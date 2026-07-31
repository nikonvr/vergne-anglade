import sys
import asyncio
import shutil
from pathlib import Path

sys.path.insert(0, ".")

from src.database.engine import DatabaseManager
from src.database.repository import ActRepository
from src.core.meta_orchestrator import MetaOrchestrator
from src.core.models import SearchQuery
from scripts.build_standalone import build_standalone_html

async def run_daily_cron():
    print("=== CERTUS DAILY ARCHIVAL CRON ===")
    db = DatabaseManager("sqlite:///certus_genealogy.db")
    db.init_db()
    
    meta_orch = MetaOrchestrator()
    query = SearchQuery(surname="VERGNE", location="Anglards-de-Salers")
    
    print("Recherche de nouveaux actes sur les sources en ligne (Gallica BnF, Mémoire des Hommes)...")
    try:
        new_acts = await meta_orch.search_everywhere(query)
        print(f"Résultats de recherche : {len(new_acts)} actes analysés/mis à jour.")
    except Exception as e:
        print(f"Avertissement lors de la recherche en ligne : {e}")

    # Re-génération du site statique autonome
    build_standalone_html()
    
    # Copie vers index.html pour GitHub Pages
    if Path("vergne_genealogy_standalone.html").exists():
        shutil.copy("vergne_genealogy_standalone.html", "index.html")
        print("Mise à jour de index.html terminée avec succès.")

if __name__ == "__main__":
    asyncio.run(run_daily_cron())
