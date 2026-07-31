from typing import Callable, Dict, Type
from .base import BaseArchiveCrawler

class ArchiveCrawlerFactory:
    """Factory for registering and retrieving archive crawlers by department code."""
    _registry: Dict[str, Type[BaseArchiveCrawler]] = {}

    @classmethod
    def register(cls, department_code: str) -> Callable[[Type[BaseArchiveCrawler]], Type[BaseArchiveCrawler]]:
        """Decorator to register a crawler class for a specific department code."""
        def inner_wrapper(wrapped_class: Type[BaseArchiveCrawler]) -> Type[BaseArchiveCrawler]:
            cls._registry[department_code] = wrapped_class
            return wrapped_class
        return inner_wrapper

    @classmethod
    def get_crawler(cls, department_code: str) -> BaseArchiveCrawler:
        """Instantiates and returns the crawler for the given department code."""
        if department_code not in cls._registry:
            raise ValueError(f"No crawler registered for department code: {department_code}")
        return cls._registry[department_code]()