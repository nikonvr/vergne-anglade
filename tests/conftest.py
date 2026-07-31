"""Harnais de test : base isolée et jeu de données minimal.

L'ancienne fixture appelait seed_initial_data_if_empty() pour CHAQUE test, ce qui reparsait
un GEDCOM de 2,2 Mo puis insérait ~334 actes avec un commit par acte : la suite de 25 tests
mettait 20 minutes. Elle touchait de surcroît la base de production, puisque le seeding
s'exécutait à l'import de src.api.main.
"""

import pytest

from src.core.models import Act, Person
from src.core.orchestrator import CertusOrchestrator
from src.database.engine import DatabaseManager
from src.database.repository import ActRepository

_PLACE = "Anglards-de-Salers,15380,Cantal,,FRANCE,"


def sample_acts() -> list[Act]:
    """Jeu de données minimal : un couple et ses deux enfants, identités explicites."""
    father = dict(source_id="@I2@", first_name="Pierre", last_name="VERGNE", sex="M")
    mother = dict(source_id="@I3@", first_name="Marie", last_name="ANGLADE", sex="F")
    return [
        Act(
            act_type="Naissance / Filiation GEDCOM",
            date="05 MAY 1840",
            location=_PLACE,
            confidence_score=1.0,
            source_text="Filiation de référence pour les tests.",
            source_type="GEDCOM_HEREDIS",
            family_id="@F1@",
            persons=[
                Person(
                    source_id="@I1@",
                    first_name="Jean",
                    last_name="VERGNE",
                    role="enfant",
                    sex="M",
                    birth_date="05 MAY 1840",
                    birth_place=_PLACE,
                ),
                Person(role="père", occupation="laboureur", birth_date="1810", **father),
                Person(role="mère", birth_date="1815", **mother),
            ],
        ),
        Act(
            act_type="Naissance / Filiation GEDCOM",
            date="12 JUN 1843",
            location=_PLACE,
            confidence_score=1.0,
            source_text="Second enfant du même couple.",
            source_type="GEDCOM_HEREDIS",
            family_id="@F1@",
            persons=[
                Person(
                    source_id="@I4@",
                    first_name="Anne",
                    last_name="VERGNE",
                    role="enfant",
                    sex="F",
                    birth_date="12 JUN 1843",
                ),
                Person(role="père", occupation="laboureur", **father),
                Person(role="mère", **mother),
            ],
        ),
    ]


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    """Base SQLite jetable propre à chaque test, peuplée en un seul commit."""
    db_path = tmp_path / "certus_test.db"
    test_db = DatabaseManager(f"sqlite:///{db_path.as_posix()}")
    test_db.init_db()

    with test_db.get_session() as session:
        ActRepository(session).save_acts(sample_acts())

    monkeypatch.setattr("src.api.main.db_manager", test_db)
    # Le cache d'arbre est un attribut de classe : sans purge, un test hérite de l'arbre
    # construit par le précédent.
    CertusOrchestrator.reset_tree_cache()
    # La simulation est refusée par défaut : les tests qui la veulent l'activent eux-mêmes.
    monkeypatch.delenv("CERTUS_ALLOW_SIMULATED", raising=False)
    monkeypatch.delenv("CERTUS_API_TOKEN", raising=False)

    yield test_db

    CertusOrchestrator.reset_tree_cache()
    test_db.engine.dispose()


@pytest.fixture
def api_token(monkeypatch):
    """Active l'authentification des endpoints mutants et retourne l'en-tête à utiliser."""
    monkeypatch.setenv("CERTUS_API_TOKEN", "jeton-de-test")
    return {"Authorization": "Bearer jeton-de-test"}


@pytest.fixture
def allow_simulation(monkeypatch):
    """Autorise explicitement les sources simulées pour la durée du test."""
    monkeypatch.setenv("CERTUS_ALLOW_SIMULATED", "1")


@pytest.fixture
def anyio_backend():
    return "asyncio"
