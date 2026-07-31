import re
from pathlib import Path
from typing import List, Dict, Optional
from src.core.models import Act, Person

class GedcomImporter:
    """Importeur de fichiers GEDCOM filtré sur des branches patronymiques spécifiques."""
    
    def __init__(self, gedcom_path: Path | str):
        self.path = Path(gedcom_path)

    def parse_branch(self, target_surnames: Optional[List[str]] = None) -> List[Act]:
        if not self.path.exists():
            raise FileNotFoundError(f"Fichier GEDCOM introuvable : {self.path}")

        surnames = [s.upper() for s in target_surnames] if target_surnames else ["VERGNE", "VERNHE", "VERNHES", "ANGLADE", "BRUN"]

        # Lecture optimisée ligne par ligne du GEDCOM
        indis: Dict[str, dict] = {}
        current_indi = None
        current_event = None

        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue

                parts = line_str.split(" ", 2)
                level = parts[0]
                tag_or_id = parts[1]
                rest = parts[2] if len(parts) > 2 else ""

                if level == "0":
                    if rest == "INDI":
                        current_indi = tag_or_id
                        current_event = None
                        indis[current_indi] = {
                            "id": current_indi,
                            "first_name": "",
                            "last_name": "",
                            "occupation": "",
                            "birth_date": "",
                            "birth_place": "",
                            "death_date": "",
                            "death_place": ""
                        }
                    else:
                        current_indi = None
                        current_event = None

                elif current_indi and current_indi in indis:
                    if level == "1":
                        current_event = tag_or_id
                        if tag_or_id == "NAME":
                            match = re.search(r"^(.*?)/(.*?)/?$", rest)
                            if match:
                                indis[current_indi]["first_name"] = match.group(1).strip()
                                indis[current_indi]["last_name"] = match.group(2).strip()
                            else:
                                indis[current_indi]["last_name"] = rest.strip()
                        elif tag_or_id == "OCCU":
                            indis[current_indi]["occupation"] = rest.strip()

                    elif level == "2" and current_event in ("BIRT", "DEAT"):
                        if tag_or_id == "DATE":
                            key = "birth_date" if current_event == "BIRT" else "death_date"
                            indis[current_indi][key] = rest.strip()
                        elif tag_or_id == "PLAC":
                            key = "birth_place" if current_event == "BIRT" else "death_place"
                            indis[current_indi][key] = rest.strip()

        # Filtrage dynamique par patronymes
        matching_acts: List[Act] = []
        for indi_id, data in indis.items():
            ln_upper = data["last_name"].upper()
            is_match = any(s in ln_upper for s in surnames) if "*" not in surnames else True
            if is_match:
                act = Act(
                    act_type="Acte GEDCOM",
                    date=data["birth_date"] or data["death_date"] or None,
                    location=data["birth_place"] or data["death_place"] or None,
                    confidence_score=1.0,
                    source_text=f"Import GEDCOM : {data['first_name']} {data['last_name']}",
                    source_type="GEDCOM_HEREDIS",
                    persons=[
                        Person(
                            first_name=data["first_name"] or None,
                            last_name=data["last_name"] or None,
                            role="principal",
                            occupation=data["occupation"] or None
                        )
                    ]
                )
                matching_acts.append(act)

        return matching_acts

    def parse_vergne_branch(self) -> List[Act]:
        """Alias de rétrocompatibilité pour la branche VERGNE."""
        return self.parse_branch(["VERGNE", "VERNHE", "VERNHES"])
