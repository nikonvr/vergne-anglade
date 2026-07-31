from typing import Callable, Dict, Type
from .base import BaseArchiveCrawler

class ArchiveCrawlerFactory:
    """Fabrique d'enregistrement et de récupération des robots d'archives par code département."""
    _registry: Dict[str, Type[BaseArchiveCrawler]] = {}

    @classmethod
    def register(cls, department_code: str) -> Callable[[Type[BaseArchiveCrawler]], Type[BaseArchiveCrawler]]:
        """Décorateur d'enregistrement d'une classe de robot pour un code département donné."""
        def inner_wrapper(wrapped_class: Type[BaseArchiveCrawler]) -> Type[BaseArchiveCrawler]:
            cls._registry[department_code] = wrapped_class
            return wrapped_class
        return inner_wrapper

    @classmethod
    def get_crawler(cls, department_code: str) -> BaseArchiveCrawler:
        """Instancie et retourne le robot correspondant au code département fourni."""
        if department_code not in cls._registry:
            raise ValueError(f"Aucun robot d'archives enregistré pour le code département : {department_code}")
        return cls._registry[department_code]()
