"""Veille généalogique quotidienne : interroge les sources en ligne, persiste les actes
trouvés, puis régénère la page publique.

Contrairement à la version précédente, les actes réellement découverts sont enregistrés en
base AVANT la régénération, et la régénération ne les détruit plus : la veille accumule
désormais ses résultats au lieu de les perdre à chaque exécution.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, ".")

from scripts.build_standalone import build_standalone_html  # noqa: E402
from src.core.meta_orchestrator import MetaOrchestrator  # noqa: E402
from src.core.models import SearchQuery  # noqa: E402
from src.database.engine import DatabaseManager  # noqa: E402
from src.database.repository import ActRepository  # noqa: E402

logger = logging.getLogger("certus.cron")


async def run_daily_cron() -> int:
    """Exécute la veille. Retourne un code de sortie (0 = succès)."""
    logger.info("=== VEILLE ARCHIVISTIQUE QUOTIDIENNE CERTUS ===")
    db = DatabaseManager()
    db.init_db()

    meta_orch = MetaOrchestrator()
    # last_name= et non surname= : le champ s'appelle last_name et SearchQuery refuse
    # désormais les clés inconnues au lieu de les ignorer silencieusement.
    query = SearchQuery(last_name="VERGNE", location="Anglards-de-Salers")

    logger.info("Recherche de nouveaux actes sur les sources en ligne...")
    new_acts = []
    search_failed = False
    try:
        new_acts = await meta_orch.search_everywhere(query)
        logger.info("Résultats de recherche : %d acte(s) rapporté(s).", len(new_acts))
    except Exception as exc:
        search_failed = True
        logger.error("Échec de la recherche en ligne : %s", exc, exc_info=True)

    if new_acts:
        with db.get_session() as session:
            ids = ActRepository(session).save_acts(new_acts)
        simulated = sum(1 for act in new_acts if act.is_simulated)
        logger.info(
            "%d acte(s) persisté(s) en base, dont %d simulé(s).", len(ids), simulated
        )
    else:
        logger.info("Aucun acte nouveau à persister.")

    # Régénération du site statique. build_standalone_html lève si le GEDCOM source est
    # introuvable : on ne publie jamais un arbre vide.
    try:
        build_standalone_html()
    except FileNotFoundError as exc:
        logger.error("Régénération annulée, la page publiée est laissée intacte : %s", exc)
        return 2

    if search_failed:
        logger.warning("Page régénérée, mais la recherche en ligne a échoué.")
        return 1
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s : %(message)s"
    )
    return asyncio.run(run_daily_cron())


if __name__ == "__main__":
    raise SystemExit(main())
