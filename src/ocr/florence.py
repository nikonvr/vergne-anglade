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

    def segment_acts(self, image_path: Path | str) -> list[Path]:
        """
        Découpe une image de registre d'archives en actes individuels empilés verticalement.

        Le profil de projection horizontale est calculé sur la zone de texte centrale binarisée (Otsu)
        en ignorant les marges latérales (CERTUS_SEGMENT_MARGIN_RATIO, défaut 0.15 de chaque côté).
        Les images d'actes découpées sont générées sur la LARGEUR COMPLÈTE de la page et enregistrées
        dans le répertoire de cache (self.output_dir) sous le nom : <nom>_acte01.jpg, <nom>_acte02.jpg...

        Toute bande sous CERTUS_SEGMENT_MIN_HEIGHT est rattachée au segment adjacent et fait l'objet d'un
        log en WARNING décrivant ses coordonnées et sa hauteur (règle R5 anti-perte).

        Si aucune séparation crédible n'est trouvée, retourne [image_prétraitée] et logue un WARNING.
        """
        input_p = Path(image_path)
        preprocessed = self.preprocess_image(input_p)

        min_gap = int(os.environ.get("CERTUS_SEGMENT_MIN_GAP") or 20)
        min_height = int(os.environ.get("CERTUS_SEGMENT_MIN_HEIGHT") or 50)
        margin_ratio = float(os.environ.get("CERTUS_SEGMENT_MARGIN_RATIO") or 0.15)

        if not HAS_OPENCV:
            self.logger.warning(
                "OpenCV non disponible : segmentation d'actes ignorée pour %s (page conservée en un seul bloc).",
                input_p.name,
            )
            return [preprocessed]

        try:
            img_cv = cv2.imread(str(preprocessed), cv2.IMREAD_GRAYSCALE)
            if img_cv is None:
                self.logger.warning(
                    "Image illisible par OpenCV pour la segmentation : %s (page conservée en un seul bloc).",
                    preprocessed.name,
                )
                return [preprocessed]

            height, width = img_cv.shape
            if height == 0 or width == 0:
                self.logger.warning(
                    "Image de dimensions nulles : %s (page conservée en un seul bloc).",
                    preprocessed.name,
                )
                return [preprocessed]

            # Binarisation avec Otsu inverse pour s'adapter à la luminosité/contraste du registre
            otsu_thresh, _ = cv2.threshold(img_cv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, binary_ink = cv2.threshold(img_cv, otsu_thresh, 1, cv2.THRESH_BINARY_INV)

            # Restreindre l'analyse du profil à la zone de texte centrale (exclut reliures et bordures sombres)
            margin_x = int(width * margin_ratio)
            if margin_x > 0 and (2 * margin_x) < width:
                analysis_zone = binary_ink[:, margin_x : width - margin_x]
                effective_w = width - 2 * margin_x
            else:
                analysis_zone = binary_ink
                effective_w = width

            ink_per_row = np.sum(analysis_zone, axis=1)

            # Une ligne est considérée comme séparatrice (blanche) si elle contient très peu d'encre (< 5% de la zone utile)
            white_threshold = max(5, int(effective_w * 0.05))
            is_white_row = ink_per_row <= white_threshold

            # Si l'image est quasiment dépourvue d'encre ou entièrement blanche (aucun contraste encre/fond)
            if np.mean(is_white_row) > 0.95 or np.sum(binary_ink) < 10:
                self.logger.warning(
                    "Aucune séparation d'actes crédible trouvée dans %s (page conservée en un seul bloc).",
                    input_p.name,
                )
                return [preprocessed]

            # Détecter les plages contiguës de lignes blanches
            white_gaps = []
            gap_start = None
            for y, white in enumerate(is_white_row):
                if white:
                    if gap_start is None:
                        gap_start = y
                else:
                    if gap_start is not None:
                        if (y - gap_start) >= min_gap:
                            white_gaps.append((gap_start, y))
                        gap_start = None
            if gap_start is not None and (height - gap_start) >= min_gap:
                white_gaps.append((gap_start, height))

            # Points de coupe au milieu des bandes blanches
            cut_points = []
            for g_start, g_end in white_gaps:
                mid = (g_start + g_end) // 2
                if 0 < mid < height:
                    cut_points.append(mid)

            raw_boundaries = [0] + cut_points + [height]
            raw_segments = []
            for i in range(len(raw_boundaries) - 1):
                raw_segments.append((raw_boundaries[i], raw_boundaries[i + 1]))

            if not raw_segments:
                return [preprocessed]

            # Traitement des bandes plus courtes que min_height : rattachées au voisin et journalisées en WARNING (R5)
            segments_coords = []
            for y_top, y_bottom in raw_segments:
                h = y_bottom - y_top
                if h < min_height:
                    if segments_coords:
                        prev_top, _ = segments_coords.pop()
                        segments_coords.append((prev_top, y_bottom))
                        self.logger.warning(
                            "Bande d'acte sous la hauteur minimale (y=%d à %d, h=%d < min_height=%d) : "
                            "rattachée au segment précédent (nouveau segment y=%d à %d).",
                            y_top,
                            y_bottom,
                            h,
                            min_height,
                            prev_top,
                            y_bottom,
                        )
                    else:
                        segments_coords.append((y_top, y_bottom))
                        self.logger.warning(
                            "Bande d'acte sous la hauteur minimale (y=%d à %d, h=%d < min_height=%d) : "
                            "conservée faute de segment précédent.",
                            y_top,
                            y_bottom,
                            h,
                            min_height,
                        )
                else:
                    segments_coords.append((y_top, y_bottom))

            if len(segments_coords) < 2:
                self.logger.warning(
                    "Aucune séparation d'actes crédible trouvée dans %s (page conservée en un seul bloc).",
                    input_p.name,
                )
                return [preprocessed]

            out_dir = self.output_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = input_p.stem
            segment_paths = []

            # DÉCOUPAGE SUR LA LARGEUR COMPLÈTE DE L'IMAGE (0 à width)
            for idx, (y_top, y_bottom) in enumerate(segments_coords, start=1):
                sub_img = img_cv[y_top:y_bottom, :]
                seg_path = out_dir / f"{stem}_acte{idx:02d}.jpg"
                cv2.imwrite(str(seg_path), sub_img)
                segment_paths.append(seg_path)

            self.logger.info(
                "Image %s découpée en %d actes.", input_p.name, len(segment_paths)
            )
            return segment_paths

        except Exception as err:
            self.logger.warning(
                "Échec de la segmentation d'actes sur %s (%s) : page conservée en un seul bloc.",
                input_p.name,
                err,
            )
            return [preprocessed]

    def extract_text(self, image_path: Path | str) -> str:
        """
        Transcrit l'image d'archive, après prétraitement et segmentation par acte.

        Chaque segment d'acte est transcrit avec le consensus de src/ocr/htr.py.
        Les transcriptions sont concaténées avec l'en-tête « --- ACTE {n} --- ».
        La confiance retenue pour la page est la MOYENNE des accords des segments.
        Si aucun moteur n'est utilisable, la méthode lève OCRBackendUnavailableError.
        """
        self._last_result_simulated = False
        self._last_consensus = None
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image introuvable : {path}")

        segments = self.segment_acts(path)

        # Import tardif : enregistre les moteurs et évite un cycle avec le socle HTR.
        import src.ocr.backends  # noqa: F401
        from src.ocr.htr import HTRError, ConsensusResult, transcribe_with_consensus

        segment_results: list[tuple[int, ConsensusResult]] = []
        failures: list[str] = []

        for idx, seg_path in enumerate(segments, start=1):
            try:
                consensus = transcribe_with_consensus(seg_path)
                segment_results.append((idx, consensus))
            except HTRError as exc:
                failures.append(f"Segment {idx} ({seg_path.name}) : {exc}")
                self.logger.warning(
                    "Échec de la transcription du segment %d de %s : %s",
                    idx,
                    path.name,
                    exc,
                )

        if not segment_results:
            raise OCRBackendUnavailableError(
                f"Impossible de transcrire {path.name} (tous les segments ont échoué) : "
                + " | ".join(failures)
            )

        text_parts = []
        all_htr_results = []
        agreements = []
        is_simulated = False

        for idx, consensus in segment_results:
            text_parts.append(f"--- ACTE {idx} ---\n{consensus.text}")
            agreements.append(consensus.agreement)
            all_htr_results.extend(consensus.results)
            if consensus.is_simulated:
                is_simulated = True

        full_text = "\n\n".join(text_parts)
        avg_agreement = sum(agreements) / len(agreements)
        primary_backend = segment_results[0][1].primary_backend

        page_consensus = ConsensusResult(
            text=full_text,
            primary_backend=primary_backend,
            agreement=avg_agreement,
            results=all_htr_results,
            is_simulated=is_simulated,
        )

        self._last_consensus = page_consensus
        self._last_result_simulated = is_simulated

        if is_simulated:
            self.logger.warning(
                "Transcription SIMULÉE pour %s : aucune lecture réelle n'a eu lieu.",
                path.name,
            )
        elif page_consensus.needs_human_review:
            self.logger.warning(
                "Transcription de %s à faire relire : accord moyen entre moteurs %.2f (%s).",
                path.name,
                avg_agreement,
                ", ".join(page_consensus.backends_used),
            )
        return full_text

    @property
    def last_consensus(self):
        """Détail du dernier consensus HTR (accord, moteurs, variantes), ou None."""
        return getattr(self, "_last_consensus", None)


# Le nom « Florence » était trompeur : aucun modèle Florence-2 n'a jamais été branché.
# HTREngine est le nom canonique ; l'alias est conservé pour les appelants existants.
HTREngine = FlorenceOCREngine
