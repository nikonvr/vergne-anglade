import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("certus.database")
Base = declarative_base()

class DatabaseManager:
    def __init__(self, db_url: str = "sqlite:///certus_genealogy.db"):
        self.db_url = db_url
        self.engine = create_engine(self.db_url, echo=False, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def init_db(self):
        Base.metadata.create_all(bind=self.engine)

    def get_session(self):
        return self.SessionLocal()