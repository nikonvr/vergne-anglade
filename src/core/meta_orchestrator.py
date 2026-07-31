import asyncio
import logging
from typing import List
from src.core.models import Act, SearchQuery
from src.crawler.adapters import BaseSourceAdapter, GallicaAdapter, CsvAdapter, GeneanetAdapter
from src.genealogy.builder import TreeBuilder
from src.genealogy.models import FamilyTree

logger = logging.getLogger("certus.meta_orchestrator")

class MetaOrchestrator:
    """
    Méta-Orchestrateur Multi-Sources pour CERTUS.
    Il lance en parallèle les recherches sur toutes les sources enregistrées
    et fusionne les résultats dans l'arbre généalogique.
    """
    
    def __init__(self, sources: List[BaseSourceAdapter] | None = None):
        self.sources: List[BaseSourceAdapter] = sources if sources is not None else [
            GallicaAdapter(),
            CsvAdapter(),
            GeneanetAdapter()
        ]
        self.tree_builder = TreeBuilder()

    async def search_everywhere(self, query: SearchQuery) -> List[Act]:
        """Exécute la recherche multi-sources en parallèle via asyncio.gather()."""
        logger.info(f"🔍 Début de la recherche multi-sources pour : {query.last_name} ({query.location})")
        tasks = [source.search(query) for source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_acts: List[Act] = []
        exceptions: List[Exception] = []
        for res in results:
            if isinstance(res, list):
                all_acts.extend(res)
            elif isinstance(res, Exception):
                exceptions.append(res)
                logger.warning(f"⚠️ Échec partiel d'un adaptateur de source : {res}")

        if not all_acts and exceptions and len(exceptions) == len(self.sources):
            logger.error(f"🚨 ALERTE CRITIQUE : Toutes les sources multi-sources ({len(exceptions)}) ont échoué par exception réseau/système.")
        elif not all_acts:
            logger.info(f"ℹ️ Aucun acte trouvé pour le patronyme {query.last_name} dans les sources interrogées.")

        logger.info(f"✅ Recherche terminée : {len(all_acts)} actes agrégés de toutes les sources.")
        return all_acts

    async def build_consolidated_tree(self, query: SearchQuery) -> FamilyTree:
        """Exécute la recherche universelle et reconstruit l'arbre consolidé fusionné."""
        acts = await self.search_everywhere(query)
        return self.tree_builder.process_acts(acts)
