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


def test_segment_acts_trois_blocs(tmp_path, monkeypatch):
    """Vérifie que 3 blocs sombres séparés par de larges bandes blanches sont bien découpés en 3 segments ordonnés."""
    from PIL import Image, ImageDraw

    img_path = tmp_path / "scans" / "trois_actes.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)

    # 3 blocs sombres séparés par 2 bandes blanches de 40px
    img = Image.new("RGB", (100, 300), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 100, 60], fill=(20, 20, 20))       # Bloc 1 (60px)
    # Bande blanche 60..100 (40px)
    draw.rectangle([0, 100, 100, 160], fill=(20, 20, 20))   # Bloc 2 (60px)
    # Bande blanche 160..200 (40px)
    draw.rectangle([0, 200, 100, 300], fill=(20, 20, 20))   # Bloc 3 (100px)
    img.save(img_path)

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    engine = FlorenceOCREngine()
    segments = engine.segment_acts(img_path)

    assert len(segments) == 3
    assert segments[0].name.endswith("_acte01.jpg")
    assert segments[1].name.endswith("_acte02.jpg")
    assert segments[2].name.endswith("_acte03.jpg")


def test_segment_acts_un_seul_bloc(tmp_path, monkeypatch):
    """Vérifie qu'une image d'un seul bloc retourne 1 chemin, sans exception."""
    from PIL import Image

    img_path = tmp_path / "scans" / "un_acte.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 200), (30, 30, 30)).save(img_path)

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    engine = FlorenceOCREngine()
    segments = engine.segment_acts(img_path)

    assert len(segments) == 1
    assert segments[0].exists()


def test_segment_acts_fichiers_dans_cache(tmp_path, monkeypatch):
    """Vérifie que les fichiers produits sont écrits dans le répertoire de cache et JAMAIS à côté du scan source."""
    from PIL import Image, ImageDraw

    scan_dir = tmp_path / "scans"
    scan_dir.mkdir(parents=True, exist_ok=True)
    img_path = scan_dir / "registre.jpg"

    img = Image.new("RGB", (100, 300), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 100, 60], fill=(20, 20, 20))
    draw.rectangle([0, 100, 100, 160], fill=(20, 20, 20))
    draw.rectangle([0, 200, 100, 300], fill=(20, 20, 20))
    img.save(img_path)

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    engine = FlorenceOCREngine()
    segments = engine.segment_acts(img_path)

    assert len(segments) == 3
    for seg in segments:
        assert seg.parent == output_dir
        assert seg.parent != scan_dir
    # Vérifie qu'aucun fichier supplémentaire n'a été créé dans scan_dir
    assert list(scan_dir.glob("*")) == [img_path]


def test_segment_acts_image_illisible(tmp_path, monkeypatch):
    """Vérifie qu'une image illisible/corrompue ne fait pas planter segment_acts."""
    corrupt_path = tmp_path / "scans" / "corrupt.jpg"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"CONTENU CORROMPU PAS UNE IMAGE")

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    engine = FlorenceOCREngine()
    segments = engine.segment_acts(corrupt_path)

    assert len(segments) == 1


@pytest.mark.slow
def test_segment_acts_scan_reel(tmp_path, monkeypatch):
    """Exécute segment_acts sur un vrai scan du dépôt et exige au moins 2 segments."""
    from pathlib import Path

    scan_path = Path("2014-12-14 12.03.15.jpg")
    if not scan_path.exists():
        pytest.skip("Fichier 2014-12-14 12.03.15.jpg absent du dépôt local.")

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))

    engine = FlorenceOCREngine()
    segments = engine.segment_acts(scan_path)

    assert len(segments) >= 2


def test_segment_acts_bande_courte_warning(tmp_path, monkeypatch, caplog):
    """Vérifie qu'une bande plus courte que min_height produit un WARNING et est rattachée sans être perdue."""
    import logging
    from PIL import Image, ImageDraw

    img_path = tmp_path / "scans" / "bande_courte.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)

    # Créer 1 bloc normal (60px), 1 bande blanche (30px), et 1 bloc très court de 20px (< min_height=50)
    img = Image.new("RGB", (100, 180), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 100, 60], fill=(20, 20, 20))      # Bloc 1 (60px)
    # Bande blanche 60..90 (30px)
    draw.rectangle([0, 90, 100, 110], fill=(20, 20, 20))    # Bloc 2 très court (20px < min_height=50)
    # Bande blanche 110..140 (30px)
    draw.rectangle([0, 140, 100, 180], fill=(20, 20, 20))   # Bloc 3 (40px)
    img.save(img_path)

    output_dir = tmp_path / "cache_ocr"
    monkeypatch.setenv("CERTUS_OCR_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("CERTUS_SEGMENT_MIN_HEIGHT", "60")

    engine = FlorenceOCREngine()
    with caplog.at_level(logging.WARNING, logger="certus.ocr"):
        segments = engine.segment_acts(img_path)

    # La bande courte doit émettre un WARNING explicite
    assert any("hauteur minimale" in record.message for record in caplog.records)
    # Les segments ne doivent pas être perdus silencieusement (rattachés au segment adjacent)
    assert len(segments) >= 1


