import pytest
from src.core.models import Act, Person
from src.genealogy.builder import TreeBuilder

def test_tree_builder_consolidation():
    act1 = Act(
        act_type="naissance",
        confidence_score=0.9,
        persons=[
            Person(first_name="Jean", last_name="Vergne", role="enfant"),
            Person(first_name="Pierre", last_name="Vergne", role="père"),
        ]
    )
    act2 = Act(
        act_type="mariage",
        confidence_score=0.95,
        persons=[
            Person(first_name="Jean", last_name="Vergne", role="époux"),
        ]
    )

    builder = TreeBuilder()
    tree = builder.process_acts([act1, act2])

    assert len(tree.nodes) == 2
    assert "VERGNE_JEAN" in tree.nodes
    assert tree.nodes["VERGNE_JEAN"].mentions == 2
    assert "VERGNE_PIERRE" in tree.nodes
    assert tree.nodes["VERGNE_PIERRE"].mentions == 1

def test_tree_builder_fuzzy_matching():
    act1 = Act(
        act_type="naissance",
        confidence_score=0.9,
        persons=[Person(first_name="Jean", last_name="VERGNE", role="enfant")]
    )
    act2 = Act(
        act_type="deces",
        confidence_score=0.88,
        persons=[Person(first_name="Jean", last_name="VERNHES", role="defunt")]
    )

    builder = TreeBuilder()
    tree = builder.process_acts([act1, act2])

    assert len(tree.nodes) == 1
    assert "VERGNE_JEAN" in tree.nodes
    assert tree.nodes["VERGNE_JEAN"].mentions == 2

