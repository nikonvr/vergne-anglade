"""Invariants du projet — garde-fous exécutables.

Chaque test correspond à un défaut réel constaté par un audit. Un échec ici ne signifie pas
« le test est à ajuster » mais « une protection vient d'être retirée ». Lisez le docstring
avant de modifier quoi que ce soit, et en cas de doute sur une règle métier, demandez au
propriétaire du projet plutôt que de trancher seul.

Voir AGENTS.md pour le corridor complet.
"""

import pytest

from scripts.check_invariants import INVARIANTS
from src.core.models import Act, Person, SearchQuery
from src.genealogy.builder import TreeBuilder
from src.genealogy.variants import (
    BRANCH_SURNAMES,
    NOT_BRANCH_SURNAMES,
    is_branch_surname,
    same_surname_group,
)


# --------------------------------------------------------------- invariants statiques
@pytest.mark.parametrize("invariant", INVARIANTS, ids=lambda inv: inv.code)
def test_invariant_statique(invariant):
    """Rejoue les invariants de scripts/check_invariants.py dans la suite de tests."""
    violations = invariant.check()
    if violations:
        detail = "\n".join(f"  - {v.location} : {v.message}" for v in violations)
        pytest.fail(
            f"{invariant.code} « {invariant.title} » violé.\n"
            f"Raison d'être : {invariant.rationale}\n{detail}"
        )


# ------------------------------------------------- règles métier sur les patronymes
@pytest.mark.parametrize("surname", ["VERGNE", "VERGNES", "ANGLADE", "BRUN", "JEHL", "IEHL"])
def test_patronymes_du_fonds_acceptes(surname):
    assert is_branch_surname(surname) is True


@pytest.mark.parametrize(
    "surname",
    ["LAVERGNE", "LEVERGNE", "BRUNET", "BRUNEAU", "BRUNSTEIN", "STEINBRUNN", "LANGLADE"],
)
def test_patronymes_etrangers_rejetes(surname):
    """DÉCISION DU PROPRIÉTAIRE : ces patronymes sont des familles distinctes.

    LAVERGNE et LEVERGNE ne sont PAS des variantes de VERGNE. La comparaison par
    sous-chaîne les rattachait à tort : « VERGNE » in « LAVERGNE » est vrai. Elle amenait
    15 individus étrangers dans le fonds.
    """
    assert is_branch_surname(surname) is False


@pytest.mark.parametrize("a, b", [("VERGNE", "VERGNES"), ("JEHL", "IEHL"), ("VERGNE", "VERNHES")])
def test_variantes_attestees_fusionnent(a, b):
    """DÉCISION DU PROPRIÉTAIRE : VERGNES est une variante de VERGNE, JEHL et IEHL sont
    le même nom."""
    assert same_surname_group(a, b) is True


@pytest.mark.parametrize(
    "a, b",
    [
        ("VERGNE", "LAVERGNE"),
        ("VERGNES", "LEVERGNE"),
        ("BRUN", "BRUNET"),
        ("ANGLADE", "LANGLADE"),
        ("MURAT", "MURET"),
    ],
)
def test_patronymes_distincts_ne_fusionnent_jamais(a, b):
    """L'ancien seuil max(2, 45 % de la longueur) fusionnait des familles distinctes."""
    assert same_surname_group(a, b) is False


def test_exclusions_documentees():
    assert "LAVERGNE" in NOT_BRANCH_SURNAMES
    assert "LEVERGNE" in NOT_BRANCH_SURNAMES
    assert NOT_BRANCH_SURNAMES.isdisjoint({s.upper() for s in BRANCH_SURNAMES})


# ------------------------------------------------------------------ identité (R3)
def _person(source_id, first_name="Jean", last_name="VERGNE", **kwargs):
    return Person(
        source_id=source_id, first_name=first_name, last_name=last_name, role="principal", **kwargs
    )


def test_homonymes_avec_identifiants_distincts_ne_fusionnent_jamais():
    """R3 : 7 personnes différentes portant le même nom n'en formaient qu'une seule."""
    acts = [
        Act(act_type="Acte", confidence_score=1.0, persons=[_person("@I1@")]),
        Act(act_type="Acte", confidence_score=1.0, persons=[_person("@I2@")]),
        Act(act_type="Acte", confidence_score=1.0, persons=[_person("@I3@")]),
    ]
    tree = TreeBuilder().process_acts(acts)

    assert len(tree.nodes) == 3, "des homonymes distincts ont été fusionnés"


def test_annee_departage_les_homonymes_sans_identifiant():
    """Sans source_id, l'année de naissance sert de discriminant."""
    acts = [
        Act(
            act_type="Acte",
            confidence_score=1.0,
            persons=[Person(first_name="Jean", last_name="VERGNE", role="principal", birth_date="1780")],
        ),
        Act(
            act_type="Acte",
            confidence_score=1.0,
            persons=[Person(first_name="Jean", last_name="VERGNE", role="principal", birth_date="1812")],
        ),
    ]
    tree = TreeBuilder().process_acts(acts)

    assert len(tree.nodes) == 2


def test_graphe_reste_acyclique():
    """Les cycles signifiaient qu'un individu était son propre ancêtre."""
    builder = TreeBuilder()
    builder.process_acts(
        [
            Act(
                act_type="Filiation",
                confidence_score=1.0,
                family_id="@F1@",
                persons=[
                    Person(source_id="@I1@", first_name="Jean", last_name="VERGNE", role="enfant"),
                    Person(source_id="@I2@", first_name="Jean", last_name="VERGNE", role="père"),
                ],
            )
        ]
    )
    report = builder.validate()

    assert report["is_acyclic"] is True, f"cycles détectés : {report['cycles']}"


# ------------------------------------------------------------------ contrat de données
def test_search_query_refuse_un_champ_inconnu():
    """Mod4 : SearchQuery(surname=...) était silencieusement ignoré."""
    with pytest.raises(Exception):
        SearchQuery(surname="VERGNE")

    assert SearchQuery(last_name="VERGNE").last_name == "VERGNE"


def test_act_non_simule_par_defaut():
    """R2 : un acte est réputé sourcé, la simulation doit être déclarée explicitement."""
    act = Act(act_type="Naissance", confidence_score=1.0)
    assert act.is_simulated is False


def test_annotations_publiques_resolubles():
    """C4 : une annotation référençant un symbole typing non importé passe inaperçue en
    Python 3.14 (évaluation tardive) mais casse à l'import en 3.11, que cible la CI."""
    import importlib
    import inspect
    import pkgutil

    import src

    failures = []
    for module_info in pkgutil.walk_packages(src.__path__, prefix="src."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # pragma: no cover
            failures.append(f"{module_info.name} : import impossible ({exc})")
            continue
        for name, obj in vars(module).items():
            if not (inspect.isclass(obj) or inspect.isfunction(obj)):
                continue
            if getattr(obj, "__module__", None) != module_info.name:
                continue
            try:
                inspect.signature(obj)
            except NameError as exc:
                failures.append(f"{module_info.name}.{name} : {exc}")
            except (ValueError, TypeError):
                continue

    assert not failures, "annotations non résolubles :\n" + "\n".join(failures)
