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

    def export_mermaid(self, tree: FamilyTree, direction: str = "BT") -> str:
        """Génère la représentation graphique au format diagramme Mermaid v11 enrichi et coloré."""
        lines = [
            f"graph {direction}",
            "    %% Définition des couleurs pour identifier les régions d'origine",
            "    classDef cantal fill:#e8f4f8,stroke:#2b78e4,stroke-width:2px",
            "    classDef provence fill:#fcf4cd,stroke:#f6b26b,stroke-width:2px",
            "    classDef alpes fill:#e6eed5,stroke:#daa84f,stroke-width:2px",
            "    classDef defaut fill:#f1f5f9,stroke:#64748b,stroke-width:2px"
        ]
        
        id_map = {}
        for idx, (node_id, person) in enumerate(tree.nodes.items(), 1):
            safe_id = f"P{idx}"
            id_map[node_id] = safe_id
            
            fn = (person.first_name or "Inconnu").replace('"', '').replace("'", "")
            ln = (person.last_name or "Inconnu").replace('"', '').replace("'", "")
            
            b_date = getattr(person, "birth_date", "") or ""
            d_date = getattr(person, "death_date", "") or ""
            date_str = f"({b_date} - {d_date})" if (b_date or d_date) else ""
            
            place = getattr(person, "birth_place", "") or getattr(person, "death_place", "") or "Anglards-de-Salers"
            
            ln_upper = ln.upper()
            if any(k in ln_upper for k in ["VERGNE", "VERNHE", "ANGLADE", "BRUN"]):
                style_class = "cantal"
            elif any(k in ln_upper for k in ["JEHL", "IEHL"]):
                style_class = "provence"
            else:
                style_class = "defaut"

            subtext = f"<br/>{date_str}" if date_str else ""
            place_text = f"<br/><i>{place}</i>" if place else ""
            label = f"<b>{fn} {ln}</b>{subtext}{place_text}"
            
            lines.append(f'    {safe_id}["{label}"]:::{style_class}')

        for rel in tree.edges:
            src = id_map.get(rel.source_id)
            tgt = id_map.get(rel.target_id)
            if src and tgt:
                lines.append(f'    {src} --> {tgt}')

        return "\n".join(lines) + "\n"