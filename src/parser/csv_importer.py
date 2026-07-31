import csv
import logging
from pathlib import Path
from typing import List

from src.core.models import Act, Person
from src.genealogy.variants import is_branch_surname

class CsvImporter:
    """Importeur de fichiers CSV/Excel (relevés associatifs type APROGEMERE)."""
    
    def __init__(self, csv_path: Path | str, delimiter: str = ","):
        self.path = Path(csv_path)
        self.delimiter = delimiter

    def parse_acts(self, surname_filter: str = "VERGNE") -> List[Act]:
        if not self.path.exists():
            raise FileNotFoundError(f"Fichier CSV introuvable : {self.path}")

        acts: List[Act] = []
        logger = logging.getLogger("certus.parser.csv")

        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            for row in reader:
                norm_row = {k.lower().strip(): v.strip() for k, v in row.items() if k}
                
                first_name = norm_row.get("prenom") or norm_row.get("prénom") or norm_row.get("first_name") or ""
                last_name = norm_row.get("nom") or norm_row.get("last_name") or ""
                
                # Comparaison EXACTE via variants.py (R6). L'ancien filtre par sous-chaîne
                # ("VERGNE" in "LAVERGNE" → vrai) rattachait des individus étrangers au fonds.
                if surname_filter and not is_branch_surname(last_name):
                    continue

                act_type = norm_row.get("type") or norm_row.get("type_acte") or "Naissance"
                date = norm_row.get("date") or None
                location = norm_row.get("commune") or norm_row.get("lieu") or None
                occupation = norm_row.get("profession") or norm_row.get("metier") or None
                role = norm_row.get("role") or norm_row.get("rôle") or "principal"
                url_source = norm_row.get("url") or norm_row.get("source_url") or None

                persons = [
                    Person(
                        first_name=first_name or None,
                        last_name=last_name or None,
                        role=role,
                        occupation=occupation or None
                    )
                ]

                # Un relevé associatif n'a pas la fiabilité d'un acte notarié original :
                # les scores doivent refléter cette incertitude, pas afficher le maximum (R1).
                act = Act(
                    act_type=act_type,
                    date=date,
                    location=location,
                    confidence_score=0.7,
                    source_text=f"Relevé associatif CSV : {first_name} {last_name}",
                    source_type="CSV_APROGEMERE",
                    url_source=url_source,
                    reliability_score=0.6,
                    persons=persons
                )
                acts.append(act)

        return acts
