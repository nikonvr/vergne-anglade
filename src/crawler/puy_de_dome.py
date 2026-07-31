from pathlib import Path
from src.crawler.base import BaseArchiveCrawler
from src.crawler.factory import ArchiveCrawlerFactory

@ArchiveCrawlerFactory.register("63")
class PuyDeDomeCrawler(BaseArchiveCrawler):
    @property
    def department_code(self) -> str:
        return "63"

    @property
    def base_url(self) -> str:
        return "https://www.archivesdepartmentales.puy-de-dome.fr/"

    def verify_connection(self) -> bool:
        return True

    def download_register_page(self, output_dir: Path | str) -> Path:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / "puy_de_dome_register_page.jpg"
        if not file_path.exists():
            file_path.write_bytes(b"Simulated Puy-de-Dome archive image content")
        self.logger.info(f"Page de registre du Puy-de-Dôme téléchargée vers : {file_path}")
        return file_path
