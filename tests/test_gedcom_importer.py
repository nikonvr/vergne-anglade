import pytest
from src.parser.gedcom_importer import GedcomImporter

def test_gedcom_importer_vergne_branch_sample(tmp_path):
    sample_ged = tmp_path / "sample.ged"
    sample_ged.write_text("""0 HEAD
1 SOUR TEST
0 @I1@ INDI
1 NAME Jean /VERGNE/
1 OCCU laboureur
1 BIRT
2 DATE 05 MAY 1840
2 PLAC Aurillac
0 @I2@ INDI
1 NAME Paul /LEMARCHAND/
0 TRLR
""", encoding="utf-8")

    importer = GedcomImporter(sample_ged)
    acts = importer.parse_vergne_branch()

    # Uniquement Jean VERGNE doit être extrait, pas Paul LEMARCHAND
    assert len(acts) == 1
    assert acts[0].persons[0].last_name == "VERGNE"
    assert acts[0].persons[0].first_name == "Jean"
    assert acts[0].persons[0].occupation == "laboureur"
    assert acts[0].date == "05 MAY 1840"
