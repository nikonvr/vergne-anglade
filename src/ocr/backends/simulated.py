"""Moteur de transcription simulé, réservé aux tests et aux démonstrations.

Il n'est utilisable que si CERTUS_ALLOW_SIMULATED=1, et tout ce qu'il produit porte
is_simulated=True. C'est le seul moteur autorisé à retourner du texte sans lire réellement
l'image ; il existe précisément pour que les autres n'aient jamais à le faire.
"""

from __future__ import annotations

from pathlib import Path

from src.core.simulation import require_simulation, simulation_allowed
from src.ocr.htr import HTRBackend, HTRError, HTRRegistry, HTRResult

SIMULATED_MARKER = "[TRANSCRIPTION SIMULÉE - AUCUNE LECTURE RÉELLE]"


@HTRRegistry.register
class SimulatedBackend(HTRBackend):
    name = "simulated"
    description = "Transcription factice explicitement marquée, pour tests uniquement."
    COMPONENT = "moteur HTR simulé"

    def available(self) -> tuple[bool, str]:
        if not simulation_allowed():
            return False, (
                "la simulation est désactivée. Définissez CERTUS_ALLOW_SIMULATED=1 pour "
                "l'autoriser — à n'utiliser qu'en test."
            )
        return True, "actif : les transcriptions produites sont marquées comme simulées."

    def transcribe(self, image_path: Path) -> HTRResult:
        require_simulation(self.COMPONENT)
        path = Path(image_path)
        if not path.is_file():
            raise HTRError(f"Image introuvable : {path.name}")
        try:
            from PIL import Image

            with Image.open(path) as img:
                img.verify()
        except Exception as exc:
            raise HTRError(f"Image corrompue ou illisible : {path.name} ({exc})")

        return HTRResult(
            text=f"{SIMULATED_MARKER} Image : {path.name}.",
            backend=self.name,
            confidence=0.0,
            is_simulated=True,
            warnings=["transcription simulée, sans valeur probante"],
        )
