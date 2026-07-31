"""Déclaration centrale de la classe de base déclarative SQLAlchemy.

Isolé dans ce module pour rompre la dépendance circulaire entre
src.database.engine et src.database.models.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
