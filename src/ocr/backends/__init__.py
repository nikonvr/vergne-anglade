"""Moteurs HTR disponibles.

Tout moteur doit être importé ICI pour que le décorateur @HTRRegistry.register s'exécute et
le rende visible du registre. Un moteur non importé est invisible, sans message d'erreur.
"""

from src.ocr.backends.claude_vision import ClaudeVisionBackend
from src.ocr.backends.reference_engines import (
    KrakenBackend,
    TesseractBackend,
    TranskribusBackend,
)
from src.ocr.backends.simulated import SimulatedBackend

__all__ = [
    "ClaudeVisionBackend",
    "KrakenBackend",
    "SimulatedBackend",
    "TesseractBackend",
    "TranskribusBackend",
]
