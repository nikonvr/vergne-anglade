from abc import ABC, abstractmethod
import logging
from pathlib import Path

class BaseArchiveCrawler(ABC):
    @property
    @abstractmethod
    def department_code(self) -> str: pass
    @property
    @abstractmethod
    def base_url(self) -> str: pass
    def __init__(self):
        self.logger = logging.getLogger(f"certus.crawler.{self.department_code}")
    @abstractmethod
    def verify_connection(self) -> bool: pass
    @abstractmethod
    def download_register_page(self, output_dir: Path | str) -> Path: pass