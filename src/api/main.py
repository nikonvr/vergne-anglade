import asyncio
import logging
import os
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from src.core.meta_orchestrator import MetaOrchestrator
from src.core.models import Act, SearchQuery
from src.core.orchestrator import CertusOrchestrator
from src.database.engine import DatabaseManager
from src.database.repository import ActRepository
from src.export.gedcom import GedcomExporter
from src.genealogy.models import FamilyTree
from src.parser.gedcom_importer import GedcomImporter

logger = logging.getLogger("certus.api")

app = FastAPI(title="CERTUS-GENEALOGY API")

# --------------------------------------------------------------------------------------
# CORS : une origine jokers combinée à allow_credentials=True laissait n'importe quel site
# appeler l'API avec les cookies du visiteur. La liste est désormais explicite.
# --------------------------------------------------------------------------------------
DEFAULT_CORS_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"
_cors_origins = [
    origin.strip()
    for origin in (os.environ.get("CERTUS_CORS_ORIGINS") or DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip() and origin.strip() != "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
GUI_PATH = BASE_DIR / "gui" / "index.html"
PUBLIC_PAGE = Path("index.html")
DEFAULT_GEDCOM_PATH = "D:/drivefl/gene/2022/2026-02_export.ged"

db_manager = DatabaseManager()
db_manager.init_db()


def seed_from_gedcom(gedcom_path: Optional[Path | str] = None) -> int:
    """Peuple une base vide depuis le fonds GEDCOM. À appeler explicitement.

    N'est plus exécutée à l'import du module : la simple collecte des tests ouvrait et
    modifiait la base de production. Ne fabrique plus d'acte de démonstration : sans fonds
    disponible, la base reste vide.
    """
    path = Path(gedcom_path or os.environ.get("CERTUS_GEDCOM_PATH") or DEFAULT_GEDCOM_PATH)
    if not path.exists():
        logger.info("Amorçage ignoré : fonds GEDCOM introuvable (%s).", path.name)
        return 0
    with db_manager.get_session() as session:
        repo = ActRepository(session)
        if repo.count_acts():
            return 0
        acts = GedcomImporter(path).parse_branch()
        return len(repo.save_acts(acts))


# --------------------------------------------------------------------------------- sécurité
def require_token(authorization: Optional[str] = Header(None)) -> None:
    """Exige un jeton Bearer sur les endpoints qui modifient l'état ou lisent le disque."""
    expected = os.environ.get("CERTUS_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Endpoints de modification désactivés : définissez la variable "
                "d'environnement CERTUS_API_TOKEN pour les activer."
            ),
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification requis.")
    if not secrets.compare_digest(authorization[len("Bearer ") :], expected):
        raise HTTPException(status_code=403, detail="Jeton d'authentification invalide.")


def _allowed_roots() -> List[Path]:
    raw = os.environ.get("CERTUS_ALLOWED_DIRS")
    if raw:
        return [Path(p).resolve() for p in raw.split(os.pathsep) if p.strip()]
    roots = [Path.cwd().resolve()]
    gedcom_parent = Path(
        os.environ.get("CERTUS_GEDCOM_PATH") or DEFAULT_GEDCOM_PATH
    ).expanduser().parent
    try:
        roots.append(gedcom_parent.resolve())
    except OSError:  # pragma: no cover - chemin non résoluble
        pass
    return roots


def _validate_client_path(raw: str, suffixes: tuple[str, ...], label: str) -> Path:
    """Valide un chemin fourni par le client.

    Les deux endpoints acceptaient auparavant n'importe quel chemin local, sans
    authentification, et renvoyaient le chemin absolu dans le message d'erreur.
    """
    if not raw or not str(raw).strip():
        raise HTTPException(status_code=400, detail=f"{label} : chemin manquant.")
    try:
        candidate = Path(raw).expanduser().resolve(strict=False)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} : chemin invalide.")

    roots = _allowed_roots()
    if not any(candidate == root or root in candidate.parents for root in roots):
        # Le chemin réel n'est journalisé que côté serveur.
        logger.warning("Chemin refusé (hors racines autorisées) : %s", candidate)
        raise HTTPException(
            status_code=403,
            detail=f"{label} : chemin hors des répertoires autorisés.",
        )
    if suffixes and candidate.suffix.lower() not in suffixes:
        raise HTTPException(
            status_code=400,
            detail=f"{label} : extension non autorisée (attendu : {', '.join(suffixes)}).",
        )
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"{label} : fichier introuvable.")
    return candidate


# ------------------------------------------------------------------------------ websocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception as exc:
                logger.debug("Diffusion websocket impossible, connexion retirée : %s", exc)
                self.disconnect(connection)


ws_manager = ConnectionManager()


# --------------------------------------------------------------------------------- modèles
class StatsResponse(BaseModel):
    total_acts: int
    total_persons: int
    families_reconstructed: int
    confidence_average: Optional[float] = None
    simulated_acts: int = 0


class ActResponse(BaseModel):
    id: int
    type: str
    date: Optional[str] = None
    location: Optional[str] = None
    principals: List[str]
    confidence: float
    is_simulated: bool = False


class ProcessRequest(BaseModel):
    image_path: str


class ProcessResponse(BaseModel):
    status: str
    act_id: int
    is_simulated: bool = False


class RelationshipAnalysisResponse(BaseModel):
    person1: str
    person2: str
    common_ancestor: Optional[str] = None
    relationship_path: List[str] = Field(default_factory=list)
    degree: int = 0


class PersonDetail(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    age: Optional[int] = None
    occupation: Optional[str] = None
    sex: Optional[str] = None
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    death_date: Optional[str] = None
    death_place: Optional[str] = None


class ActDetailResponse(BaseModel):
    id: int
    act_type: str
    date: Optional[str] = None
    location: Optional[str] = None
    confidence_score: float
    source_text: Optional[str] = None
    source_type: str
    url_source: Optional[str] = None
    is_simulated: bool = False
    persons: List[PersonDetail]


class GedcomImportRequest(BaseModel):
    gedcom_path: Optional[str] = None


class GedcomImportResponse(BaseModel):
    status: str
    imported_count: int


class MultiSourceSearchResponse(BaseModel):
    total_acts: int
    acts: List[ActResponse]
    simulated_acts: int = 0


# ---------------------------------------------------------------------------------- helpers
def _get_orchestrator() -> CertusOrchestrator:
    return CertusOrchestrator(db_manager)


def _get_global_tree() -> FamilyTree:
    return _get_orchestrator().generate_global_tree()


def _format_act_response(act: Act, fallback_id: int = 0) -> dict:
    principals = [
        f"{p.last_name or ''} {p.first_name or ''}".strip() for p in act.persons if p.last_name
    ]
    return {
        "id": act.id if act.id is not None else fallback_id,
        "type": act.act_type or "Inconnu",
        "date": act.date,
        "location": act.location,
        "principals": principals or ["Inconnu"],
        "confidence": act.confidence_score,
        "is_simulated": act.is_simulated,
    }


# --------------------------------------------------------------------------------- endpoints
@app.websocket("/ws/progress")
async def websocket_progress_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/", response_class=HTMLResponse)
async def serve_gui():
    """Sert le tableau de bord interne."""
    return FileResponse(GUI_PATH)


@app.get("/standalone", response_class=HTMLResponse)
async def serve_public_page():
    """Sert la page publique générée par scripts/build_standalone.py."""
    if PUBLIC_PAGE.exists():
        return FileResponse(PUBLIC_PAGE)
    return FileResponse(GUI_PATH)


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Statistiques globales calculées depuis la base, sans valeur de repli inventée."""
    with db_manager.get_session() as session:
        acts = ActRepository(session).get_all_acts()
    total_acts = len(acts)
    simulated = sum(1 for a in acts if a.is_simulated)
    sourced = [a for a in acts if not a.is_simulated]
    average = (
        round(sum(a.confidence_score for a in sourced) / len(sourced), 2) if sourced else None
    )
    return {
        "total_acts": total_acts,
        "total_persons": sum(len(a.persons) for a in acts),
        "families_reconstructed": len(_get_global_tree().nodes),
        "confidence_average": average,
        "simulated_acts": simulated,
    }


@app.get("/api/tree", response_model=FamilyTree)
async def get_global_tree(
    person_id: Optional[str] = None,
    up: int = 3,
    down: int = 3,
    include_siblings: bool = True,
):
    """Arbre généalogique reconstruit.

    Sans person_id : arbre complet (comportement inchangé, rétrocompatible). Avec
    person_id : sous-arbre centré sur cette personne, borné à `up` générations
    d'ascendants et `down` générations de descendants.
    """
    orchestrator = _get_orchestrator()
    tree = orchestrator.generate_global_tree()
    if person_id is None:
        return tree
    if person_id not in tree.nodes:
        raise HTTPException(status_code=404, detail="Personne non trouvée.")
    return orchestrator.tree_builder.subtree(
        tree, person_id, up=up, down=down, include_siblings=include_siblings
    )


@app.get("/api/relationship", response_model=RelationshipAnalysisResponse)
async def analyze_relationship(p1: str, p2: str):
    """Ancêtre commun et chemin de parenté entre deux individus."""
    orchestrator = _get_orchestrator()
    orchestrator.generate_global_tree()
    ancestor = orchestrator.tree_builder.find_common_ancestor(p1, p2)
    path = orchestrator.tree_builder.get_relationship_path(p1, p2)
    return {
        "person1": p1,
        "person2": p2,
        "common_ancestor": ancestor,
        "relationship_path": path,
        "degree": max(0, len(path) - 1),
    }


@app.get("/api/export/json")
async def export_json_graph():
    """Graphe au format JSON (nœuds et liens) pour un rendu D3.js."""
    tree = _get_global_tree()
    return {
        "nodes": [
            {
                "id": nid,
                "name": f"{p.first_name} {p.last_name}".strip(),
                "mentions": p.mentions,
                "occupation": p.occupation,
                "birth_date": p.birth_date,
                "death_date": p.death_date,
            }
            for nid, p in tree.nodes.items()
        ],
        "links": [
            {"source": e.source_id, "target": e.target_id, "type": e.rel_type}
            for e in tree.edges
        ],
    }


@app.get("/api/export/mermaid")
async def export_mermaid_endpoint(
    person_id: Optional[str] = None,
    up: int = 3,
    down: int = 3,
    include_siblings: bool = True,
):
    """Syntaxe Mermaid du diagramme, complet ou restreint à un sous-arbre (voir /api/tree)."""
    orchestrator = _get_orchestrator()
    tree = orchestrator.generate_global_tree()
    if person_id is not None:
        if person_id not in tree.nodes:
            raise HTTPException(status_code=404, detail="Personne non trouvée.")
        tree = orchestrator.tree_builder.subtree(
            tree, person_id, up=up, down=down, include_siblings=include_siblings
        )
    return {"mermaid": GedcomExporter().export_mermaid(tree)}


@app.get("/api/export/gedcom")
async def export_gedcom():
    """Télécharge l'arbre au format GEDCOM 5.5.1."""
    return Response(
        content=GedcomExporter().export_string(_get_global_tree()),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=certus_genealogy.ged"},
    )


@app.get("/api/acts/recent", response_model=List[ActResponse])
async def get_recent_acts(limit: int = 50, offset: int = 0):
    """Liste paginée des actes. Les identifiants sont les clés primaires réelles."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit doit être compris entre 1 et 500.")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset doit être positif.")
    with db_manager.get_session() as session:
        acts = ActRepository(session).get_all_acts()
    window = acts[offset : offset + limit]
    return [_format_act_response(act) for act in window]


@app.get("/api/acts/{act_id}", response_model=ActDetailResponse)
async def get_act_detail(act_id: int):
    """Détail d'un acte par sa clé primaire (et non par sa position dans la liste)."""
    with db_manager.get_session() as session:
        act = ActRepository(session).get_act_by_id(act_id)
    if act is None:
        raise HTTPException(status_code=404, detail="Acte non trouvé.")
    return {
        "id": act.id,
        "act_type": act.act_type,
        "date": act.date,
        "location": act.location,
        "confidence_score": act.confidence_score,
        "source_text": act.source_text,
        "source_type": act.source_type,
        "url_source": act.url_source,
        "is_simulated": act.is_simulated,
        "persons": [
            PersonDetail(
                first_name=p.first_name,
                last_name=p.last_name,
                role=p.role,
                age=p.age,
                occupation=p.occupation,
                sex=p.sex,
                birth_date=p.birth_date,
                birth_place=p.birth_place,
                death_date=p.death_date,
                death_place=p.death_place,
            )
            for p in act.persons
        ],
    }


@app.post(
    "/api/pipeline/process",
    response_model=ProcessResponse,
    dependencies=[Depends(require_token)],
)
async def process_document_endpoint(payload: ProcessRequest):
    """Déclenche le traitement d'une image d'archive située dans un répertoire autorisé."""
    image_path = _validate_client_path(
        payload.image_path, (".jpg", ".jpeg", ".png", ".tif", ".tiff"), "Image d'archive"
    )
    loop = asyncio.get_running_loop()

    def sync_progress(step: str, percentage: int):
        # Le callback est appelé depuis le thread d'exécution : on repasse par la boucle.
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast({"step": step, "percentage": percentage}), loop
        )

    orchestrator = _get_orchestrator()
    try:
        act_id = await asyncio.to_thread(
            orchestrator.process_document, image_path, sync_progress
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image d'archive introuvable.")
    except Exception as exc:
        # Le détail technique reste côté serveur : il divulguait chemins et traces internes.
        logger.error("Échec du pipeline : %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Échec du traitement du document.")
    return {
        "status": "success",
        "act_id": act_id,
        "is_simulated": bool(getattr(orchestrator.ocr_engine, "last_result_simulated", False)),
    }


@app.post(
    "/api/import/gedcom",
    response_model=GedcomImportResponse,
    dependencies=[Depends(require_token)],
)
async def import_gedcom_endpoint(payload: GedcomImportRequest):
    """Importe la branche depuis un fichier GEDCOM d'un répertoire autorisé."""
    raw_path = payload.gedcom_path or os.environ.get("CERTUS_GEDCOM_PATH") or DEFAULT_GEDCOM_PATH
    gedcom_path = _validate_client_path(raw_path, (".ged",), "Fichier GEDCOM")
    try:
        acts = GedcomImporter(gedcom_path).parse_branch()
        with db_manager.get_session() as session:
            ActRepository(session).save_acts(acts)
    except Exception as exc:
        logger.error("Échec de l'import GEDCOM : %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Échec de l'import du fichier GEDCOM.")
    CertusOrchestrator.invalidate_tree_cache()
    return {"status": "success", "imported_count": len(acts)}


@app.post("/api/search", response_model=MultiSourceSearchResponse)
async def multi_source_search_endpoint(query: SearchQuery):
    """Recherche parallèle sur toutes les sources enregistrées."""
    acts = await MetaOrchestrator().search_everywhere(query)
    return {
        "total_acts": len(acts),
        "acts": [_format_act_response(act, idx) for idx, act in enumerate(acts, 1)],
        "simulated_acts": sum(1 for act in acts if act.is_simulated),
    }
