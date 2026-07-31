from pathlib import Path
from src.crawler.base import BaseArchiveCrawler
from src.crawler.factory import ArchiveCrawlerFactory

@ArchiveCrawlerFactory.register("63")
class PuyDeDomeCrawler(BaseArchiveCrawler):
    """Robot de collecte des Archives départementales du Puy-de-Dôme (63)."""

    REGISTER_FILENAME = "puy_de_dome_register_page.jpg"
    SOURCE_LABEL = "des Archives départementales du Puy-de-Dôme (63)"

    @property
    def department_code(self) -> str:
        return "63"

    @property
    def base_url(self) -> str:
        return "https://www.archivesdepartmentales.puy-de-dome.fr/"

    def verify_connection(self) -> bool:
        return True

    def download_register_page(self, output_dir: Path | str) -> Path:
        """
        Récupère une page de registre.

        Le téléchargement réel n'étant pas implémenté, cette méthode lève
        NotImplementedError sauf si la simulation est autorisée
        (CERTUS_ALLOW_SIMULATED=1) : dans ce cas un fichier de substitution
        marqué comme simulé est écrit et last_download_simulated vaut True.
        """
        return self._write_simulated_register_page(output_dir, self.REGISTER_FILENAME, self.SOURCE_LABEL)
