import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.api.main import app
from src.core.models import Act, Person

client = TestClient(app)

@patch("src.ocr.florence.FlorenceOCREngine.extract_text")
@patch("src.parser.llm.LLMActParser.parse")
def test_process_pipeline_endpoint(mock_parse, mock_ocr, tmp_path):
    dummy_image = tmp_path / "archive.jpg"
    dummy_image.write_text("dummy")

    mock_ocr.return_value = "Texte brut"
    mock_parse.return_value = Act(
        act_type="naissance",
        date="1850-01-01",
        confidence_score=0.98,
        persons=[Person(first_name="Jean", last_name="Vergne", role="enfant")]
    )

    response = client.post("/api/pipeline/process", json={"image_path": str(dummy_image)})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["act_id"] > 0

def test_websocket_progress():
    with client.websocket_connect("/ws/progress") as websocket:
        websocket.send_text("ping")

def test_get_tree_endpoint():
    response = client.get("/api/tree")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data

def test_get_act_detail_endpoint():
    response = client.get("/api/acts/1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert "act_type" in data
    assert "persons" in data



