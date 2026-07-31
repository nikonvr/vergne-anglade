"""Tests pour le pipeline de transcription par lot scripts/batch_transcribe.py."""

import json
import pytest
from pathlib import Path
from PIL import Image, ImageDraw

import src.ocr.backends  # noqa: F401
from src.core.models import Act, Person
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
    """Avec --force : les images sont retraitées et remplacent les actes précédents sans accumulation."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        initial_count = ActRepository(session).count_acts()
        initial_ids = [act.id for act in ActRepository(session).get_all_acts()]
    finally:
        session.close()

    # Retraitement avec force=True
    exit_code = process_batch(source_dir=images_dir, force=True, db_manager=db_manager)
    assert exit_code == 0

    session = db_manager.get_session()
    try:
        final_count = ActRepository(session).count_acts()
        final_ids = [act.id for act in ActRepository(session).get_all_acts()]
    finally:
        session.close()

    # Remplacement : le total reste identique, mais les clés primaires ont changé
    assert final_count == initial_count
    assert set(initial_ids).isdisjoint(set(final_ids))


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


# ------------------------------------------------------------------ Nouveaux tests de remplacement et d'isolation


def test_batch_replacement_remplace_et_n_accumule_pas(
    tmp_path, monkeypatch, allow_simulation, db_manager
):
    """Répertoire de 2 images : traiter, compter les actes, puis retraiter avec --force et vérifier que le total d'actes est IDENTIQUE."""
    scans_dir = tmp_path / "scans_replace"
    scans_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 3):
        p = scans_dir / f"scan_{i:02d}.jpg"
        img = Image.new("RGB", (100, 200), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 60], fill=(0, 0, 0))
        img.save(p)

    ledger_file = tmp_path / "ledger_replace.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    # Premier passage
    assert process_batch(source_dir=scans_dir, db_manager=db_manager) == 0
    session = db_manager.get_session()
    try:
        count_pass1 = ActRepository(session).count_acts()
    finally:
        session.close()

    # Second passage avec --force
    assert process_batch(source_dir=scans_dir, force=True, db_manager=db_manager) == 0
    session = db_manager.get_session()
    try:
        count_pass2 = ActRepository(session).count_acts()
    finally:
        session.close()

    # Remplacement strict : pas d'accumulation d'actes
    assert count_pass1 > 0
    assert count_pass2 == count_pass1


def test_batch_aucun_acte_orphelin(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Tout acte HTR/SIMULATED en base doit être référencé par les act_ids d'une entrée du registre."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger_orphelin.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)
    # Retraitement avec force pour forcer le remplacement
    process_batch(source_dir=images_dir, force=True, db_manager=db_manager)

    ledger = load_ledger(ledger_file)
    registered_act_ids = set()
    for entry in ledger.values():
        registered_act_ids.update(entry.get("act_ids", []))

    session = db_manager.get_session()
    try:
        acts_in_db = ActRepository(session).get_all_acts()
        htr_sim_acts = [
            act for act in acts_in_db
            if act.source_type and (act.source_type.startswith("HTR_") or act.source_type.startswith("SIMULATED_"))
        ]
        for act in htr_sim_acts:
            assert act.id in registered_act_ids, f"L'acte {act.id} de source {act.source_type} est orphelin !"
    finally:
        session.close()


def test_batch_preservation_gedcom_heredis(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """Un acte GEDCOM_HEREDIS présent en base AVANT le lot est toujours là APRÈS un --force."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger_gedcom.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    # Insérer un acte GEDCOM_HEREDIS préalable
    session = db_manager.get_session()
    try:
        gedcom_act = Act(
            act_type="Naissance GEDCOM",
            confidence_score=1.0,
            source_type="GEDCOM_HEREDIS",
            source_text="Acte GEDCOM préservé.",
            persons=[Person(first_name="Pierre", last_name="VERGNE", role="enfant")],
        )
        gedcom_act_id = ActRepository(session).save_act(gedcom_act)
    finally:
        session.close()

    # Traitement initial + retraitement avec --force
    process_batch(source_dir=images_dir, db_manager=db_manager)
    process_batch(source_dir=images_dir, force=True, db_manager=db_manager)

    # Vérifier que l'acte GEDCOM_HEREDIS est toujours présent
    session = db_manager.get_session()
    try:
        retrieved_act = ActRepository(session).get_act_by_id(gedcom_act_id)
        assert retrieved_act is not None
        assert retrieved_act.source_type == "GEDCOM_HEREDIS"
    finally:
        session.close()


def test_batch_dry_run_aucune_suppression(
    tmp_path, monkeypatch, allow_simulation, db_manager, synthetic_images
):
    """En --dry-run après un premier passage réel, aucune suppression n'a lieu en base."""
    images_dir, paths = synthetic_images
    ledger_file = tmp_path / "ledger_dry_run_del.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=images_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        count_real = ActRepository(session).count_acts()
    finally:
        session.close()

    # Lancement en --dry-run avec --force
    process_batch(source_dir=images_dir, dry_run=True, force=True, db_manager=db_manager)

    session = db_manager.get_session()
    try:
        count_after_dry_run = ActRepository(session).count_acts()
    finally:
        session.close()

    # Le nombre d'actes en base doit être strictement inchangé
    assert count_after_dry_run == count_real


def test_batch_changement_empreinte_image_remplace(
    tmp_path, monkeypatch, allow_simulation, db_manager
):
    """Une image dont le contenu (et donc le SHA-256) change est retraitée en remplacement et non en ajout."""
    scans_dir = tmp_path / "scans_modified"
    scans_dir.mkdir(parents=True, exist_ok=True)
    img_path = scans_dir / "scan_mod.jpg"

    # Version 1 de l'image
    img1 = Image.new("RGB", (100, 200), (255, 255, 255))
    ImageDraw.Draw(img1).rectangle([0, 0, 100, 60], fill=(0, 0, 0))
    img1.save(img_path)

    ledger_file = tmp_path / "ledger_mod.json"
    monkeypatch.setenv("CERTUS_BATCH_LEDGER", str(ledger_file))

    process_batch(source_dir=scans_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        count1 = ActRepository(session).count_acts()
    finally:
        session.close()

    # Version 2 de l'image (contenu modifié)
    img2 = Image.new("RGB", (100, 200), (255, 255, 255))
    ImageDraw.Draw(img2).rectangle([0, 100, 100, 160], fill=(50, 50, 50))
    img2.save(img_path)

    # Relance sans --force : le changement de SHA-256 déclenche le traitement en remplacement
    process_batch(source_dir=scans_dir, db_manager=db_manager)
    session = db_manager.get_session()
    try:
        count2 = ActRepository(session).count_acts()
    finally:
        session.close()

    # Le nombre d'actes ne doit pas s'accumuler
    assert count1 > 0
    assert count2 == count1
