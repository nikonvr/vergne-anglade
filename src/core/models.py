from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

class Person(BaseModel):
    """Personne mentionnée dans un acte. Les champs d'état civil viennent du GEDCOM source
    (sous-tags GIVN / SURN / SEX / BIRT / DEAT) et ne doivent jamais être fabriqués."""
    source_id: Optional[str] = Field(None)      # identifiant externe stable, ex GEDCOM "@I3@"
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    role: str = Field(...)
    age: Optional[int] = Field(None)
    occupation: Optional[str] = Field(None)
    sex: Optional[str] = Field(None)            # "M" | "F" | None
    birth_date: Optional[str] = Field(None)     # chaîne GEDCOM brute, ex "21 FEB 1972"
    birth_place: Optional[str] = Field(None)    # chemin complet, ex "Aix-en-Provence,13100,...,FRANCE,"
    death_date: Optional[str] = Field(None)
    death_place: Optional[str] = Field(None)

class Act(BaseModel):
    """Acte (réel ou simulé). Toute donnée non sourcée DOIT porter is_simulated=True,
    un source_type préfixé "SIMULATED_" et des scores à 0.0 (politique anti-fabrication)."""
    id: Optional[int] = Field(None)             # clé primaire SQL, None si pas encore persisté
    act_type: str = Field(...)
    date: Optional[str] = Field(None)
    location: Optional[str] = Field(None)
    persons: List[Person] = Field(default_factory=list)
    confidence_score: float = Field(...)
    source_text: Optional[str] = Field(None)
    source_type: str = Field("GEDCOM_HEREDIS")
    url_source: Optional[str] = Field(None)
    reliability_score: float = Field(1.0)
    is_simulated: bool = Field(False)           # True = donnée non sourcée (démo/simulation)
    family_id: Optional[str] = Field(None)      # id stable de la famille, ex "@F108@"

class SearchQuery(BaseModel):
    # extra="forbid" : un kwarg inconnu (ex. surname= au lieu de last_name=) lève une erreur
    # au lieu d'être silencieusement ignoré.
    model_config = ConfigDict(extra="forbid")

    last_name: str = Field("VERGNE")
    first_name: Optional[str] = Field(None)
    location: Optional[str] = Field("Anglards-de-Salers")
    period_start: Optional[int] = Field(1800)
    period_end: Optional[int] = Field(1900)
