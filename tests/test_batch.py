"""Tests pour le pipeline de transcription par lot scripts/batch_transcribe.py."""

import json
import pytest
from pathlib import Path
from PIL import Image, ImageDraw

import src.ocr.backends  # noqa: F401
from src.database.engine import DatabaseManager
from src.database.repository import ActRepository
from scripts.batch_transcribe import process_batch, load_ledger, get_ledger_path


@pytest.fixture(autouse=True)
def setup_batch_env(monkeypatch, allow_simulation):
    monkeypatch.setenv("CERTUS_ALLOW_SIMULATED", "1")
    monkeypatch.setenv("CERTUS_HTR_BACKENDS", "simulated")


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "test_batch.db"
    db = DatabaseManager(f"sqlite:///{db_file}")
    db.init_db()
    return db


@pytest.fixture
def synthetic_images(tmp_path):
    images_dir = tmp_path / "scans"
    images_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, 4):
        p = images_dir / f"scan_synth_{i:02d}.jpg"
        img = Image.new("RGB", (100, 200), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 60], fill=(20, 20, 20))
        draw.rectangle([0, 100, 100, 160], fill=(20, 20, 20))
        img.save(p)
        paths.append(p)
    return images_dir, paths


def test_batch_trois_images_synthetiques(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Le lot traite 3 images et persiste les actes en base."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    exit_code = process_batch(source_dir=images_dir, db_manager=db_manager)

    assert exit_code == 0
    session = db_manager.get_session()
    try:
        repo = ActRepository(session)
        assert repo.count_acts() > 0
    finally:
        session.close()

    ledger = load_ledger(ledger_file)
    assert len(ledger) == 3
    for p in paths:
        assert str(p.resolve()) in ledger
        assert ledger[str(p.resolve())]["status"] == "OK"


def test_batch_idempotence(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Relance immédiate : 0 image retraitée, 0 acte créé en plus."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        initial_acts_count = ActRepository(session).count_acts()
    finally:
        session.close()

    # Relance immédiate
    exit_code = process_batch(source_dir=images_dir, db_manager=db_manager)
    assert exit_code == 0

    session = db_manager.get_session()
    try:
        final_acts_count = ActRepository(session).count_acts()
    finally:
        session.close()

    assert final_acts_count == initial_acts_count


def test_batch_force(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Avec --force : les images sont retraitées et de nouveaux actes sont créés."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        initial_count = ActRepository(session).count_acts()
    finally:
        session.close()

    # Retraitement avec force=True
    exit_code = process_batch(source_dir=images_dir, force=True, db_manager=db_manager)
    assert exit_code == 0

    session = db_manager.get_session()
    try:
        final_count = ActRepository(session).count_acts()
    finally:
        session.close()

    assert final_count > initial_count


def test_batch_dry_run(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """--dry-run : rien n'est écrit en base et le registre n'est pas modifié."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    exit_code = process_batch(source_dir=images_dir, dry_run=True, db_manager=db_manager)
    assert exit_code == 0

    session = db_manager.get_session()
    try:
        assert ActRepository(session).count_acts() == 0
    finally:
        session.close()

    assert not ledger_file.exists()


def test_batch_limit(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """--limit 1 : une seule image traitée sur les 3."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    exit_code = process_batch(source_dir=images_dir, limit=1, db_manager=db_manager)
    assert exit_code == 0

    ledger = load_ledger(ledger_file)
    assert len(ledger) == 1


def test_batch_image_corrompue(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Une image corrompue : le lot continue, l'échec est au registre, aucun acte créé pour l'image corrompue, code de sortie non nul."""
    images_dir, paths = synthetic_images
    corrupt_file = images_dir / "z_corrupt.jpg"
    corrupt_file.write_bytes(b"CONTENU CORROMPU PAS UNE IMAGE")

    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    exit_code = process_batch(source_dir=images_dir, db_manager=db_manager)
    assert exit_code == 1

    ledger = load_ledger(ledger_file)
    corrupt_key = str(corrupt_file.resolve())
    assert corrupt_key in ledger
    assert ledger[corrupt_key]["status"] == "FAILED"
    assert ledger[corrupt_key]["num_acts_created"] == 0
    assert ledger[corrupt_key]["error_message"] is not None


def test_batch_actes_simules(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Les actes créés en mode simulé portent is_simulated=True, source_type préfixé SIMULATED_, et scores à 0.0."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)

    session = db_manager.get_session()
    try:
        acts = ActRepository(session).get_all_acts()
        assert len(acts) > 0
        for act in acts:
            assert act.is_simulated is True
            assert act.source_type.startswith("SIMULATED_")
            assert act.confidence_score == 0.0
            assert act.reliability_score == 0.0
            assert act.url_source is None
    finally:
        session.close()
