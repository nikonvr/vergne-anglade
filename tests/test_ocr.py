import pytest
from pathlib import Path
from src.ocr.florence import FlorenceOCREngine

def test_florence_ocr_preprocess(tmp_path):
    img_file = tmp_path / "archive_test.jpg"
    img_file.write_bytes(b"dummy image data")

    ocr = FlorenceOCREngine()
    result_path = ocr.preprocess_image(img_file)
    assert result_path.exists()

def test_florence_ocr_extract_text(tmp_path):
    img_file = tmp_path / "archive_test.jpg"
    img_file.write_bytes(b"dummy image data")

    ocr = FlorenceOCREngine()
    text = ocr.extract_text(img_file)
    assert isinstance(text, str)
    assert "VERGNE" in text
