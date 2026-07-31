import re
from pathlib import Path
from typing import List, Dict, Optional
from src.core.models import Act, Person

class GedcomImporter:
    """Importeur de fichiers GEDCOM filtré sur des branches patronymiques spécifiques avec filiations."""
    
    def __init__(self, gedcom_path: Path | str):
        self.path = Path(gedcom_path)

    def _parse_indi_line(self, indi: dict, level: str, tag: str, rest: str, event: Optional[str]) -> Optional[str]:
        if level == "1":
            if tag == "NAME":
                match = re.search(r"^(.*?)/(.*?)/?$", rest)
                if match:
                    indi["first_name"], indi["last_name"] = match.group(1).strip(), match.group(2).strip()
                else:
                    indi["last_name"] = rest.strip()
            elif tag == "OCCU":
                indi["occupation"] = rest.strip()
            return tag
        elif level == "2" and event in ("BIRT", "DEAT"):
            if tag == "DATE":
                indi[f"{'birth' if event == 'BIRT' else 'death'}_date"] = rest.strip()
            elif tag == "PLAC":
                indi[f"{'birth' if event == 'BIRT' else 'death'}_place"] = rest.strip()
        return event

    def _parse_fam_line(self, fam: dict, level: str, tag: str, rest: str):
        if level == "1":
            if tag == "HUSB":
                fam["husb"] = rest.strip()
            elif tag == "WIFE":
                fam["wife"] = rest.strip()
            elif tag == "CHIL":
                fam["children"].append(rest.strip())

    def _create_person(self, data: dict, role: str) -> Person:
        return Person(
            first_name=data.get("first_name") or None,
            last_name=data.get("last_name") or None,
            role=role,
            occupation=data.get("occupation") or None
        )

    def _is_match(self, ln: str, surnames: List[str]) -> bool:
        return "*" in surnames or any(s in (ln or "").upper() for s in surnames)

    def _build_filiation_acts(self, indis: Dict[str, dict], fams: Dict[str, dict], surnames: List[str]) -> List[Act]:
        acts = []
        for fam in fams.values():
            husb, wife = indis.get(fam["husb"]), indis.get(fam["wife"])
            for chil_id in fam["children"]:
                chil = indis.get(chil_id)
                if not chil: continue
                
                if not (self._is_match(chil.get("last_name", ""), surnames) or 
                        (husb and self._is_match(husb.get("last_name", ""), surnames)) or 
                        (wife and self._is_match(wife.get("last_name", ""), surnames))):
                    continue
                
                persons = [self._create_person(chil, "enfant")]
                if husb and husb.get("last_name"): persons.append(self._create_person(husb, "père"))
                if wife and wife.get("last_name"): persons.append(self._create_person(wife, "mère"))
                
                acts.append(Act(
                    act_type="Naissance / Filiation GEDCOM",
                    date=chil["birth_date"] or chil["death_date"] or None,
                    location=chil["birth_place"] or chil["death_place"] or None,
                    confidence_score=1.0,
                    source_text=f"Filiation GEDCOM : {chil['first_name']} {chil['last_name']}",
                    source_type="GEDCOM_HEREDIS",
                    persons=persons
                ))
        return acts

    def _build_isolated_acts(self, indis: Dict[str, dict], surnames: List[str]) -> List[Act]:
        acts = []
        for data in indis.values():
            if self._is_match(data.get("last_name", ""), surnames):
                acts.append(Act(
                    act_type="Acte GEDCOM",
                    date=data["birth_date"] or data["death_date"] or None,
                    location=data["birth_place"] or data["death_place"] or None,
                    confidence_score=1.0,
                    source_text=f"Import GEDCOM : {data['first_name']} {data['last_name']}",
                    source_type="GEDCOM_HEREDIS",
                    persons=[self._create_person(data, "principal")]
                ))
        return acts

    def parse_branch(self, target_surnames: Optional[List[str]] = None) -> List[Act]:
        if not self.path.exists():
            raise FileNotFoundError(f"Fichier GEDCOM introuvable : {self.path}")

        surnames = [s.upper() for s in target_surnames] if target_surnames else ["VERGNE", "VERNHE", "VERNHES", "ANGLADE", "BRUN"]
        indis, fams = {}, {}
        current_id, current_type, current_event = None, None, None

        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str: continue

                parts = line_str.split(" ", 2)
                level, tag_or_id = parts[0], parts[1]
                rest = parts[2] if len(parts) > 2 else ""

                if level == "0":
                    current_event = None
                    if rest == "INDI":
                        current_id, current_type = tag_or_id, "INDI"
                        indis[current_id] = {
                            "id": current_id, "first_name": "", "last_name": "",
                            "occupation": "", "birth_date": "", "birth_place": "",
                            "death_date": "", "death_place": ""
                        }
                    elif rest == "FAM":
                        current_id, current_type = tag_or_id, "FAM"
                        fams[current_id] = {"husb": None, "wife": None, "children": []}
                    else:
                        current_id, current_type = None, None

                elif current_type == "INDI" and current_id in indis:
                    current_event = self._parse_indi_line(indis[current_id], level, tag_or_id, rest, current_event)
                elif current_type == "FAM" and current_id in fams:
                    self._parse_fam_line(fams[current_id], level, tag_or_id, rest)

        matching_acts = self._build_filiation_acts(indis, fams, surnames)
        matching_acts.extend(self._build_isolated_acts(indis, surnames))
        return matching_acts

    def parse_vergne_branch(self) -> List[Act]:
        """Alias de rétrocompatibilité pour la branche VERGNE."""
        return self.parse_branch(["VERGNE", "VERNHE", "VERNHES", "ANGLADE", "BRUN"])
