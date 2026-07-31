"""Politique anti-fabrication côté OCR (constat M3).

extract_text renvoyait une phrase constante mentionnant un patronyme de la branche, et
l'ancien test verrouillait ce comportement en vérifiant la présence de ce patronyme.
"""

import pytest

from src.ocr.florence import FlorenceOCREngine, OCRBackendUnavailableError


@pytest.fixture
def image(tmp_path):
    """Vraie image lisible : sur un fichier illisible le prétraitement retourne la source."""
    from PIL import Image

    img_path = tmp_path / "scans" / "archive_test.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (200, 200, 200)).save(img_path)
    return img_path


def test_preprocess_ecrit_hors_du_repertoire_source(image, tmp_path, monkeypatch):
    """Mod11 : le prétraitement ne pollue plus le répertoire des scans d'origine."""
    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    result = FlorenceOCREngine().preprocess_image(image)

    assert result.exists()
    assert result.parent != image.parent
    assert result.parent == output_dir


def test_extract_text_refuse_de_fabriquer_sans_moteur(image):
    """M3 : sans moteur réel ni autorisation explicite, l'OCR échoue au lieu d'inventer."""
    engine = FlorenceOCREngine()
    with pytest.raises(OCRBackendUnavailableError):
        engine.extract_text(image)
    assert engine.last_result_simulated is False


def test_extract_text_simule_est_marque(image, allow_simulation):
    """M3 : une transcription simulée est identifiable par l'appelant."""
    engine = FlorenceOCREngine()
    text = engine.extract_text(image)

    assert engine.last_result_simulated is True
    assert "SIMUL" in text.upper()
