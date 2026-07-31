import html as html_module
from pathlib import Path
from typing import Optional

from src.genealogy.models import FamilyTree


class HtmlReportExporter:
    """Générateur de rapport généalogique imprimable au format HTML.

    Toute valeur issue des données est échappée : un patronyme contenant du balisage était
    auparavant interpolé tel quel dans le document.
    """

    @staticmethod
    def _esc(value: Optional[str]) -> str:
        return html_module.escape(str(value), quote=True) if value else ""

    @classmethod
    def _short_place(cls, place: Optional[str]) -> str:
        """Ne conserve que la commune d'un lieu GEDCOM "Ville,CP,Département,...,PAYS,"."""
        if not place:
            return ""
        return place.split(",")[0].strip()

    def generate_html(self, tree: FamilyTree) -> str:
        parts = [
            "<!DOCTYPE html>",
            "<html lang='fr'>",
            "<head>",
            "  <meta charset='utf-8'>",
            "  <title>CERTUS - Rapport généalogique consolidé</title>",
            "  <style>",
            "    body { font-family: system-ui, -apple-system, sans-serif; margin: 40px; color: #1e293b; background: #f8fafc; }",
            "    h1 { color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }",
            "    .person-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }",
            "    .person-name { font-size: 1.1rem; font-weight: bold; color: #2563eb; }",
            "    .person-meta { font-size: 0.875rem; color: #64748b; margin-top: 4px; }",
            "  </style>",
            "</head>",
            "<body>",
            "  <h1>Rapport généalogique consolidé - CERTUS</h1>",
            f"  <p>Nombre total d'individus identifiés : <strong>{len(tree.nodes)}</strong></p>",
            "  <div class='person-list'>",
        ]

        for node_id, person in tree.nodes.items():
            full_name = f"{self._esc(person.first_name)} {self._esc(person.last_name)}".strip()
            meta = [
                f"Identifiant : {self._esc(node_id)}",
                f"Mentions dans les actes : {person.mentions}",
            ]
            dates = " – ".join(
                filter(None, [self._esc(person.birth_date), self._esc(person.death_date)])
            )
            if dates:
                meta.append(f"Dates : {dates}")
            place = self._short_place(person.birth_place or person.death_place)
            if place:
                meta.append(f"Lieu : {self._esc(place)}")
            if person.occupation:
                meta.append(f"Profession : {self._esc(person.occupation)}")

            parts.append("    <div class='person-card'>")
            parts.append(f"      <div class='person-name'>{full_name}</div>")
            parts.append(f"      <div class='person-meta'>{' | '.join(meta)}</div>")
            parts.append("    </div>")

        parts.extend(["  </div>", "</body>", "</html>"])
        return "\n".join(parts)

    def export(self, tree: FamilyTree, output_path: str | Path) -> None:
        Path(output_path).write_text(self.generate_html(tree), encoding="utf-8")
