from typing import List, Dict, Optional
from pydantic import BaseModel, Field

class ConsolidatedPerson(BaseModel):
    id: str
    first_name: str
    last_name: str
    mentions: int = 1
    occupation: Optional[str] = None
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    death_date: Optional[str] = None
    death_place: Optional[str] = None

class Relationship(BaseModel):
    source_id: str
    target_id: str
    rel_type: str

class FamilyTree(BaseModel):
    nodes: Dict[str, ConsolidatedPerson] = Field(default_factory=dict)
    edges: List[Relationship] = Field(default_factory=list)