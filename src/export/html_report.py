from pathlib import Path
from src.genealogy.models import FamilyTree

class HtmlReportExporter:
    """Générateur de rapport généalogique imprimable au format HTML."""
    
    def generate_html(self, tree: FamilyTree) -> str:
        html = [
            "<!DOCTYPE html>",
            "<html lang='fr'>",
            "<head>",
            "  <meta charset='utf-8'>",
            "  <title>CERTUS - Rapport Généalogique Famille VERGNE</title>",
            "  <style>",
            "    body { font-family: system-ui, -apple-system, sans-serif; margin: 40px; color: #1e293b; background: #f8fafc; }",
            "    h1 { color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }",
            "    .person-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }",
            "    .person-name { font-size: 1.1rem; font-weight: bold; color: #2563eb; }",
            "    .person-meta { font-size: 0.875rem; color: #64748b; margin-top: 4px; }",
            "  </style>",
            "</head>",
            "<body>",
            "  <h1>Rapport Généalogique Consolidé - CERTUS</h1>",
            f"  <p>Nombre total d'individus identifiés : <strong>{len(tree.nodes)}</strong></p>",
            "  <div class='person-list'>"
        ]

        for node_id, person in tree.nodes.items():
            html.append("    <div class='person-card'>")
            html.append(f"      <div class='person-name'>{person.first_name} {person.last_name}</div>")
            meta = f"Identifiant: {node_id} | Mentions dans les actes: {person.mentions}"
            if person.occupation:
                meta += f" | Profession: {person.occupation}"
            html.append(f"      <div class='person-meta'>{meta}</div>")
            html.append("    </div>")

        html.extend([
            "  </div>",
            "</body>",
            "</html>"
        ])
        return "\n".join(html)

    def export(self, tree: FamilyTree, output_path: str | Path) -> None:
        path = Path(output_path)
        content = self.generate_html(tree)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
