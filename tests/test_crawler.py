import pytest
from pathlib import Path
import src.crawler
from src.crawler.factory import ArchiveCrawlerFactory
from src.crawler.cantal import CantalCrawler
from src.crawler.puy_de_dome import PuyDeDomeCrawler

def test_crawler_factory_multi_departments(tmp_path):
    # Test Cantal (15)
    cantal_crawler = ArchiveCrawlerFactory.get_crawler("15")
    assert isinstance(cantal_crawler, CantalCrawler)
    assert cantal_crawler.verify_connection() is True

    file_15 = cantal_crawler.download_register_page(tmp_path)
    assert file_15.exists()
    assert file_15.name == "cantal_register_page.jpg"

    # Test Puy-de-Dôme (63)
    puy_crawler = ArchiveCrawlerFactory.get_crawler("63")
    assert isinstance(puy_crawler, PuyDeDomeCrawler)
    assert puy_crawler.verify_connection() is True

    file_63 = puy_crawler.download_register_page(tmp_path)
    assert file_63.exists()
    assert file_63.name == "puy_de_dome_register_page.jpg"
