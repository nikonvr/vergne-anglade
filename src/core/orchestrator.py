import logging
from pathlib import Path
from src.crawler.factory import ArchiveCrawlerFactory
from src.ocr.engine import HTREngine
from src.parser.llm import LLMActParser
from src.database.engine import DatabaseManager
from src.database.repository import ActRepository
from src.genealogy.builder import TreeBuilder
from src.genealogy.models import FamilyTree
from src.core.models import Act

logger = logging.getLogger("certus.orchestrator")

class CertusOrchestrator:
    """
    Chef d'orchestre du projet CERTUS.
    Il fait le lien entre l'extraction visuelle (OCR), l'analyse sémantique (LLM),
    le stockage (DB) et la reconstruction métier (Genealogy).
    """
    # Le cache mémorise l'arbre ET le TreeBuilder qui l'a construit : le graphe networkx
    # vit sur l'instance du builder, donc servir un arbre en cache sans son builder
    # laissait le graphe vide et rendait toute analyse de parenté impossible.
    _tree_cache = {"tree": None, "builder": None, "invalidated": True}

    def __init__(self, db_manager: DatabaseManager):
        self.logger = logger
        self.db_manager = db_manager
        self.logger.info("Initialisation de l'orchestrateur de traitement...")
        self._ocr_engine = None
        self._parser_engine = None
        self._tree_builder = None

    @classmethod
    def invalidate_tree_cache(cls):
        """Marque le cache comme périmé : arbre et builder seront reconstruits."""
        cls._tree_cache["invalidated"] = True
        cls._tree_cache["builder"] = None

    @classmethod
    def reset_tree_cache(cls):
        """Vide complètement le cache. Indispensable à l'isolation entre deux tests."""
        cls._tree_cache = {"tree": None, "builder": None, "invalidated": True}

    def process_department_register(self, department_code: str, output_dir: Path | str = "downloads") -> int:
        """
        Télécharge une page de registre via le crawler du département et exécute le pipeline.
        """
        crawler = ArchiveCrawlerFactory.get_crawler(department_code)
        image_path = crawler.download_register_page(output_dir)
        return self.process_document(image_path)

    @property
    def ocr_engine(self) -> HTREngine:
        if self._ocr_engine is None:
            self._ocr_engine = HTREngine()
        return self._ocr_engine

    @property
    def parser_engine(self) -> LLMActParser:
        if self._parser_engine is None:
            self._parser_engine = LLMActParser()
        return self._parser_engine

    @property
    def tree_builder(self) -> TreeBuilder:
        if self._tree_builder is None:
            self._tree_builder = TreeBuilder()
        return self._tree_builder

    def process_document(self, image_path: Path | str, progress_callback=None) -> int:
        """
        Exécute le pipeline de bout en bout sur une image d'archive.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"L'image d'archive est introuvable : {path}")
            
        self.logger.info(f"🚀 Début du pipeline pour le document : {path.name}")
        
        try:
            # 1. Extraction visuelle (OCR)
            self.logger.info("Étape 1/3 : Reconnaissance visuelle (OCR/HTR)...")
            if progress_callback:
                progress_callback("Reconnaissance visuelle (OCR)", 33)
            raw_text = self.ocr_engine.extract_text(path)
            
            # 2. Analyse Sémantique (LLM)
            self.logger.info("Étape 2/3 : Analyse sémantique et structuration (LLM)...")
            if progress_callback:
                progress_callback("Analyse sémantique (LLM)", 66)
            act = self.parser_engine.parse(raw_text)

            # Aucune donnée simulée ne doit entrer en base sans être marquée comme telle.
            if getattr(self.ocr_engine, "last_result_simulated", False):
                act.is_simulated = True
                if not act.source_type.startswith("SIMULATED_"):
                    act.source_type = f"SIMULATED_{act.source_type}"
                act.confidence_score = 0.0
                act.reliability_score = 0.0
                self.logger.warning(
                    "Acte issu d'un OCR simulé : marqué is_simulated=True et scores à 0."
                )

            # 3. Persistance en Base de Données
            self.logger.info("Étape 3/3 : Sauvegarde relationnelle...")
            if progress_callback:
                progress_callback("Sauvegarde en base de données", 100)
            with self.db_manager.get_session() as session:
                repo = ActRepository(session)
                act_id = repo.save_act(act)
                
            self.invalidate_tree_cache()
            self.logger.info(f"✅ Pipeline terminé avec succès. Acte ID #{act_id} créé.")
            return act_id
        except Exception as e:
            self.logger.error(f"❌ Échec du pipeline pour le document {path.name} : {str(e)}")
            raise

    def generate_global_tree(self) -> FamilyTree:
        """
        Interroge la base de données pour récupérer tous les actes connus
        et lance le moteur de reconstruction généalogique avec mise en cache.
        """
        cached_builder = self._tree_cache.get("builder")
        if (
            not self._tree_cache["invalidated"]
            and self._tree_cache["tree"] is not None
            and cached_builder is not None
        ):
            # On restaure le builder d'origine : sans lui, self.tree_builder serait un
            # builder neuf au graphe vide et find_common_ancestor / get_relationship_path
            # renverraient systématiquement None et [].
            self._tree_builder = cached_builder
            self.logger.info("Retour de l'arbre généalogique depuis le cache.")
            return self._tree_cache["tree"]

        self.logger.info("Génération de l'arbre généalogique global en cours...")

        with self.db_manager.get_session() as session:
            repo = ActRepository(session)
            acts = repo.get_all_acts()

        # Construction du graphe
        tree = self.tree_builder.process_acts(acts)
        self._tree_cache["tree"] = tree
        self._tree_cache["builder"] = self.tree_builder
        self._tree_cache["invalidated"] = False

        report = self.tree_builder.validate()
        if not report["is_acyclic"]:
            self.logger.error(
                "Arbre incohérent : %d cycle(s) de filiation détecté(s). %s",
                len(report["cycles"]),
                report["cycles"],
            )
        self.logger.info(f"Arbre généré et mis en cache : {len(tree.nodes)} individus consolidés.")
        return tree
