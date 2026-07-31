"""Analyse de parenté et rapport HTML (constats M4 et Mod9).

L'ancienne assertion « ancestor is None or isinstance(ancestor, str) » était une tautologie :
elle passait quoi qu'il arrive, ce qui a laissé passer M4 (analyse de parenté toujours
inopérante).
"""

from src.core.models import Act, Person
from src.database.repository import ActRepository
from src.export.html_report import HtmlReportExporter
from src.genealogy.builder import TreeBuilder


def _fratrie_act(child_id: str, child_name: str) -> Act:
    return Act(
        act_type="Naissance",
        confidence_score=1.0,
        family_id="@F1@",
        persons=[
            Person(source_id=child_id, first_name=child_name, last_name="VERGNE", role="enfant"),
            Person(source_id="@I2@", first_name="Pierre", last_name="VERGNE", role="père"),
            Person(source_id="@I3@", first_name="Marie", last_name="ANGLADE", role="mère"),
        ],
    )


def test_ancetre_commun_reellement_trouve():
    """M4 : deux frères et sœurs ont pour ancêtre commun l'un de leurs parents."""
    builder = TreeBuilder()
    tree = builder.process_acts([_fratrie_act("@I1@", "Jean"), _fratrie_act("@I4@", "Anne")])

    assert len(tree.nodes) == 4
    ancestor = builder.find_common_ancestor("I1", "I4")

    assert ancestor in ("I2", "I3")
    path = builder.get_relationship_path("I1", "I4")
    assert path[0] == "I1" and path[-1] == "I4"
    assert len(path) == 3  # enfant -> parent -> enfant


def test_graphe_de_filiation_acyclique():
    """C3 : l'arbre construit ne doit contenir aucun cycle de filiation."""
    builder = TreeBuilder()
    builder.process_acts([_fratrie_act("@I1@", "Jean"), _fratrie_act("@I4@", "Anne")])

    report = builder.validate()
    assert report["is_acyclic"] is True
    assert report["cycles"] == []


def test_parente_inconnue_retourne_vide():
    builder = TreeBuilder()
    builder.process_acts([_fratrie_act("@I1@", "Jean")])

    assert builder.find_common_ancestor("I1", "INEXISTANT") is None
    assert builder.get_relationship_path("I1", "INEXISTANT") == []


def test_analyse_de_parente_survit_au_cache(setup_test_db):
    """M4 : le graphe reste exploitable sur des requêtes successives.

    Le cache d'arbre est un attribut de classe alors que le graphe networkx vit sur
    l'instance du TreeBuilder : servir l'arbre en cache sans son builder laissait le graphe
    vide dès la deuxième requête, et l'analyse renvoyait systématiquement None et [].
    """
    from src.core.orchestrator import CertusOrchestrator

    with setup_test_db.get_session() as session:
        acts = ActRepository(session).get_all_acts()
    assert acts

    graphes = []
    for _ in range(3):
        orchestrator = CertusOrchestrator(setup_test_db)
        orchestrator.generate_global_tree()
        graphes.append(orchestrator.tree_builder.graph.number_of_nodes())

    assert graphes[0] > 0
    assert len(set(graphes)) == 1, f"le graphe s'est vidé entre les requêtes : {graphes}"

    orchestrator = CertusOrchestrator(setup_test_db)
    orchestrator.generate_global_tree()
    assert orchestrator.tree_builder.find_common_ancestor("I1", "I4") in ("I2", "I3")


def test_rapport_html_echappe_les_donnees():
    """Mod9 : un patronyme contenant du balisage ne doit pas produire de HTML actif."""
    builder = TreeBuilder()
    tree = builder.process_acts(
        [
            Act(
                act_type="Naissance",
                confidence_score=1.0,
                persons=[
                    Person(
                        source_id="@I9@",
                        first_name="<script>alert(1)</script>",
                        last_name="D'ANGLADE",
                        role="enfant",
                    )
                ],
            )
        ]
    )

    html = HtmlReportExporter().generate_html(tree)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "ANGLADE" in html
