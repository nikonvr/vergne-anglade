from pydantic import BaseModel, Field
from typing import List, Optional

class Person(BaseModel):
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    role: str = Field(...)
    age: Optional[int] = Field(None)
    occupation: Optional[str] = Field(None)

class Act(BaseModel):
    act_type: str = Field(...)
    date: Optional[str] = Field(None)
    location: Optional[str] = Field(None)
    persons: List[Person] = Field(default_factory=list)
    confidence_score: float = Field(...)
    source_text: Optional[str] = Field(None)
    source_type: str = Field("OCR_CANTAL")
    url_source: Optional[str] = Field(None)
    reliability_score: float = Field(1.0)

class SearchQuery(BaseModel):
    last_name: str = Field("VERGNE")
    first_name: Optional[str] = Field(None)
    location: Optional[str] = Field("Anglards-de-Salers")
    period_start: Optional[int] = Field(1800)
    period_end: Optional[int] = Field(1900)