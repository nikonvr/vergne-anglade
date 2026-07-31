from pathlib import Path
from src.genealogy.models import FamilyTree

class GedcomExporter:
    def export_string(self, tree: FamilyTree) -> str:
        lines = ["0 HEAD", "1 SOUR CERTUS"]
        
        # 1. Enregistrements d'Individus (INDI)
        for node_id, person in tree.nodes.items():
            lines.append(f"0 @{node_id}@ INDI")
            lines.append(f"1 NAME {person.first_name} /{person.last_name}/")
            if person.birth_date or person.birth_place:
                lines.append("1 BIRT")
                if person.birth_date:
                    lines.append(f"2 DATE {person.birth_date}")
                if person.birth_place:
                    lines.append(f"2 PLAC {person.birth_place}")
            if person.death_date or person.death_place:
                lines.append("1 DEAT")
                if person.death_date:
                    lines.append(f"2 DATE {person.death_date}")
                if person.death_place:
                    lines.append(f"2 PLAC {person.death_place}")

        # 2. Enregistrements de Familles (FAM)
        fam_idx = 1
        for rel in tree.edges:
            lines.append(f"0 @F{fam_idx}@ FAM")
            if rel.rel_type in ("pere", "father", "husb"):
                lines.append(f"1 HUSB @{rel.source_id}@")
                lines.append(f"1 CHIL @{rel.target_id}@")
            elif rel.rel_type in ("mere", "mother", "wife"):
                lines.append(f"1 WIFE @{rel.source_id}@")
                lines.append(f"1 CHIL @{rel.target_id}@")
            else:
                lines.append(f"1 CHIL @{rel.target_id}@")
            fam_idx += 1

        lines.append("0 TRLR")
        return "\n".join(lines) + "\n"

    def export(self, tree: FamilyTree, output_path: str) -> None:
        path = Path(output_path)
        content = self.export_string(tree)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def export_mermaid(self, tree: FamilyTree) -> str:
        """Génère la représentation graphique au format diagramme Mermaid v11 valide."""
        lines = ["graph TD"]
        id_map = {}
        for idx, (node_id, person) in enumerate(tree.nodes.items(), 1):
            safe_id = f"P{idx}"
            id_map[node_id] = safe_id
            fn = (person.first_name or "Inconnu").replace('"', '').replace("'", "")
            ln = (person.last_name or "Inconnu").replace('"', '').replace("'", "")
            label = f"{fn} {ln}"
            lines.append(f'    {safe_id}["{label}"]')
        for rel in tree.edges:
            src = id_map.get(rel.source_id)
            tgt = id_map.get(rel.target_id)
            if src and tgt:
                lines.append(f'    {src} --> {tgt}')
        return "\n".join(lines) + "\n"