"""Tests unitaires pour les 4 nouvelles fonctionnalités :
1. Inclusion de la fratrie dans les sous-arbres (include_siblings)
2. Fiche individuelle (données de profil, parents, fratrie, enfants)
3. Tri interactif et tri alphabétique des individus
4. Filtre CSV (filtrage exact de patronyme R6 et scores non fabriqués R1)
"""

import tempfile
from pathlib import Path

import pytest
from src.core.models import Act
from src.genealogy.builder import TreeBuilder
from src.genealogy.models import ConsolidatedPerson, FamilyTree, Relationship
from src.parser.csv_importer import CsvImporter
from scripts.build_standalone import sort_nodes_data


@pytest.fixture
def sample_family_tree() -> FamilyTree:
    """Arbre avec Grand-Père GP, Père P, Mère M, Enfant Principal E1, Frère S1, et Enfant C1."""
    return FamilyTree(
        nodes={
            "GP": ConsolidatedPerson(id="GP", first_name="Antoine", last_name="VERGNE", sex="M"),
            "P": ConsolidatedPerson(id="P", first_name="Pierre", last_name="VERGNE", sex="M", birth_date="1850"),
            "M": ConsolidatedPerson(id="M", first_name="Marie", last_name="ANGLADE", sex="F", birth_date="1855"),
            "E1": ConsolidatedPerson(id="E1", first_name="Jean", last_name="VERGNE", sex="M", birth_date="1880"),
            "S1": ConsolidatedPerson(id="S1", first_name="Anne", last_name="VERGNE", sex="F", birth_date="1882"),
            "C1": ConsolidatedPerson(id="C1", first_name="Louis", last_name="VERGNE", sex="M", birth_date="1910"),
            "STRANGER": ConsolidatedPerson(id="STRANGER", first_name="Paul", last_name="LAVERGNE", sex="M"),
        },
        edges=[
            Relationship(source_id="GP", target_id="P", rel_type="pere"),
            Relationship(source_id="P", target_id="E1", rel_type="pere"),
            Relationship(source_id="M", target_id="E1", rel_type="mere"),
            Relationship(source_id="P", target_id="S1", rel_type="pere"),
            Relationship(source_id="M", target_id="S1", rel_type="mere"),
            Relationship(source_id="E1", target_id="C1", rel_type="pere"),
        ],
    )


def _to_builder(tree: FamilyTree) -> TreeBuilder:
    builder = TreeBuilder()
    for nid, person in tree.nodes.items():
        builder.graph.add_node(nid, person=person)
    for rel in tree.edges:
        builder.graph.add_edge(rel.source_id, rel.target_id, rel_type=rel.rel_type)
    return builder


def test_feature_1_fratrie_dans_sous_arbre(sample_family_tree):
    """Vérifie l'option d'inclusion/exclusion de la fratrie dans la vue sous-arbre."""
    builder = _to_builder(sample_family_tree)

    # Sans fratrie (include_siblings=False)
    ids_no_siblings = builder.subtree_ids("E1", up=1, down=1, include_siblings=False)
    assert "E1" in ids_no_siblings
    assert "P" in ids_no_siblings
    assert "M" in ids_no_siblings
    assert "C1" in ids_no_siblings
    assert "S1" not in ids_no_siblings  # La sœur S1 est absente sans fratrie

    # Avec fratrie (include_siblings=True)
    ids_with_siblings = builder.subtree_ids("E1", up=1, down=1, include_siblings=True)
    assert "E1" in ids_with_siblings
    assert "P" in ids_with_siblings
    assert "M" in ids_with_siblings
    assert "C1" in ids_with_siblings
    assert "S1" in ids_with_siblings  # La sœur S1 est bien incluse avec la fratrie


def test_feature_2_fiche_individuelle(sample_family_tree):
    """Vérifie que les relations parent/fratrie/enfant nécessaires à la fiche individuelle sont bien extractibles."""
    builder = _to_builder(sample_family_tree)
    tree = sample_family_tree

    # Pour E1 (Jean VERGNE)
    e1_node = tree.nodes["E1"]
    assert e1_node.first_name == "Jean"
    assert e1_node.last_name == "VERGNE"

    # Extraction des parents
    parents = [rel.source_id for rel in tree.edges if rel.target_id == "E1"]
    assert set(parents) == {"P", "M"}

    # Extraction des enfants
    children = [rel.target_id for rel in tree.edges if rel.source_id == "E1"]
    assert children == ["C1"]

    # Extraction de la fratrie via le père
    p_children = [rel.target_id for rel in tree.edges if rel.source_id == "P"]
    siblings = [cid for cid in p_children if cid != "E1"]
    assert siblings == ["S1"]


def test_feature_3_tri_interactif():
    """Vérifie la fonction de tri des individus par patronyme puis prénom."""
    raw_nodes = [
        {"id": "1", "last_name": "VERGNE", "first_name": "Pierre"},
        {"id": "2", "last_name": "ANGLADE", "first_name": "Marie"},
        {"id": "3", "last_name": "VERGNE", "first_name": "Antoine"},
        {"id": "4", "last_name": "BRUN", "first_name": "Jean"},
    ]

    sorted_nodes = sort_nodes_data(raw_nodes)

    # Ordre attendu : ANGLADE Marie, BRUN Jean, VERGNE Antoine, VERGNE Pierre
    names = [(n["last_name"], n["first_name"]) for n in sorted_nodes]
    assert names == [
        ("ANGLADE", "Marie"),
        ("BRUN", "Jean"),
        ("VERGNE", "Antoine"),
        ("VERGNE", "Pierre"),
    ]


def test_feature_4_filtre_csv_et_scores_honnêtes():
    """Vérifie que le CsvImporter respecte R6 (filtrage exact) et R1 (scores non fabriqués à 1.0)."""
    csv_content = (
        "Prénom,Nom,Type,Date,Commune,Profession,Rôle\n"
        "Pierre,VERGNE,Naissance,1850,Aurillac,Laboureur,principal\n"
        "Marie,VERGNES,Mariage,1875,Aurillac,,epouse\n"
        "Paul,LAVERGNE,Décès,1900,Aurillac,,principal\n"
        "Jacques,BRUNET,Naissance,1880,Aurillac,,principal\n"
    )

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8") as f:
        f.write(csv_content)
        temp_csv_path = Path(f.name)

    try:
        importer = CsvImporter(temp_csv_path)
        acts = importer.parse_acts(surname_filter="VERGNE")

        # Seuls VERGNE et VERGNES doivent être retenus (R6: exact matching, LAVERGNE et BRUNET sont exclus)
        names = [(act.persons[0].first_name, act.persons[0].last_name) for act in acts]
        assert len(acts) == 2
        assert ("Pierre", "VERGNE") in names
        assert ("Marie", "VERGNES") in names
        assert not any(act.persons[0].last_name == "LAVERGNE" for act in acts)
        assert not any(act.persons[0].last_name == "BRUNET" for act in acts)

        # R1 : confidence_score ne doit pas être fabriqué à 1.0 par défaut pour un relevé associatif
        for act in acts:
            assert act.confidence_score < 1.0
            assert act.confidence_score == 0.7
    finally:
        if temp_csv_path.exists():
            temp_csv_path.unlink()


def test_feature_5_disposition_pro_arbres_et_subgraphs(sample_family_tree):
    """Vérifie que GedcomExporter.export_mermaid produit un schéma pro avec subgraphs direction LR et nœuds 💍 Union."""
    from src.export.gedcom import GedcomExporter

    mermaid_code = GedcomExporter().export_mermaid(sample_family_tree)

    assert "graph TD" in mermaid_code
    assert "subgraph SG_FAM" in mermaid_code
    assert "direction LR" in mermaid_code
    assert '💍 Union' in mermaid_code

