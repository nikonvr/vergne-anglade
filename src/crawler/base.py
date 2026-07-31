from abc import ABC, abstractmethod
import logging
from pathlib import Path

from src.core.simulation import simulation_allowed


class BaseArchiveCrawler(ABC):
    """
    Base des robots de collecte des archives départementales.

    Aucun robot ne doit produire un fichier « plausible » à la place d'une vraie
    numérisation : tant que le téléchargement réel n'est pas implémenté,
    download_register_page() doit échouer explicitement. Le mode simulation
    (CERTUS_ALLOW_SIMULATED=1) permet un fichier de substitution, mais celui-ci
    est marqué comme simulé et l'appelant peut le détecter via
    last_download_simulated.
    """

    @property
    @abstractmethod
    def department_code(self) -> str: pass
    @property
    @abstractmethod
    def base_url(self) -> str: pass

    def __init__(self):
        self.logger = logging.getLogger(f"certus.crawler.{self.department_code}")
        self._last_download_simulated = False

    @property
    def last_download_simulated(self) -> bool:
        """True si le dernier fichier produit est une simulation, non une numérisation réelle."""
        return self._last_download_simulated

    def is_simulated(self) -> bool:
        """Alias explicite de last_download_simulated, pour les appelants procéduraux."""
        return self._last_download_simulated

    @abstractmethod
    def verify_connection(self) -> bool: pass
    @abstractmethod
    def download_register_page(self, output_dir: Path | str) -> Path: pass

    def _write_simulated_register_page(self, output_dir: Path | str, filename: str, source_label: str) -> Path:
        """
        Écrit un fichier de substitution EXPLICITEMENT marqué comme simulé.

        Lève NotImplementedError si la simulation n'est pas autorisée : c'est le
        comportement normal, le téléchargement réel n'étant pas implémenté.
        """
        self._last_download_simulated = False
        if not simulation_allowed():
            raise NotImplementedError(
                f"Le téléchargement réel des registres {source_label} n'est pas implémenté "
                f"({self.base_url}) : aucune image d'archive ne peut être produite. "
                "Définissez CERTUS_ALLOW_SIMULATED=1 pour obtenir à la place un fichier "
                "de substitution explicitement marqué comme simulé."
            )

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / filename
        file_path.write_bytes(
            "[FICHIER SIMULÉ - CERTUS]\n"
            f"Département : {self.department_code}\n"
            f"Source annoncée : {source_label} ({self.base_url})\n"
            "Ce fichier ne contient AUCUNE numérisation d'archive : il est généré "
            "uniquement parce que CERTUS_ALLOW_SIMULATED=1. Toute donnée qui en "
            "découlerait doit être considérée comme simulée.\n".encode("utf-8")
        )
        self._last_download_simulated = True
        self.logger.warning(
            f"Fichier SIMULÉ écrit (aucun téléchargement réel) pour {source_label} : {file_path}"
        )
        return file_path
