from sqlalchemy import Boolean, Column, Integer, String, Float, ForeignKey, Text, Index, text
from sqlalchemy.orm import relationship
from src.database.base import Base

class DBAct(Base):
    __tablename__ = "acts"
    __table_args__ = (
        Index("idx_acts_type_date", "act_type", "date"),
        Index("idx_acts_family_id", "family_id"),
        Index("idx_acts_is_simulated", "is_simulated"),
    )
    id = Column(Integer, primary_key=True, index=True)
    act_type = Column(String(50), nullable=False)
    date = Column(String(20), nullable=True)
    location = Column(String(255), nullable=True)
    confidence_score = Column(Float, nullable=False)
    source_text = Column(Text, nullable=True)
    source_type = Column(String(50), default="GEDCOM_HEREDIS")
    url_source = Column(String(500), nullable=True)
    reliability_score = Column(Float, default=1.0)
    # True = donnée non sourcée (démo/simulation), jamais présentée comme vérifiée.
    # server_default=text("0") : littéral numérique (et non la chaîne '0', toujours vraie
    # côté Python) pour les lignes déjà présentes lors de la migration.
    is_simulated = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    # Identifiant stable de la famille GEDCOM, ex "@F108@".
    family_id = Column(String(50), nullable=True)
    # order_by : garantit un ordre de restitution déterministe (rôles enfant/père/mère).
    persons = relationship(
        "DBPerson",
        back_populates="act",
        cascade="all, delete-orphan",
        order_by="DBPerson.id",
    )

class DBPerson(Base):
    __tablename__ = "persons"
    __table_args__ = (
        Index("idx_persons_name", "last_name", "first_name"),
        Index("idx_persons_source_id", "source_id"),
    )
    id = Column(Integer, primary_key=True, index=True)
    act_id = Column(Integer, ForeignKey("acts.id"), nullable=False)
    # Identifiant stable de l'individu dans la source, ex GEDCOM "@I3@".
    source_id = Column(String(50), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    role = Column(String(50), nullable=False)
    age = Column(Integer, nullable=True)
    occupation = Column(String(100), nullable=True)
    sex = Column(String(1), nullable=True)
    # Dates GEDCOM brutes ("21 FEB 1972") et lieux en chemin complet à virgules.
    birth_date = Column(String(50), nullable=True)
    birth_place = Column(String(255), nullable=True)
    death_date = Column(String(50), nullable=True)
    death_place = Column(String(255), nullable=True)
    act = relationship("DBAct", back_populates="persons")
