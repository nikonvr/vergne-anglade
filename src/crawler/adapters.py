import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from src.core.models import Act, Person, SearchQuery
from src.core.simulation import SimulationDisabledError, require_simulation, simulated_source_type
from src.crawler.gallica import GallicaAPIClient
from src.parser.csv_importer import CsvImporter

logger = logging.getLogger("certus.crawler.adapters")


class BaseSourceAdapter(ABC):
    """Classe de base abstraite pour tous les adaptateurs de recherche multi-sources."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> List[Act]:
        pass


def _build_search_expression(query: SearchQuery) -> str:
    """
    Assemble l'expression de recherche plein texte à partir des critères non vides.

    Seuls le patronyme et le lieu sont retenus (comportement historique) : ajouter
    le prénom restreindrait trop la recherche plein texte dans la presse.
    """
    parts = [part.strip() for part in (query.last_name, query.location) if part and part.strip()]
    return " AND ".join(parts)


class GallicaAdapter(BaseSourceAdapter):
    """Adaptateur de recherche pour la presse historique Gallica / BnF (source réelle, API SRU)."""

    def __init__(self, client: GallicaAPIClient | None = None, max_records: int | None = None, timeout: float | None = None):
        self.client = client if client is not None else GallicaAPIClient(max_records=max_records, timeout=timeout)
        self.max_records = max_records

    async def search(self, query: SearchQuery) -> List[Act]:
        search_str = _build_search_expression(query)
        if not search_str:
            logger.info("Recherche Gallica ignorée : aucun critère de recherche exploitable.")
            return []
        return self.client.search_press_articles(query=search_str, max_records=self.max_records)


class CsvAdapter(BaseSourceAdapter):
    """Adaptateur de recherche pour les dépouillements associatifs au format CSV."""

    def __init__(self, csv_path: Path | str | None = None):
        self.csv_path = Path(csv_path) if csv_path else None

    async def search(self, query: SearchQuery) -> List[Act]:
        if not self.csv_path or not self.csv_path.exists():
            return []
        importer = CsvImporter(self.csv_path)
        return importer.parse_acts(surname_filter=query.last_name)


class MemoireDesHommesAdapter(BaseSourceAdapter):
    """
    Adaptateur pour les registres militaires Mémoire des Hommes / Série R.

    ATTENTION : aucune interrogation réelle de Mémoire des Hommes n'est implémentée.
    L'adaptateur ne produit donc rien, sauf si la simulation est explicitement
    autorisée (CERTUS_ALLOW_SIMULATED=1), auquel cas l'acte renvoyé est marqué
    comme simulé (is_simulated=True, scores à 0.0).
    """

    COMPONENT = "MemoireDesHommesAdapter"

    async def search(self, query: SearchQuery) -> List[Act]:
        if not query.last_name:
            return []

        try:
            require_simulation(self.COMPONENT)
        except SimulationDisabledError as err:
            # On ne propage pas l'exception : asyncio.gather() du méta-orchestrateur
            # doit continuer à agréger les sources réellement disponibles.
            logger.warning(
                "Adaptateur Mémoire des Hommes désactivé : aucune interrogation réelle n'est "
                "implémentée et la simulation est interdite (%s). Aucun acte produit.",
                err,
            )
            return []

        act = Act(
            act_type="Matricule Militaire",
            date=None,
            location=query.location,
            confidence_score=0.0,
            source_text=(
                "[DONNÉE SIMULÉE] Registre de matricule militaire pour le patronyme "
                f"{query.last_name} — aucune consultation réelle de Mémoire des Hommes."
            ),
            source_type=simulated_source_type("MILITAIRE_MEMOIRE_DES_HOMMES"),
            url_source="https://www.memoiredeshommes.sga.defense.gouv.fr/",
            reliability_score=0.0,
            is_simulated=True,
            persons=[
                Person(first_name=query.first_name, last_name=query.last_name, role="soldat")
            ],
        )
        logger.warning("Acte SIMULÉ produit par %s (mode simulation autorisé).", self.COMPONENT)
        return [act]


class GeneanetAdapter(BaseSourceAdapter):
    """
    Adaptateur Geneanet.

    Les identifiants proviennent EXCLUSIVEMENT de l'environnement
    (GENEANET_USERNAME / GENEANET_PASSWORD) ou des paramètres du constructeur :
    aucune valeur par défaut n'est codée en dur.

    ATTENTION : aucune interrogation réelle de Geneanet n'est implémentée.
    L'adaptateur ne produit donc rien, sauf si la simulation est explicitement
    autorisée (CERTUS_ALLOW_SIMULATED=1), auquel cas l'acte renvoyé est marqué
    comme simulé (is_simulated=True, scores à 0.0).
    """

    COMPONENT = "GeneanetAdapter"

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        self.username: Optional[str] = username if username is not None else os.environ.get("GENEANET_USERNAME")
        self.password: Optional[str] = password if password is not None else os.environ.get("GENEANET_PASSWORD")
        self.is_authenticated: bool = bool(self.username and self.password)

    async def search(self, query: SearchQuery) -> List[Act]:
        if not query.last_name:
            return []

        try:
            require_simulation(self.COMPONENT)
        except SimulationDisabledError as err:
            # Idem : retour d'une liste vide pour ne pas casser asyncio.gather().
            logger.warning(
                "Adaptateur Geneanet désactivé : aucune interrogation réelle n'est implémentée "
                "et la simulation est interdite (%s). Aucun acte produit.",
                err,
            )
            return []

        access_level = "PREMIUM" if self.is_authenticated else "PUBLIC"
        identite = " ".join(part for part in ((query.first_name or "").strip(), query.last_name) if part)
        act = Act(
            act_type="Recherche Geneanet (INSEE / Arbres)",
            date=None,
            location=query.location,
            confidence_score=0.0,
            source_text=(
                f"[DONNÉE SIMULÉE] Relevé Geneanet ({access_level}) pour {identite} "
                "— aucune consultation réelle de Geneanet."
            ),
            source_type=simulated_source_type(f"GENEANET_{access_level}"),
            url_source=f"https://www.geneanet.org/fonds/individus/?go=1&nom={query.last_name}",
            reliability_score=0.0,
            is_simulated=True,
            persons=[
                Person(
                    first_name=query.first_name,
                    last_name=query.last_name,
                    role="principal",
                )
            ],
        )
        logger.warning("Acte SIMULÉ produit par %s (mode simulation autorisé).", self.COMPONENT)
        return [act]
