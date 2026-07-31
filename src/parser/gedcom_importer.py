import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from src.core.models import Act, Person
from src.genealogy.variants import (
    BRANCH_SURNAMES,
    NOT_BRANCH_SURNAMES,
    normalize_surname,
    same_surname_group,
)

logger = logging.getLogger("certus.parser.gedcom")

# La ligne "1 NAME" porte la forme "Prénoms/PATRONYME/". Sert de repli quand les sous-tags
# GIVN / SURN sont absents.
_NAME_RE = re.compile(r"^(.*?)/(.*?)/?$")

# Tags de niveau 1 introduisant un événement dont on lit la date et le lieu.
_EVENT_TAGS = ("BIRT", "DEAT")


class GedcomImporter:
    """Importeur de fichiers GEDCOM filtré sur les patronymes de la branche, avec filiations.

    Transporte l'intégralité de l'état civil disponible (identifiant stable, sexe, dates et
    lieux de naissance et de décès) : ces données sont indispensables à la désambiguïsation
    des homonymes et à la validité de l'export GEDCOM.
    """

    def __init__(self, gedcom_path: Path | str):
        self.path = Path(gedcom_path)
        # Nombre de lignes ignorées car malformées, exposé après parse_branch().
        self.malformed_lines = 0

    # ------------------------------------------------------------------ individus
    def _parse_indi_line(
        self, indi: dict, level: str, tag: str, rest: str, context: Optional[str]
    ) -> Optional[str]:
        """Applique une ligne à l'individu courant et retourne le nouveau contexte.

        Le contexte est le tag de niveau 1 en cours (NAME, BIRT, DEAT...), nécessaire pour
        interpréter les sous-tags de niveau 2.
        """
        if level == "1":
            if tag == "NAME":
                match = _NAME_RE.search(rest)
                if match:
                    indi["first_name"] = match.group(1).strip()
                    indi["last_name"] = match.group(2).strip()
                elif rest.strip():
                    indi["last_name"] = rest.strip()
            elif tag == "OCCU":
                indi["occupation"] = rest.strip()
            elif tag == "SEX":
                sex = rest.strip().upper()[:1]
                if sex in ("M", "F"):
                    indi["sex"] = sex
            elif tag == "FAMC":
                indi["famc"] = rest.strip()
            elif tag == "FAMS":
                indi["fams"].append(rest.strip())
            return tag

        if level == "2":
            if context == "NAME":
                # GIVN / SURN sont présents pour chaque individu du fonds et plus fiables
                # que le découpage de la ligne NAME : ils font autorité.
                if tag == "GIVN":
                    indi["first_name"] = rest.strip()
                elif tag == "SURN":
                    indi["last_name"] = rest.strip()
            elif context in _EVENT_TAGS:
                prefix = "birth" if context == "BIRT" else "death"
                if tag == "DATE":
                    indi[f"{prefix}_date"] = rest.strip()
                elif tag == "PLAC":
                    indi[f"{prefix}_place"] = rest.strip()
            # Les lignes de continuation CONT / CONC n'apparaissent que sous NOTE et SOUR,
            # que l'on ne lit pas : les ignorer ne peut pas corrompre de valeur.
        return context

    # ------------------------------------------------------------------ familles
    def _parse_fam_line(self, fam: dict, level: str, tag: str, rest: str) -> None:
        if level == "1":
            if tag == "HUSB":
                fam["husb"] = rest.strip()
            elif tag == "WIFE":
                fam["wife"] = rest.strip()
            elif tag == "CHIL":
                fam["children"].append(rest.strip())

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _new_indi(indi_id: str) -> dict:
        return {
            "id": indi_id,
            "first_name": "",
            "last_name": "",
            "occupation": "",
            "sex": "",
            "birth_date": "",
            "birth_place": "",
            "death_date": "",
            "death_place": "",
            "famc": None,
            "fams": [],
        }

    def _create_person(self, data: dict, role: str) -> Person:
        """Construit une Person en transportant tout l'état civil disponible.

        L'ancienne version ne recopiait que le nom, le prénom et la profession : les dates
        et les lieux lus dans le GEDCOM étaient perdus, ce qui laissait tous les individus
        sans date et rendait les homonymes indiscernables.
        """
        return Person(
            source_id=data.get("id") or None,
            first_name=data.get("first_name") or None,
            last_name=data.get("last_name") or None,
            role=role,
            occupation=data.get("occupation") or None,
            sex=data.get("sex") or None,
            birth_date=data.get("birth_date") or None,
            birth_place=data.get("birth_place") or None,
            death_date=data.get("death_date") or None,
            death_place=data.get("death_place") or None,
        )

    def _is_match(self, ln: str, surnames: List[str]) -> bool:
        """Indique si un patronyme appartient à la sélection demandée.

        Comparaison EXACTE, au groupe de variantes près. L'ancienne comparaison par
        SOUS-CHAÎNE rattachait à tort les patronymes seulement ressemblants : "VERGNE" in
        "LAVERGNE" était vrai, de même que BRUN pour BRUNET, BRUNEAU ou BRUNSTEIN.
        """
        if "*" in surnames:
            return True
        if normalize_surname(ln) in NOT_BRANCH_SURNAMES:
            return False
        return any(same_surname_group(ln, surname) for surname in surnames)

    # ------------------------------------------------------------------ actes
    def _build_filiation_acts(
        self, indis: Dict[str, dict], fams: Dict[str, dict], surnames: List[str]
    ) -> List[Act]:
        acts = []
        for fam_id, fam in fams.items():
            husb, wife = indis.get(fam["husb"]), indis.get(fam["wife"])
            for chil_id in fam["children"]:
                chil = indis.get(chil_id)
                if not chil:
                    continue

                if not (
                    self._is_match(chil.get("last_name", ""), surnames)
                    or (husb and self._is_match(husb.get("last_name", ""), surnames))
                    or (wife and self._is_match(wife.get("last_name", ""), surnames))
                ):
                    continue

                persons = [self._create_person(chil, "enfant")]
                if husb and husb.get("last_name"):
                    persons.append(self._create_person(husb, "père"))
                if wife and wife.get("last_name"):
                    persons.append(self._create_person(wife, "mère"))

                acts.append(
                    Act(
                        act_type="Naissance / Filiation GEDCOM",
                        date=chil["birth_date"] or chil["death_date"] or None,
                        location=chil["birth_place"] or chil["death_place"] or None,
                        confidence_score=1.0,
                        source_text=f"Filiation GEDCOM : {chil['first_name']} {chil['last_name']}".strip(),
                        source_type="GEDCOM_HEREDIS",
                        # family_id permet à l'export de regrouper le père et la mère d'un
                        # même enfant dans UNE seule famille au lieu de deux.
                        family_id=fam_id,
                        persons=persons,
                    )
                )
        return acts

    def _build_isolated_acts(self, indis: Dict[str, dict], surnames: List[str]) -> List[Act]:
        acts = []
        for data in indis.values():
            if self._is_match(data.get("last_name", ""), surnames):
                acts.append(
                    Act(
                        act_type="Acte GEDCOM",
                        date=data["birth_date"] or data["death_date"] or None,
                        location=data["birth_place"] or data["death_place"] or None,
                        confidence_score=1.0,
                        source_text=f"Import GEDCOM : {data['first_name']} {data['last_name']}".strip(),
                        source_type="GEDCOM_HEREDIS",
                        family_id=data.get("famc"),
                        persons=[self._create_person(data, "principal")],
                    )
                )
        return acts

    # ------------------------------------------------------------------ entrée
    def parse_branch(self, target_surnames: Optional[List[str]] = None) -> List[Act]:
        if not self.path.exists():
            raise FileNotFoundError(f"Fichier GEDCOM introuvable : {self.path}")

        surnames = (
            [s.upper() for s in target_surnames] if target_surnames else list(BRANCH_SURNAMES)
        )
        indis: Dict[str, dict] = {}
        fams: Dict[str, dict] = {}
        current_id, current_type, current_context = None, None, None
        self.malformed_lines = 0

        # utf-8-sig retire un éventuel BOM, qui sinon corrompait le premier tag.
        with open(self.path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue

                parts = line_str.split(" ", 2)
                if len(parts) < 2 or not parts[0].isdigit():
                    # Ligne malformée (niveau sans tag, ou niveau non numérique).
                    # L'ancienne version levait ici une IndexError qui interrompait
                    # l'import complet du fichier.
                    self.malformed_lines += 1
                    continue

                level, tag_or_id = parts[0], parts[1]
                rest = parts[2] if len(parts) > 2 else ""

                if level == "0":
                    current_context = None
                    if rest == "INDI":
                        current_id, current_type = tag_or_id, "INDI"
                        indis[current_id] = self._new_indi(current_id)
                    elif rest == "FAM":
                        current_id, current_type = tag_or_id, "FAM"
                        fams[current_id] = {"husb": None, "wife": None, "children": []}
                    else:
                        current_id, current_type = None, None

                elif current_type == "INDI" and current_id in indis:
                    current_context = self._parse_indi_line(
                        indis[current_id], level, tag_or_id, rest, current_context
                    )
                elif current_type == "FAM" and current_id in fams:
                    self._parse_fam_line(fams[current_id], level, tag_or_id, rest)

        if self.malformed_lines:
            logger.warning(
                "%d ligne(s) malformée(s) ignorée(s) dans %s",
                self.malformed_lines,
                self.path.name,
            )

        matching_acts = self._build_filiation_acts(indis, fams, surnames)
        matching_acts.extend(self._build_isolated_acts(indis, surnames))
        logger.info(
            "Import GEDCOM : %d individus lus, %d familles, %d actes retenus pour %s",
            len(indis),
            len(fams),
            len(matching_acts),
            ", ".join(surnames),
        )
        return matching_acts

    def parse_vergne_branch(self) -> List[Act]:
        """Alias de rétrocompatibilité : importe la branche définie dans variants.py."""
        return self.parse_branch(list(BRANCH_SURNAMES))
