import datetime
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.genealogy.models import FamilyTree
from src.genealogy.variants import (
    DEFAULT_REGION_STYLE,
    REGION_STYLE_GROUPS,
    region_style_for_surname,
)

logger = logging.getLogger("certus.export.gedcom")

# Limite de longueur d'une ligne GEDCOM 5.5.1, continuation par CONC au-delà.
_MAX_LINE_LENGTH = 255

_ROLE_FATHER = ("pere", "père", "father", "husb")
_ROLE_MOTHER = ("mere", "mère", "mother", "wife")

# Caractères qui cassent un libellé Mermaid entre guillemets.
_MERMAID_UNSAFE_RE = re.compile(r'["\[\]{}|<>\\`]')


class GedcomExporter:
    """Génère un fichier GEDCOM 5.5.1 valide à partir d'un arbre consolidé."""

    SOURCE_NAME = "CERTUS"
    SOURCE_VERSION = "0.1.0"

    # ------------------------------------------------------------------ primitives
    @staticmethod
    def _clean(value: Optional[str]) -> str:
        """Neutralise les retours à la ligne, interdits dans une valeur GEDCOM."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    def _emit(self, lines: List[str], level: int, tag: str, value: Optional[str] = None) -> None:
        """Ajoute une ligne GEDCOM, découpée par CONC si elle dépasse la limite."""
        text = self._clean(value)
        prefix = f"{level} {tag}"
        if not text:
            lines.append(prefix)
            return

        budget = _MAX_LINE_LENGTH - len(prefix) - 1
        if budget <= 0:  # pragma: no cover - tag anormalement long
            lines.append(prefix)
            return

        lines.append(f"{prefix} {text[:budget]}")
        remainder = text[budget:]
        conc_prefix = f"{level + 1} CONC"
        conc_budget = max(1, _MAX_LINE_LENGTH - len(conc_prefix) - 1)
        while remainder:
            lines.append(f"{conc_prefix} {remainder[:conc_budget]}")
            remainder = remainder[conc_budget:]

    # ------------------------------------------------------------------ familles
    def _build_families(
        self, tree: FamilyTree
    ) -> Tuple[List[dict], Dict[str, str], Dict[str, List[str]]]:
        """Regroupe les filiations en familles : une famille par couple parental.

        L'ancienne version émettait un enregistrement FAM par arête, si bien que le père et
        la mère d'un même enfant se retrouvaient dans deux familles monoparentales
        distinctes — l'enfant apparaissait deux fois à l'import.

        Retourne les familles, l'index enfant -> famille (FAMC) et l'index parent -> familles
        (FAMS).
        """
        by_child: Dict[str, dict] = {}
        for rel in tree.edges:
            entry = by_child.setdefault(
                rel.target_id, {"father": None, "mother": None, "family_id": None}
            )
            rel_type = (rel.rel_type or "").lower()
            if rel_type in _ROLE_FATHER:
                entry["father"] = entry["father"] or rel.source_id
            elif rel_type in _ROLE_MOTHER:
                entry["mother"] = entry["mother"] or rel.source_id
            else:
                continue
            if rel.family_id and not entry["family_id"]:
                entry["family_id"] = rel.family_id

        grouped: Dict[object, dict] = {}
        for child_id, entry in by_child.items():
            # L'identifiant de famille de la source fait autorité ; à défaut on regroupe
            # sur le couple de parents.
            key = entry["family_id"] or ("COUPLE", entry["father"], entry["mother"])
            family = grouped.setdefault(
                key, {"husb": entry["father"], "wife": entry["mother"], "children": []}
            )
            family["husb"] = family["husb"] or entry["father"]
            family["wife"] = family["wife"] or entry["mother"]
            if child_id not in family["children"]:
                family["children"].append(child_id)

        families = list(grouped.values())
        famc: Dict[str, str] = {}
        fams: Dict[str, List[str]] = {}
        for idx, family in enumerate(families, 1):
            xref = f"F{idx}"
            for child_id in family["children"]:
                famc.setdefault(child_id, xref)
            for parent_id in (family["husb"], family["wife"]):
                if parent_id:
                    fams.setdefault(parent_id, [])
                    if xref not in fams[parent_id]:
                        fams[parent_id].append(xref)
        return families, famc, fams

    # ------------------------------------------------------------------ en-tête
    def _emit_header(self, lines: List[str], generated_on: Optional[str]) -> None:
        """En-tête conforme GEDCOM 5.5.1.

        L'ancien en-tête se réduisait à "0 HEAD / 1 SOUR CERTUS", sans GEDC, VERS ni CHAR :
        la plupart des logiciels de généalogie refusaient le fichier.
        """
        stamp = generated_on or datetime.date.today().strftime("%d %b %Y").upper()
        lines.append("0 HEAD")
        self._emit(lines, 1, "SOUR", self.SOURCE_NAME)
        self._emit(lines, 2, "VERS", self.SOURCE_VERSION)
        self._emit(lines, 2, "NAME", "CERTUS Genealogy")
        self._emit(lines, 1, "DATE", stamp)
        lines.append("1 GEDC")
        self._emit(lines, 2, "VERS", "5.5.1")
        self._emit(lines, 2, "FORM", "LINEAGE-LINKED")
        self._emit(lines, 1, "CHAR", "UTF-8")

    # ------------------------------------------------------------------ export
    def export_string(self, tree: FamilyTree, generated_on: Optional[str] = None) -> str:
        lines: List[str] = []
        self._emit_header(lines, generated_on)

        # Les identifiants de nœuds contiennent espaces et accents, interdits dans un xref :
        # on émet des références séquentielles et on conserve la correspondance.
        xrefs = {node_id: f"I{idx}" for idx, node_id in enumerate(tree.nodes, 1)}
        families, famc, fams = self._build_families(tree)

        for node_id, person in tree.nodes.items():
            xref = xrefs[node_id]
            first_name = self._clean(person.first_name)
            last_name = self._clean(person.last_name)

            lines.append(f"0 @{xref}@ INDI")
            self._emit(lines, 1, "NAME", f"{first_name} /{last_name}/".strip())
            if first_name:
                self._emit(lines, 2, "GIVN", first_name)
            if last_name:
                self._emit(lines, 2, "SURN", last_name)
            if person.sex in ("M", "F"):
                self._emit(lines, 1, "SEX", person.sex)
            if person.occupation:
                self._emit(lines, 1, "OCCU", person.occupation)

            for tag, date, place in (
                ("BIRT", person.birth_date, person.birth_place),
                ("DEAT", person.death_date, person.death_place),
            ):
                if date or place:
                    lines.append(f"1 {tag}")
                    if date:
                        self._emit(lines, 2, "DATE", date)
                    if place:
                        self._emit(lines, 2, "PLAC", place)

            # Liens de rattachement familial, totalement absents de l'ancien export.
            if node_id in famc:
                self._emit(lines, 1, "FAMC", f"@{famc[node_id]}@")
            for fam_xref in fams.get(node_id, []):
                self._emit(lines, 1, "FAMS", f"@{fam_xref}@")

        for idx, family in enumerate(families, 1):
            lines.append(f"0 @F{idx}@ FAM")
            if family["husb"] and family["husb"] in xrefs:
                self._emit(lines, 1, "HUSB", f"@{xrefs[family['husb']]}@")
            if family["wife"] and family["wife"] in xrefs:
                self._emit(lines, 1, "WIFE", f"@{xrefs[family['wife']]}@")
            for child_id in family["children"]:
                if child_id in xrefs:
                    self._emit(lines, 1, "CHIL", f"@{xrefs[child_id]}@")

        lines.append("0 TRLR")
        logger.info(
            "Export GEDCOM : %d individus, %d familles, %d lignes",
            len(tree.nodes),
            len(families),
            len(lines),
        )
        return "\n".join(lines) + "\n"

    def export(self, tree: FamilyTree, output_path: str) -> None:
        Path(output_path).write_text(self.export_string(tree), encoding="utf-8")

    # ------------------------------------------------------------------ Mermaid
    @staticmethod
    def _short_place(place: Optional[str]) -> str:
        """Ne garde que la commune d'un lieu GEDCOM "Ville,CP,Département,Région,PAYS,"."""
        if not place:
            return ""
        return place.split(",")[0].strip()

    @classmethod
    def _mermaid_safe(cls, value: Optional[str]) -> str:
        """Neutralise les caractères qui casseraient la syntaxe d'un libellé Mermaid."""
        if not value:
            return ""
        return _MERMAID_UNSAFE_RE.sub("", " ".join(str(value).split()))

    def export_mermaid(self, tree: FamilyTree, direction: str = "TD") -> str:
        """Génère le diagramme Mermaid v11, coloré par région d'origine du patronyme."""
        palette = {
            "cantal": "fill:#e8f4f8,stroke:#2b78e4,stroke-width:2px",
            "provence": "fill:#fcf4cd,stroke:#f6b26b,stroke-width:2px",
            DEFAULT_REGION_STYLE: "fill:#f1f5f9,stroke:#64748b,stroke-width:2px",
        }
        lines = [
            f"graph {direction}",
            "    %% Couleurs par région d'origine, définies dans src/genealogy/variants.py",
            "    classDef union fill:#fffbeb,stroke:#f59e0b,stroke-width:1.5px,rx:8,ry:8",
        ]
        for style_class in list(REGION_STYLE_GROUPS) + [DEFAULT_REGION_STYLE]:
            rule = palette.get(style_class, palette[DEFAULT_REGION_STYLE])
            lines.append(f"    classDef {style_class} {rule}")

        id_map = {}
        node_defs = {}
        for idx, (node_id, person) in enumerate(tree.nodes.items(), 1):
            safe_id = f"P{idx}"
            id_map[node_id] = safe_id

            first_name = self._mermaid_safe(person.first_name) or "Inconnu"
            last_name = self._mermaid_safe(person.last_name) or "Inconnu"

            birth = self._mermaid_safe(person.birth_date)
            death = self._mermaid_safe(person.death_date)
            dates = f"({birth} - {death})" if (birth or death) else ""
            place = self._mermaid_safe(
                self._short_place(person.birth_place or person.death_place)
            )

            # Prénom et nom sur deux lignes distinctes : un nom complet sur une seule ligne
            # dépasse souvent la largeur de la boîte et se fait tronquer par Mermaid
            # ("Françoise Jeanne Marie AN" au lieu de "...ANGLADE").
            label = f"<b>{first_name}</b><br/><b>{last_name}</b>"
            if dates:
                label += f"<br/>{dates}"
            if place:
                label += f"<br/><i>{place}</i>"

            style_class = region_style_for_surname(person.last_name)
            node_defs[node_id] = f'{safe_id}["{label}"]:::{style_class}'

        families, _, _ = self._build_families(tree)
        placed_nodes = set()

        for idx, family in enumerate(families, 1):
            fam_id = f"FAM{idx}"
            union_node = f'{fam_id}["💍 Union"]:::union'
            h, w = family["husb"], family["wife"]

            if h and w and h in id_map and w in id_map:
                s1, s2 = id_map[h], id_map[w]
                def1, def2 = node_defs.get(h), node_defs.get(w)

                lines.append(f'    subgraph SG_{fam_id} [" "]')
                lines.append('        direction LR')
                if def1 and h not in placed_nodes:
                    lines.append(f'        {def1}')
                    placed_nodes.add(h)
                lines.append(f'        {union_node}')
                if def2 and w not in placed_nodes:
                    lines.append(f'        {def2}')
                    placed_nodes.add(w)
                lines.append(f'        {s1} --- {fam_id} --- {s2}')
                lines.append('    end')
            elif h or w:
                p = h or w
                s_p = id_map.get(p)
                def_p = node_defs.get(p)
                if def_p and p not in placed_nodes:
                    lines.append(f'    {def_p}')
                    placed_nodes.add(p)
                lines.append(f'    {fam_id}["🏠"]:::union')
                if s_p:
                    lines.append(f'    {s_p} --> {fam_id}')

            for child_id in family["children"]:
                s_c = id_map.get(child_id)
                def_c = node_defs.get(child_id)
                if def_c and child_id not in placed_nodes:
                    lines.append(f'    {def_c}')
                    placed_nodes.add(child_id)
                if s_c:
                    lines.append(f'    {fam_id} --> {s_c}')

        for node_id in tree.nodes:
            if node_id not in placed_nodes:
                def_node = node_defs.get(node_id)
                if def_node:
                    lines.append(f'    {def_node}')

        return "\n".join(lines) + "\n"
