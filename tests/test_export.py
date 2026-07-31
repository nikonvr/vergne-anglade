import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.genealogy.models import FamilyTree, ConsolidatedPerson, Relationship
from src.export.gedcom import GedcomExporter

client = TestClient(app)

def test_gedcom_exporter_string():
    tree = FamilyTree(
        nodes={
            "VERGNE_JEAN": ConsolidatedPerson(
                id="VERGNE_JEAN",
                first_name="Jean",
                last_name="Vergne",
                mentions=2,
                birth_date="1840-05-05",
                birth_place="Aurillac",
                death_date="1900-01-01",
                death_place="Marseille"
            ),
            "VERGNE_PIERRE": ConsolidatedPerson(
                id="VERGNE_PIERRE",
                first_name="Pierre",
                last_name="Vergne",
                mentions=1
            )
        },
        edges=[
            Relationship(source_id="VERGNE_PIERRE", target_id="VERGNE_JEAN", rel_type="pere")
        ]
    )
    exporter = GedcomExporter()
    content = exporter.export_string(tree)

    assert "0 HEAD" in content
    assert "0 @VERGNE_JEAN@ INDI" in content
    assert "1 NAME Jean /Vergne/" in content
    assert "1 BIRT" in content
    assert "2 DATE 1840-05-05" in content
    assert "2 PLAC Aurillac" in content
    assert "1 DEAT" in content
    assert "2 DATE 1900-01-01" in content
    assert "0 @F1@ FAM" in content
    assert "1 HUSB @VERGNE_PIERRE@" in content
    assert "1 CHIL @VERGNE_JEAN@" in content
    assert "0 TRLR" in content

def test_export_gedcom_endpoint():
    response = client.get("/api/export/gedcom")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "0 HEAD" in response.text
    assert "0 TRLR" in response.text
