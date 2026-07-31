import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from src.database.engine import DatabaseManager
from src.core.orchestrator import CertusOrchestrator
from src.genealogy.models import FamilyTree
from src.export.gedcom import GedcomExporter

app = FastAPI(title="CERTUS-GENEALOGY API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

BASE_DIR = Path(__file__).resolve().parent.parent
GUI_PATH = BASE_DIR / "gui" / "index.html"

from src.core.models import Act, Person
from src.database.repository import ActRepository
from src.parser.gedcom_importer import GedcomImporter

db_manager = DatabaseManager()
db_manager.init_db()

def seed_initial_data_if_empty():
    try:
        with db_manager.get_session() as session:
            repo = ActRepository(session)
            acts = repo.get_all_acts()
            if not acts:
                gedcom_path = Path("D:/drivefl/gene/2022/2026-02_export.ged")
                if gedcom_path.exists():
                    try:
                        importer = GedcomImporter(gedcom_path)
                        vergne_acts = importer.parse_vergne_branch()
                        for act in vergne_acts:
                            repo.save_act(act)
                    except Exception:
                        session.rollback()

                if not repo.get_all_acts():
                    initial_act = Act(
                        act_type="Naissance",
                        date="1841-05-02",
                        location="Anglards-de-Salers",
                        confidence_score=0.95,
                        source_text="L'an 1841 le 2 mai est né Jean VERGNE fils de Pierre VERGNE à Anglards-de-Salers.",
                        persons=[
                            Person(first_name="Jean", last_name="VERGNE", role="enfant"),
                            Person(first_name="Pierre", last_name="VERGNE", role="père", occupation="laboureur")
                        ]
                    )
                    repo.save_act(initial_act)
    except Exception:
        pass

seed_initial_data_if_empty()

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
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                pass

ws_manager = ConnectionManager()

class StatsResponse(BaseModel):
    total_acts: int
    total_persons: int
    families_reconstructed: int
    confidence_average: float

class ActResponse(BaseModel):
    id: int
    type: str
    date: str
    location: str
    principals: List[str]
    confidence: float

class ProcessRequest(BaseModel):
    image_path: str

class ProcessResponse(BaseModel):
    status: str
    act_id: int

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
    """Sert l'interface graphique principale."""
    return FileResponse(GUI_PATH)

@app.get("/standalone", response_class=HTMLResponse)
async def serve_standalone_gui():
    """Sert la page HTML autonome grand public."""
    standalone_path = Path("vergne_genealogy_standalone.html")
    if standalone_path.exists():
        return FileResponse(standalone_path)
    return FileResponse(GUI_PATH)

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Retourne les statistiques globales calculées depuis la base de données."""
    with db_manager.get_session() as session:
        repo = ActRepository(session)
        acts = repo.get_all_acts()
        total_acts = len(acts)
        total_persons = sum(len(a.persons) for a in acts)
        orchestrator = CertusOrchestrator(db_manager)
        tree = orchestrator.generate_global_tree()
        families_count = len(tree.nodes)
        avg_confidence = sum(a.confidence_score for a in acts) / total_acts if total_acts > 0 else 0.90
        return {
            "total_acts": total_acts,
            "total_persons": total_persons,
            "families_reconstructed": families_count,
            "confidence_average": round(avg_confidence, 2)
        }

@app.get("/api/tree", response_model=FamilyTree)
async def get_global_tree():
    """Génère et retourne l'arbre généalogique reconstruit."""
    orchestrator = CertusOrchestrator(db_manager)
    return orchestrator.generate_global_tree()

class RelationshipAnalysisResponse(BaseModel):
    person1: str
    person2: str
    common_ancestor: Optional[str] = None
    relationship_path: List[str] = Field(default_factory=list)
    degree: int = 0

@app.get("/api/relationship", response_model=RelationshipAnalysisResponse)
async def analyze_relationship(p1: str, p2: str):
    """Calcule l'ancêtre commun et le chemin de parenté entre deux individus."""
    orchestrator = CertusOrchestrator(db_manager)
    tree = orchestrator.generate_global_tree()
    ancestor = orchestrator.tree_builder.find_common_ancestor(p1, p2)
    path = orchestrator.tree_builder.get_relationship_path(p1, p2)
    return {
        "person1": p1,
        "person2": p2,
        "common_ancestor": ancestor,
        "relationship_path": path,
        "degree": max(0, len(path) - 1)
    }

@app.get("/api/export/json")
async def export_json_graph():
    """Exporte le graphe généalogique au format JSON (nœuds et liens) pour D3.js."""
    orchestrator = CertusOrchestrator(db_manager)
    tree = orchestrator.generate_global_tree()
    nodes = [
        {
            "id": nid,
            "name": f"{p.first_name} {p.last_name}",
            "mentions": p.mentions,
            "occupation": p.occupation
        }
        for nid, p in tree.nodes.items()
    ]
    links = [
        {
            "source": e.source_id,
            "target": e.target_id,
            "type": e.rel_type
        }
        for e in tree.edges
    ]
    return {"nodes": nodes, "links": links}

@app.get("/api/export/mermaid")
async def export_mermaid_endpoint():
    """Génère la syntaxe du diagramme graphique Mermaid pour le rendu dans l'UI."""
    orchestrator = CertusOrchestrator(db_manager)
    tree = orchestrator.generate_global_tree()
    exporter = GedcomExporter()
    return {"mermaid": exporter.export_mermaid(tree)}

@app.get("/api/export/gedcom")
async def export_gedcom():
    """Génère et télécharge l'arbre généalogique au format GEDCOM (.ged)."""
    orchestrator = CertusOrchestrator(db_manager)
    tree = orchestrator.generate_global_tree()
    exporter = GedcomExporter()
    gedcom_data = exporter.export_string(tree)
    return Response(
        content=gedcom_data,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=certus_genealogy.ged"}
    )

@app.get("/api/acts/recent", response_model=List[ActResponse])
async def get_recent_acts():
    """Retourne la liste des actes de la base de données."""
    with db_manager.get_session() as session:
        repo = ActRepository(session)
        acts = repo.get_all_acts()
        result = []
        for idx, act in enumerate(acts, 1):
            principals = [f"{p.last_name or ''} {p.first_name or ''}".strip() for p in act.persons if p.last_name]
            if not principals:
                principals = ["Inconnu"]
            result.append({
                "id": idx,
                "type": act.act_type or "Inconnu",
                "date": act.date or "S.D.",
                "location": act.location or "Non précisé",
                "principals": principals,
                "confidence": act.confidence_score
            })
        return result

class PersonDetail(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    age: Optional[int] = None
    occupation: Optional[str] = None

class ActDetailResponse(BaseModel):
    id: int
    act_type: str
    date: Optional[str] = None
    location: Optional[str] = None
    confidence_score: float
    source_text: Optional[str] = None
    persons: List[PersonDetail]

@app.get("/api/acts/{act_id}", response_model=ActDetailResponse)
async def get_act_detail(act_id: int):
    """Retourne les détails complets d'un acte par son identifiant."""
    with db_manager.get_session() as session:
        repo = ActRepository(session)
        acts = repo.get_all_acts()
        if act_id < 1 or act_id > len(acts):
            raise HTTPException(status_code=404, detail="Acte non trouvé")
        act = acts[act_id - 1]
        persons_detail = [
            PersonDetail(
                first_name=p.first_name,
                last_name=p.last_name,
                role=p.role,
                age=p.age,
                occupation=p.occupation
            )
            for p in act.persons
        ]
        return {
            "id": act_id,
            "act_type": act.act_type,
            "date": act.date,
            "location": act.location,
            "confidence_score": act.confidence_score,
            "source_text": act.source_text,
            "persons": persons_detail
        }

@app.post("/api/pipeline/process", response_model=ProcessResponse)
async def process_document_endpoint(payload: ProcessRequest):
    """Déclenche le traitement d'un document via l'orchestrateur."""
    try:
        orchestrator = CertusOrchestrator(db_manager)

        def sync_progress(step: str, percentage: int):
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast({"step": step, "percentage": percentage}), loop
                )
            except RuntimeError:
                pass

        act_id = orchestrator.process_document(payload.image_path, progress_callback=sync_progress)
        return {"status": "success", "act_id": act_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class GedcomImportRequest(BaseModel):
    gedcom_path: Optional[str] = "D:/drivefl/gene/2022/2026-02_export.ged"

class GedcomImportResponse(BaseModel):
    status: str
    imported_count: int

@app.post("/api/import/gedcom", response_model=GedcomImportResponse)
async def import_gedcom_endpoint(payload: GedcomImportRequest):
    """Importe la branche VERGNE depuis un fichier GEDCOM local."""
    target_path = payload.gedcom_path or "D:/drivefl/gene/2022/2026-02_export.ged"
    try:
        importer = GedcomImporter(target_path)
        acts = importer.parse_vergne_branch()
        with db_manager.get_session() as session:
            repo = ActRepository(session)
            for act in acts:
                repo.save_act(act)
        return {"status": "success", "imported_count": len(acts)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class MultiSourceSearchResponse(BaseModel):
    total_acts: int
    acts: List[ActResponse]

from src.core.models import SearchQuery
from src.core.meta_orchestrator import MetaOrchestrator

@app.post("/api/search", response_model=MultiSourceSearchResponse)
async def multi_source_search_endpoint(query: SearchQuery):
    """Effectue une recherche universelle parallèle sur toutes les sources enregistrées."""
    meta = MetaOrchestrator()
    acts = await meta.search_everywhere(query)
    results = []
    for idx, act in enumerate(acts, 1):
        principals = [f"{p.last_name or ''} {p.first_name or ''}".strip() for p in act.persons if p.last_name]
        if not principals:
            principals = ["Inconnu"]
        results.append({
            "id": idx,
            "type": act.act_type or "Inconnu",
            "date": act.date or "S.D.",
            "location": act.location or "Non précisé",
            "principals": principals,
            "confidence": act.confidence_score
        })
    return {"total_acts": len(results), "acts": results}

