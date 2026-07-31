import logging
import os
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import Column, Table, create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex

import src.database.models  # noqa: F401 (enregistre les tables dans Base.metadata)
from src.database.base import Base

logger = logging.getLogger("certus.database")

# Noms figés (voir contrat des variables d'environnement).
ENV_DB_URL = "CERTUS_DB_URL"
DEFAULT_DB_URL = "sqlite:///certus_genealogy.db"


def resolve_db_url(db_url: Optional[str] = None) -> str:
    """URL SQLAlchemy effective : argument explicite, sinon CERTUS_DB_URL, sinon défaut."""
    if db_url:
        return db_url
    return os.environ.get(ENV_DB_URL, "").strip() or DEFAULT_DB_URL


def _sql_literal(value: Any) -> str:
    """Rend une valeur Python sous forme de littéral SQL pour une clause DEFAULT."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _column_default_sql(column: Column) -> Optional[str]:
    """Littéral SQL du DEFAULT d'une colonne, ou None si elle n'en a pas d'exploitable."""
    server_default = getattr(column, "server_default", None)
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        if arg is not None:
            return str(getattr(arg, "text", arg))
    default = getattr(column, "default", None)
    if default is not None and not getattr(default, "is_callable", False):
        return _sql_literal(getattr(default, "arg", None))
    return None


class DatabaseManager:
    """Gestion du moteur SQLAlchemy et de la migration légère du schéma."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = resolve_db_url(db_url)
        self.is_sqlite = self.db_url.startswith("sqlite")
        self.is_memory = self.is_sqlite and (":memory:" in self.db_url or "mode=memory" in self.db_url)

        engine_kwargs: Dict[str, Any] = {"echo": False}
        if self.is_sqlite:
            # check_same_thread : requis par FastAPI/TestClient qui change de thread.
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if self.is_memory:
                # Sans StaticPool, chaque connexion obtiendrait une base mémoire vide.
                engine_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(self.db_url, **engine_kwargs)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def init_db(self) -> None:
        """Crée les tables manquantes puis applique la migration légère (sans perte de données).

        create_all() n'ajoute AUCUNE colonne à une table déjà existante : la base de
        production a été créée avec l'ancien schéma, d'où _ensure_columns().
        """
        Base.metadata.create_all(bind=self.engine)
        self._ensure_columns()
        self._ensure_indexes()

    def get_session(self):
        return self.SessionLocal()

    # ------------------------------------------------------------------ migration légère

    def _existing_columns(self, conn, table_name: str) -> Set[str]:
        """Colonnes réellement présentes en base (PRAGMA table_info sous SQLite)."""
        if self.is_sqlite:
            rows = conn.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
            return {row[1] for row in rows}
        return {col["name"] for col in inspect(conn).get_columns(table_name)}

    def _add_column_ddl(self, table: Table, column: Column) -> str:
        """Construit l'ordre ALTER TABLE ... ADD COLUMN pour une colonne manquante."""
        type_sql = column.type.compile(dialect=self.engine.dialect)
        ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}'
        default_sql = _column_default_sql(column)
        if not column.nullable:
            if default_sql is None:
                # SQLite refuse d'ajouter une colonne NOT NULL sans DEFAULT à une table
                # peuplée : on l'ajoute nullable plutôt que d'échouer sur la migration.
                logger.warning(
                    "Colonne %s.%s NOT NULL sans DEFAULT : ajoutée nullable pour préserver "
                    "les données existantes.", table.name, column.name
                )
            else:
                ddl += " NOT NULL"
        if default_sql is not None:
            ddl += f" DEFAULT {default_sql}"
        return ddl

    def _ensure_columns(self) -> None:
        """Ajoute les colonnes déclarées dans les modèles et absentes de la base.

        Uniquement des ALTER TABLE ... ADD COLUMN : aucune donnée n'est jamais supprimée.
        """
        added: List[str] = []
        with self.engine.begin() as conn:
            table_names = set(inspect(conn).get_table_names())
            for table in Base.metadata.sorted_tables:
                if table.name not in table_names:
                    continue  # create_all() vient de la créer complète, ou base non SQL
                existing = self._existing_columns(conn, table.name)
                for column in table.columns:
                    if column.name in existing:
                        continue
                    ddl = self._add_column_ddl(table, column)
                    try:
                        conn.execute(text(ddl))
                    except OperationalError as exc:
                        if "duplicate column" in str(exc).lower():
                            logger.info("Colonne %s.%s déjà présente.", table.name, column.name)
                            continue
                        logger.error("Échec de la migration (%s) : %s", ddl, exc)
                        raise
                    added.append(f"{table.name}.{column.name}")
        if added:
            logger.info("Migration légère : colonnes ajoutées -> %s", ", ".join(added))

    def _ensure_indexes(self) -> None:
        """Crée les index déclarés dans les modèles et absents de la base.

        create_all() ignore les index d'une table préexistante : les index portant sur les
        colonnes fraîchement ajoutées doivent être créés explicitement.
        """
        created: List[str] = []
        with self.engine.begin() as conn:
            inspector = inspect(conn)
            table_names = set(inspector.get_table_names())
            for table in Base.metadata.sorted_tables:
                if table.name not in table_names:
                    continue
                existing = {ix.get("name") for ix in inspector.get_indexes(table.name)}
                for index in table.indexes:
                    if not index.name or index.name in existing:
                        continue
                    try:
                        conn.execute(CreateIndex(index, if_not_exists=True))
                    except OperationalError as exc:
                        logger.error("Échec de création de l'index %s : %s", index.name, exc)
                        raise
                    created.append(index.name)
        if created:
            logger.info("Migration légère : index créés -> %s", ", ".join(created))
