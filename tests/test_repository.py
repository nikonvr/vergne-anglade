import pytest
from src.core.models import Act, Person
from src.database.engine import DatabaseManager
from src.database.repository import ActRepository

def test_repository_save_and_get_all():
    db_manager = DatabaseManager("sqlite:///:memory:")
    db_manager.init_db()

    act = Act(
        act_type="Naissance",
        date="1855-01-01",
        location="Aurillac",
        persons=[
            Person(first_name="Jean", last_name="Vergne", role="Enfant", age=0)
        ],
        confidence_score=0.9,
        source_text="Acte de naissance de Jean Vergne",
    )

    with db_manager.get_session() as session:
        repo = ActRepository(session)
        act_id = repo.save_act(act)
        assert act_id > 0

    with db_manager.get_session() as session:
        repo = ActRepository(session)
        all_acts = repo.get_all_acts()
        assert len(all_acts) == 1
        assert all_acts[0].act_type == "Naissance"
        assert len(all_acts[0].persons) == 1
        assert all_acts[0].persons[0].first_name == "Jean"
