from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from src.database.engine import Base

class DBAct(Base):
    __tablename__ = "acts"
    __table_args__ = (
        Index("idx_acts_type_date", "act_type", "date"),
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
    persons = relationship("DBPerson", back_populates="act", cascade="all, delete-orphan")

class DBPerson(Base):
    __tablename__ = "persons"
    __table_args__ = (
        Index("idx_persons_name", "last_name", "first_name"),
    )
    id = Column(Integer, primary_key=True, index=True)
    act_id = Column(Integer, ForeignKey("acts.id"), nullable=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    role = Column(String(50), nullable=False)
    age = Column(Integer, nullable=True)
    occupation = Column(String(100), nullable=True)
    act = relationship("DBAct", back_populates="persons")