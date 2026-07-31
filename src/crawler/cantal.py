from pathlib import Path
from src.crawler.base import BaseArchiveCrawler
from src.crawler.factory import ArchiveCrawlerFactory

@ArchiveCrawlerFactory.register("15")
class CantalCrawler(BaseArchiveCrawler):
    @property
    def department_code(self) -> str: return "15"
    @property
    def base_url(self) -> str: return "https://archives.cantal.fr/"
    def verify_connection(self) -> bool: return True

    def download_register_page(self, output_dir: Path | str) -> Path:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / "cantal_register_page.jpg"
        if not file_path.exists():
            file_path.write_bytes(b"Simulated Cantal archive image content")
        self.logger.info(f"Page de registre téléchargée vers : {file_path}")
        return file_path