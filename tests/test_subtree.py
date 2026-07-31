"""Extraction de sous-arbres généalogiques (zoom sur une branche).

Arbre de référence utilisé par ces tests, trois générations :

    I_GP1   I_GP2         I_GP3   I_GP4
        \\   /                 \\   /
        I_PARENT1             I_PARENT2
              \\                 /
               \\               /
                 I_ENFANT1   I_ENFANT2
                       (enfants de PARENT1 x PARENT2)

PARENT1 et PARENT2 sont conjoints : ENFANT1 et ENFANT2 ont pour père PARENT1 et pour
mère PARENT2 (ou l'inverse, peu importe pour ces tests).
"""

import pytest

from src.core.models import Act, Person
from src.genealogy.builder import TreeBuilder


def _acts():
    return [
        # Génération grands-parents -> parent 1
        Act(
            act_type="Filiation",
            confidence_score=1.0,
            family_id="@F1@",
            persons=[
                Person(source_id="I_PARENT1", first_name="Parent", last_name="UN", role="enfant"),
                Person(source_id="I_GP1", first_name="Grand", last_name="PERE1", role="père"),
                Person(source_id="I_GP2", first_name="Grand", last_name="MERE1", role="mère"),
            ],
        ),
        # Génération grands-parents -> parent 2
        Act(
            act_type="Filiation",
            confidence_score=1.0,
            family_id="@F2@",
            persons=[
                Person(source_id="I_PARENT2", first_name="Parent", last_name="DEUX", role="enfant"),
                Person(source_id="I_GP3", first_name="Grand", last_name="PERE2", role="père"),
                Person(source_id="I_GP4", first_name="Grand", last_name="MERE2", role="mère"),
            ],
        ),
        # Génération parents -> enfant 1
        Act(
            act_type="Filiation",
            confidence_score=1.0,
            family_id="@F3@",
            persons=[
                Person(source_id="I_ENFANT1", first_name="Enfant", last_name="A", role="enfant"),
                Person(source_id="I_PARENT1", first_name="Parent", last_name="UN", role="père"),
                Person(source_id="I_PARENT2", first_name="Parent", last_name="DEUX", role="mère"),
            ],
        ),
        # Génération parents -> enfant 2 (même couple)
        Act(
            act_type="Filiation",
            confidence_score=1.0,
            family_id="@F3@",
            persons=[
                Person(source_id="I_ENFANT2", first_name="Enfant", last_name="B", role="enfant"),
                Person(source_id="I_PARENT1", first_name="Parent", last_name="UN", role="père"),
                Person(source_id="I_PARENT2", first_name="Parent", last_name="DEUX", role="mère"),
            ],
        ),
        # Individu isolé, sans aucune arête de filiation
        Act(
            act_type="Acte",
            confidence_score=1.0,
            persons=[
                Person(source_id="I_ISOLE", first_name="Sans", last_name="LIEN", role="principal")
            ],
        ),
    ]


@pytest.fixture
def builder_and_tree():
    builder = TreeBuilder()
    tree = builder.process_acts(_acts())
    return builder, tree


def test_racine_absente_retourne_vide(builder_and_tree):
    builder, _ = builder_and_tree
    assert builder.subtree_ids("N_EXISTE_PAS") == set()


def test_individu_isole_retourne_lui_seul(builder_and_tree):
    builder, _ = builder_and_tree
    assert builder.subtree_ids("I_ISOLE", up=3, down=3) == {"I_ISOLE"}


def test_profondeur_zero_retourne_la_racine_seule(builder_and_tree):
    builder, _ = builder_and_tree
    assert builder.subtree_ids("I_PARENT1", up=0, down=0) == {"I_PARENT1"}


def test_ascendants_un_niveau(builder_and_tree):
    """Remonter d'un niveau depuis un parent donne ses deux propres parents."""
    builder, _ = builder_and_tree
    ids = builder.subtree_ids("I_PARENT1", up=1, down=0)
    assert ids == {"I_PARENT1", "I_GP1", "I_GP2"}


def test_descendants_un_niveau(builder_and_tree):
    builder, _ = builder_and_tree
    ids = builder.subtree_ids("I_PARENT1", up=0, down=1)
    assert ids == {"I_PARENT1", "I_ENFANT1", "I_ENFANT2"}


def test_conjoint_naturellement_inclus_dans_la_descendance(builder_and_tree):
    """Le conjoint d'un descendant apparaît sans traitement particulier : ENFANT1 a deux
    parents (PARENT1 et PARENT2), donc PARENT2 ressort comme co-parent de PARENT1."""
    builder, _ = builder_and_tree
    ids = builder.subtree_ids("I_PARENT1", up=0, down=1)
    assert "I_PARENT2" not in ids  # PARENT2 n'est PAS un descendant de PARENT1

    # Mais si on prend le sous-arbre centré sur l'ENFANT en remontant d'un niveau,
    # les DEUX parents apparaissent.
    ids_enfant = builder.subtree_ids("I_ENFANT1", up=1, down=0)
    assert ids_enfant == {"I_ENFANT1", "I_PARENT1", "I_PARENT2"}


def test_profondeur_superieure_a_la_hauteur_reelle_ne_plante_pas(builder_and_tree):
    """up/down plus grand que le nombre de générations réelles : pas d'erreur, le front
    de recherche s'épuise simplement (couvert par le `if not frontier: break`)."""
    builder, _ = builder_and_tree
    ids = builder.subtree_ids("I_ENFANT1", up=50, down=50)
    assert ids == {"I_ENFANT1", "I_PARENT1", "I_PARENT2", "I_GP1", "I_GP2", "I_GP3", "I_GP4"}


def test_subtree_filtre_noeuds_et_aretes(builder_and_tree):
    """subtree() renvoie un FamilyTree où toute arête relie deux nœuds du sous-ensemble."""
    builder, tree = builder_and_tree
    filtered = builder.subtree(tree, "I_PARENT1", up=0, down=1)

    assert set(filtered.nodes) == {"I_PARENT1", "I_ENFANT1", "I_ENFANT2"}
    assert len(filtered.edges) == 2  # PARENT1 -> ENFANT1, PARENT1 -> ENFANT2
    for rel in filtered.edges:
        assert rel.source_id in filtered.nodes
        assert rel.target_id in filtered.nodes


def test_subtree_racine_absente_retourne_arbre_vide(builder_and_tree):
    builder, tree = builder_and_tree
    filtered = builder.subtree(tree, "N_EXISTE_PAS")
    assert filtered.nodes == {}
    assert filtered.edges == []


def test_subtree_conserve_les_donnees_completes_des_personnes(builder_and_tree):
    """Le filtrage ne doit pas dégrader les informations déjà consolidées (occupation,
    dates...) : subtree() ne fait que retirer des entrées, jamais en transformer une."""
    builder, tree = builder_and_tree
    filtered = builder.subtree(tree, "I_PARENT1", up=0, down=0)
    assert filtered.nodes["I_PARENT1"] == tree.nodes["I_PARENT1"]
