"""Crawlers d'archives départementales (constat M3).

Les crawlers écrivaient b"Simulated ... content" en se présentant comme un téléchargement
réussi, et l'ancien test se contentait de vérifier qu'un fichier existait.
"""

import pytest

import src.crawler  # noqa: F401  (enregistre les crawlers dans la factory)
from src.core.simulation import SimulationDisabledError
from src.crawler.cantal import CantalCrawler
from src.crawler.factory import ArchiveCrawlerFactory
from src.crawler.puy_de_dome import PuyDeDomeCrawler


@pytest.mark.parametrize(
    "code, expected_class",
    [("15", CantalCrawler), ("63", PuyDeDomeCrawler)],
)
def test_factory_resout_le_bon_crawler(code, expected_class):
    crawler = ArchiveCrawlerFactory.get_crawler(code)
    assert isinstance(crawler, expected_class)
    assert crawler.department_code == code


def test_factory_refuse_un_departement_inconnu():
    with pytest.raises(ValueError):
        ArchiveCrawlerFactory.get_crawler("99")


@pytest.mark.parametrize("code", ["15", "63"])
def test_telechargement_refuse_sans_autorisation(code, tmp_path):
    """M3 : sans téléchargement réel implémenté, le crawler échoue au lieu de simuler."""
    crawler = ArchiveCrawlerFactory.get_crawler(code)
    with pytest.raises((SimulationDisabledError, NotImplementedError)):
        crawler.download_register_page(tmp_path)
    assert crawler.last_download_simulated is False


@pytest.mark.parametrize("code", ["15", "63"])
def test_telechargement_simule_est_marque(code, tmp_path, allow_simulation):
    """M3 : le fichier de substitution est explicitement identifié comme simulé."""
    crawler = ArchiveCrawlerFactory.get_crawler(code)
    path = crawler.download_register_page(tmp_path)

    assert path.exists()
    assert crawler.last_download_simulated is True
    assert "SIMUL" in path.read_bytes().decode("utf-8", errors="ignore").upper()
