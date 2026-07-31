import os
import pytest
from src.database.engine import DatabaseManager

TEST_DB_PATH = "test_certus_temp.db"

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Utilise un fichier SQLite temporaire isolé pour les tests, puis le supprime."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

    test_db = DatabaseManager(f"sqlite:///{TEST_DB_PATH}")
    try:
        test_db.init_db()
    except Exception:
        pass
    monkeypatch.setattr("src.api.main.db_manager", test_db)
    
    from src.api.main import seed_initial_data_if_empty
    seed_initial_data_if_empty()

    yield test_db
    test_db.engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
