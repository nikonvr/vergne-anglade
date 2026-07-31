import pytest
from unittest.mock import patch
from src.core.orchestrator import CertusOrchestrator
from src.database.engine import DatabaseManager
from src.core.models import Act, Person

@pytest.fixture
def db_manager():
    """Fournit un gestionnaire de base de données en mémoire pour le test."""
    manager = DatabaseManager(db_url="sqlite:///:memory:")
    manager.init_db()
    return manager

@pytest.fixture
def dummy_image(tmp_path):
    image_file = tmp_path / "test_archive.jpg"
    image_file.write_text("fake image content")
    return image_file

@patch("src.ocr.florence.FlorenceOCREngine.extract_text")
@patch("src.parser.llm.LLMActParser.parse")
def test_process_document_pipeline(mock_parse, mock_ocr, db_manager, dummy_image):
    """
    Teste le chef d'orchestre de bout en bout en mockant uniquement les appels IA (LLM et OCR)
    pour vérifier que la logique de liaison (Pipeline) et la persistance fonctionnent.
    """
    # 1. Configuration des Mocks
    mock_ocr.return_value = "L'an mil huit cent quarante..."
    
    mock_act = Act(
        act_type="naissance",
        date="1840-01-01",
        confidence_score=0.99,
        persons=[Person(first_name="Jean", last_name="VERGNE", role="principal")],
        source_text="L'an mil huit cent quarante..."
    )
    mock_parse.return_value = mock_act

    # 2. Exécution du pipeline
    orchestrator = CertusOrchestrator(db_manager)
    act_id = orchestrator.process_document(dummy_image)

    # 3. Assertions
    assert act_id is not None
    assert act_id > 0
    mock_ocr.assert_called_once_with(dummy_image)
    mock_parse.assert_called_once_with("L'an mil huit cent quarante...")
