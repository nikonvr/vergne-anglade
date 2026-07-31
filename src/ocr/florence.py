import logging
import os
from pathlib import Path

from src.core.simulation import simulation_allowed

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

logger = logging.getLogger("certus.ocr")

# Répertoire de sortie du prétraitement : jamais à côté des scans sources (cf. Mod11).
DEFAULT_OCR_OUTPUT_DIR = ".certus_cache/preprocessed"

# Marqueur obligatoire en tête de tout texte non issu d'un OCR réel.
SIMULATED_TEXT_MARKER = "[TEXTE SIMULÉ - AUCUN OCR RÉEL]"


class OCRBackendUnavailableError(RuntimeError):
    """Levée lorsqu'aucun moteur OCR réel n'est configuré et que la simulation est interdite."""


class FlorenceOCREngine:
    """
    Moteur OCR (Florence-2 / HTR) avec pipeline de prétraitement visuel.

    Le prétraitement d'image est réel (OpenCV ou PIL). En revanche AUCUN moteur
    de reconnaissance n'est actuellement branché : extract_text() lève une
    exception explicite plutôt que de retourner une transcription inventée.
    Si CERTUS_ALLOW_SIMULATED=1, un texte explicitement marqué comme simulé est
    retourné et l'appelant peut le détecter via last_result_simulated /
    is_simulated().
    """

    def __init__(self, output_dir: Path | str | None = None):
        self.logger = logger
        self._output_dir = Path(output_dir) if output_dir else None
        self._last_result_simulated = False

    @property
    def output_dir(self) -> Path:
        """Répertoire des images prétraitées (CERTUS_OCR_OUTPUT_DIR, sinon .certus_cache/preprocessed)."""
        if self._output_dir is not None:
            return self._output_dir
        return Path(os.environ.get("CERTUS_OCR_OUTPUT_DIR") or DEFAULT_OCR_OUTPUT_DIR)

    @property
    def last_result_simulated(self) -> bool:
        """True si le dernier texte retourné par extract_text() est une simulation."""
        return self._last_result_simulated

    def is_simulated(self) -> bool:
        """Alias explicite de last_result_simulated, pour les appelants procéduraux."""
        return self._last_result_simulated

    def preprocess_image(self, image_path: Path | str, output_path: Path | str | None = None) -> Path:
        """
        Applique un prétraitement adaptatif (niveaux de gris, amélioration du contraste)
        pour nettoyer les taches et l'encre qui transperce sur les registres anciens.

        La sortie est écrite dans le répertoire de cache (jamais à côté du scan source),
        sauf si output_path est fourni explicitement.
        """
        input_p = Path(image_path)
        if not input_p.exists():
            raise FileNotFoundError(f"Image introuvable : {input_p}")

        if output_path is None:
            out_dir = self.output_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            out_p = out_dir / f"preprocessed_{input_p.name}"
        else:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)

        # 1. Traitement renforcé avec OpenCV (CLAHE + Denoise) si disponible
        if HAS_OPENCV:
            try:
                img_cv = cv2.imread(str(input_p), cv2.IMREAD_GRAYSCALE)
                if img_cv is not None:
                    # Rehaussement de contraste localisé (CLAHE)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    enhanced = clahe.apply(img_cv)
                    # Filtrage médian pour éliminer les piqûres et l'encre traversante
                    denoised = cv2.medianBlur(enhanced, 3)
                    cv2.imwrite(str(out_p), denoised)
                    self.logger.info(f"Image prétraitée via OpenCV (CLAHE+MedianBlur) : {out_p}")
                    return out_p
            except Exception as cv_err:
                self.logger.debug(f"Erreur OpenCV, passage au fallback PIL : {cv_err}")

        # 2. Fallback PIL si OpenCV n'est pas utilisé
        try:
            from PIL import Image, ImageEnhance, ImageFilter
            with Image.open(input_p) as img:
                gray = img.convert("L")
                sharp = gray.filter(ImageFilter.SHARPEN)
                contrast_enhancer = ImageEnhance.Contrast(sharp)
                enhanced = contrast_enhancer.enhance(2.0)
                bright_enhancer = ImageEnhance.Brightness(enhanced)
                final_img = bright_enhancer.enhance(1.1)
                final_img.save(out_p)
                self.logger.info(f"Image prétraitée via PIL : {out_p}")
                return out_p
        except Exception as e:
            self.logger.warning(
                f"Aucun prétraitement appliqué à {input_p.name} ({e}) : "
                "l'image source est transmise telle quelle à l'OCR."
            )
            return input_p

    def extract_text(self, image_path: Path | str) -> str:
        """
        Transcrit l'image d'archive, après prétraitement, via les moteurs HTR configurés.

        La transcription est confiée au registre de src/ocr/htr.py : plusieurs moteurs sont
        exécutés et leur accord fournit le score de confiance (voir last_consensus).
        Si aucun moteur n'est utilisable, la méthode lève OCRBackendUnavailableError plutôt
        que de retourner une transcription inventée. Lancez « python -m src.ocr.htr » pour
        savoir quel moteur manque et pourquoi.
        """
        self._last_result_simulated = False
        self._last_consensus = None
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image introuvable : {path}")

        preprocessed = self.preprocess_image(path)

        # Import tardif : enregistre les moteurs et évite un cycle avec le socle HTR.
        import src.ocr.backends  # noqa: F401
        from src.ocr.htr import HTRError, transcribe_with_consensus

        try:
            consensus = transcribe_with_consensus(preprocessed)
        except HTRError as exc:
            raise OCRBackendUnavailableError(
                f"Impossible de transcrire {path.name} : {exc}"
            ) from exc

        self._last_consensus = consensus
        self._last_result_simulated = consensus.is_simulated
        if consensus.is_simulated:
            self.logger.warning(
                "Transcription SIMULÉE pour %s : aucune lecture réelle n'a eu lieu.",
                preprocessed.name,
            )
        elif consensus.needs_human_review:
            self.logger.warning(
                "Transcription de %s à faire relire : accord entre moteurs %.2f (%s).",
                preprocessed.name,
                consensus.agreement,
                ", ".join(consensus.backends_used),
            )
        return consensus.text

    @property
    def last_consensus(self):
        """Détail du dernier consensus HTR (accord, moteurs, variantes), ou None."""
        return getattr(self, "_last_consensus", None)


# Le nom « Florence » était trompeur : aucun modèle Florence-2 n'a jamais été branché.
# HTREngine est le nom canonique ; l'alias est conservé pour les appelants existants.
HTREngine = FlorenceOCREngine
