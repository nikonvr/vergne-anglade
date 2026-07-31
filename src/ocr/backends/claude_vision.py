"""Moteur HTR fondé sur un modèle de vision Claude.

C'est le moteur le plus immédiatement opérationnel sur les registres BMS : il lit la main
ancienne et applique le contexte paléographique du prompt (formules, abréviations,
calendrier républicain) dans la même passe.

LIMITE À CONNAÎTRE
Le service redimensionne les images au-delà d'environ 1568 pixels sur le grand côté. Sur une
page de registre entière, le détail des jambages peut s'en trouver dégradé. Pour les pages
denses, transcrire ACTE PAR ACTE en découpant l'image donne de bien meilleurs résultats
qu'une page complète : voir CERTUS_HTR_MAX_EDGE et la piste de découpage en bandes
documentée dans AGENTS.md.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from src.ocr.bms import build_transcription_prompt
from src.ocr.htr import HTRBackend, HTRError, HTRRegistry, HTRResult

logger = logging.getLogger("certus.ocr.claude")

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

ENV_API_KEY = "ANTHROPIC_API_KEY"
ENV_MODEL = "CERTUS_HTR_CLAUDE_MODEL"
ENV_MAX_EDGE = "CERTUS_HTR_MAX_EDGE"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_EDGE = 1568
MAX_PAYLOAD_BYTES = 4_500_000  # marge sous la limite de charge utile du service


@HTRRegistry.register
class ClaudeVisionBackend(HTRBackend):
    name = "claude_vision"
    description = "Modèle de vision Claude, guidé par le contexte paléographique BMS."

    def available(self) -> tuple[bool, str]:
        if not os.environ.get(ENV_API_KEY):
            return False, f"définissez {ENV_API_KEY} avec votre clé d'API Anthropic."
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "paquet « anthropic » absent : installez l'extra llm du projet."
        return True, f"prêt (modèle {os.environ.get(ENV_MODEL) or DEFAULT_MODEL})."

    # ------------------------------------------------------------------ préparation image
    def _encode(self, image_path: Path) -> tuple[str, str]:
        """Encode l'image en base64, en la réduisant si elle dépasse les limites."""
        suffix = image_path.suffix.lower()
        media_type = MEDIA_TYPES.get(suffix)
        if media_type is None:
            raise HTRError(
                f"Format d'image non pris en charge : {suffix}. "
                f"Formats acceptés : {', '.join(sorted(MEDIA_TYPES))}."
            )

        raw = image_path.read_bytes()
        max_edge = int(os.environ.get(ENV_MAX_EDGE) or DEFAULT_MAX_EDGE)

        try:
            from PIL import Image

            with Image.open(image_path) as img:
                if max(img.size) > max_edge or len(raw) > MAX_PAYLOAD_BYTES:
                    ratio = max_edge / max(img.size)
                    new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                    logger.info(
                        "Image réduite de %s à %s avant transcription : le détail des "
                        "jambages peut en souffrir, préférez un découpage acte par acte.",
                        img.size,
                        new_size,
                    )
                    import io

                    buffer = io.BytesIO()
                    img.convert("RGB").resize(new_size, Image.LANCZOS).save(
                        buffer, format="JPEG", quality=92
                    )
                    raw = buffer.getvalue()
                    media_type = "image/jpeg"
        except ImportError:
            logger.warning("Pillow absent : image envoyée sans redimensionnement.")

        if len(raw) > MAX_PAYLOAD_BYTES:
            raise HTRError(
                "Image trop volumineuse même après réduction. Découpez la page en actes "
                f"individuels ou abaissez {ENV_MAX_EDGE}."
            )
        return base64.standard_b64encode(raw).decode("ascii"), media_type

    # ------------------------------------------------------------------ transcription
    def transcribe(self, image_path: Path) -> HTRResult:
        self.ensure_available()
        path = Path(image_path)
        if not path.is_file():
            raise HTRError(f"Image introuvable : {path.name}")

        encoded, media_type = self._encode(path)
        model = os.environ.get(ENV_MODEL) or DEFAULT_MODEL

        try:
            import anthropic

            client = anthropic.Anthropic()
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=0,  # transcription : aucune créativité souhaitée
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": encoded,
                                },
                            },
                            {"type": "text", "text": build_transcription_prompt()},
                        ],
                    }
                ],
            )
        except Exception as exc:
            # Aucune transcription de repli : mieux vaut une erreur qu'un texte inventé.
            raise HTRError(f"Appel au modèle de vision en échec : {exc}") from exc

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            raise HTRError("Le modèle n'a retourné aucune transcription.")

        warnings = []
        if "[illisible]" in text:
            warnings.append("le moteur a signalé des passages illisibles")
        if "(?)" in text:
            warnings.append("le moteur a signalé des lectures incertaines")

        return HTRResult(
            text=text,
            backend=self.name,
            # Le modèle n'expose pas de probabilité exploitable : on ne fabrique pas de
            # score. La confiance vient de l'accord entre moteurs (voir htr.py).
            confidence=None,
            warnings=warnings,
            raw={"model": model, "stop_reason": getattr(response, "stop_reason", None)},
        )
