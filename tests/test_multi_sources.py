import pytest
from src.core.models import Act, Person
from src.parser.csv_importer import CsvImporter
from src.crawler.gallica import GallicaAPIClient

def test_act_etl_fields():
    act = Act(
        act_type="Mariage",
        confidence_score=0.95,
        source_type="CSV_APROGEMERE",
        url_source="https://aprogemere.fr/acte/123",
        reliability_score=0.90,
        persons=[Person(first_name="Jean", last_name="VERGNE", role="époux")]
    )
    assert act.source_type == "CSV_APROGEMERE"
    assert act.url_source == "https://aprogemere.fr/acte/123"
    assert act.reliability_score == 0.90

def test_csv_importer_sample(tmp_path):
    csv_file = tmp_path / "releve_aprogemere.csv"
    csv_file.write_text("""nom,prenom,type,date,commune,profession,url
VERGNE,Pierre,Naissance,1840-05-05,Anglards-de-Salers,laboureur,https://aprogemere.fr/act/1
LEMARCHAND,Paul,Naissance,1850-01-01,Aix,enseignant,https://aprogemere.fr/act/2
""", encoding="utf-8")

    importer = CsvImporter(csv_file)
    acts = importer.parse_acts(surname_filter="VERGNE")

    assert len(acts) == 1
    assert acts[0].persons[0].last_name == "VERGNE"
    assert acts[0].persons[0].first_name == "Pierre"
    assert acts[0].source_type == "CSV_APROGEMERE"
    assert acts[0].url_source == "https://aprogemere.fr/act/1"
