"""Validité de l'export GEDCOM (constat M5).

L'ancien export produisait 137 identifiants invalides sur 595 (espaces et accents), un
enregistrement FAM par arête — donc le père et la mère d'un même enfant dans deux familles
monoparentales distinctes —, aucun événement BIRT/DEAT et un en-tête sans GEDC ni CHAR.
"""

import re

from src.export.gedcom import GedcomExporter
from src.genealogy.models import ConsolidatedPerson, FamilyTree, Relationship

XREF_RE = re.compile(r"^0 @([A-Za-z0-9_]+)@ (INDI|FAM)$")


def _tree() -> FamilyTree:
    """Un couple et deux enfants, avec des identifiants volontairement hostiles."""
    return FamilyTree(
        nodes={
            "VERGNE_JEAN AIMABLE MARIE": ConsolidatedPerson(
                id="VERGNE_JEAN AIMABLE MARIE",
                first_name="Jean Aimable Marie",
                last_name="VERGNE",
                sex="M",
                occupation="laboureur",
                birth_date="05 MAY 1840",
                birth_place="Anglards-de-Salers,15380,Cantal,,FRANCE,",
                death_date="01 JAN 1900",
                death_place="Marseille,13000,,,FRANCE,",
            ),
            "ANGLADE_MARIE LÉON": ConsolidatedPerson(
                id="ANGLADE_MARIE LÉON",
                first_name="Marie Léon",
                last_name="ANGLADE",
                sex="F",
                birth_date="1815",
            ),
            "VERGNE_ENFANT": ConsolidatedPerson(
                id="VERGNE_ENFANT", first_name="Anne", last_name="VERGNE", sex="F"
            ),
            "VERGNE_CADET": ConsolidatedPerson(
                id="VERGNE_CADET", first_name="Louis", last_name="VERGNE", sex="M"
            ),
        },
        edges=[
            Relationship(
                source_id="VERGNE_JEAN AIMABLE MARIE",
                target_id="VERGNE_ENFANT",
                rel_type="pere",
                family_id="@F1@",
            ),
            Relationship(
                source_id="ANGLADE_MARIE LÉON",
                target_id="VERGNE_ENFANT",
                rel_type="mere",
                family_id="@F1@",
            ),
            Relationship(
                source_id="VERGNE_JEAN AIMABLE MARIE",
                target_id="VERGNE_CADET",
                rel_type="pere",
                family_id="@F1@",
            ),
            Relationship(
                source_id="ANGLADE_MARIE LÉON",
                target_id="VERGNE_CADET",
                rel_type="mere",
                family_id="@F1@",
            ),
        ],
    )


def test_identifiants_conformes():
    """M5 : aucun xref ne contient d'espace ni d'accent, malgré des ids de nœuds hostiles."""
    lines = GedcomExporter().export_string(_tree()).splitlines()
    records = [line for line in lines if line.startswith("0 @")]

    assert records
    assert all(XREF_RE.match(line) for line in records)


def test_une_seule_famille_par_couple():
    """M5 : les deux parents d'un enfant sont dans UNE famille, pas deux monoparentales."""
    content = GedcomExporter().export_string(_tree())
    lines = content.splitlines()

    assert lines.count("0 @F1@ FAM") == 1
    assert sum(1 for line in lines if line.endswith(" FAM")) == 1

    family_block = content.split("0 @F1@ FAM")[1]
    assert sum(1 for line in family_block.splitlines() if line.startswith("1 HUSB")) == 1
    assert sum(1 for line in family_block.splitlines() if line.startswith("1 WIFE")) == 1
    assert sum(1 for line in family_block.splitlines() if line.startswith("1 CHIL")) == 2


def test_evenements_et_liens_familiaux_presents():
    """M5 et M6 : les dates, les lieux et les rattachements FAMC/FAMS sont exportés."""
    lines = GedcomExporter().export_string(_tree()).splitlines()

    assert "1 BIRT" in lines
    assert "1 DEAT" in lines
    assert "2 DATE 05 MAY 1840" in lines
    assert any(line.startswith("2 PLAC Anglards-de-Salers") for line in lines)
    assert any(line.startswith("1 FAMC @") for line in lines)
    assert any(line.startswith("1 FAMS @") for line in lines)


def test_entete_et_cloture_conformes():
    """M5 : en-tête GEDCOM 5.5.1 complet, absent de l'ancien export."""
    lines = GedcomExporter().export_string(_tree()).splitlines()

    assert lines[0] == "0 HEAD"
    assert "1 GEDC" in lines
    assert "2 VERS 5.5.1" in lines
    assert "2 FORM LINEAGE-LINKED" in lines
    assert "1 CHAR UTF-8" in lines
    assert lines[-1] == "0 TRLR"


def test_integrite_referentielle_et_longueur_des_lignes():
    content = GedcomExporter().export_string(_tree())
    declared = set(re.findall(r"^0 @([A-Za-z0-9_]+)@", content, re.M))
    referenced = set(
        re.findall(r"^1 (?:HUSB|WIFE|CHIL|FAMC|FAMS) @([A-Za-z0-9_]+)@", content, re.M)
    )

    assert referenced <= declared
    assert all(len(line) <= 255 for line in content.splitlines())


def test_mermaid_neutralise_les_caracteres_dangereux():
    """Un patronyme contenant des guillemets ou des crochets ne casse pas le diagramme."""
    tree = FamilyTree(
        nodes={
            "X": ConsolidatedPerson(
                id="X", first_name='Jean"[x]', last_name="D'ANGLADE", birth_place="Aurillac,15000"
            )
        }
    )
    mermaid = GedcomExporter().export_mermaid(tree)

    label = next(line for line in mermaid.splitlines() if line.strip().startswith("P1["))
    assert label.count('"') == 2
    assert "[x]" not in label
    assert "Aurillac" in label and "15000" not in label


def test_mermaid_prenom_et_nom_sur_deux_lignes():
    """Un nom complet sur une seule ligne dépasse souvent la largeur de la boîte Mermaid
    et se fait tronquer ("Françoise Jeanne Marie AN" au lieu de "...ANGLADE") : prénom et
    nom doivent être séparés par un retour à la ligne."""
    tree = FamilyTree(
        nodes={
            "X": ConsolidatedPerson(id="X", first_name="Françoise Jeanne Marie", last_name="ANGLADE")
        }
    )
    mermaid = GedcomExporter().export_mermaid(tree)

    label = next(line for line in mermaid.splitlines() if line.strip().startswith("P1["))
    assert "<b>Françoise Jeanne Marie</b><br/><b>ANGLADE</b>" in label
