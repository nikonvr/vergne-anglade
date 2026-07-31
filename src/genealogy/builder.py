import networkx as nx
from typing import List, Dict, Optional
from src.core.models import Act
from src.genealogy.models import ConsolidatedPerson, Relationship, FamilyTree

try:
    from rapidfuzz.distance.Levenshtein import distance as _levenshtein_fast
    def _levenshtein(s1: str, s2: str) -> int:
        return _levenshtein_fast(s1, s2)
except ImportError:
    def _levenshtein(s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return _levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

class TreeBuilder:
    def __init__(self):
        self.graph = nx.DiGraph()
        
    def _generate_person_id(self, person) -> str:
        fn = person.first_name.upper() if person.first_name else "INCONNU"
        ln = person.last_name.upper() if person.last_name else "INCONNU"
        return f"{ln}_{fn}"

    def _get_block_key(self, fn: str, ln: str) -> str:
        fn_part = fn.strip().upper()[:3] if fn else "INC"
        ln_part = ln.strip().upper()[:3] if ln else "INC"
        return f"{fn_part}_{ln_part}"

    def _find_matching_person_id(self, tree: FamilyTree, index: Dict[str, List[str]], fn: str, ln: str) -> Optional[str]:
        target_fn = fn.upper()
        target_ln = ln.upper()
        block_key = self._get_block_key(fn, ln)
        candidate_ids = index.get(block_key, [])

        for pid in candidate_ids:
            existing = tree.nodes[pid]
            ex_fn = existing.first_name.upper()
            ex_ln = existing.last_name.upper()
            if ex_fn == target_fn:
                dist = _levenshtein(ex_ln, target_ln)
                max_allowed = max(2, int(len(target_ln) * 0.45))
                if ex_ln == target_ln or dist <= max_allowed:
                    return pid
        return None

    def process_acts(self, acts: List[Act]) -> FamilyTree:
        tree = FamilyTree()
        block_index: Dict[str, List[str]] = {}

        for act in acts:
            role_map: Dict[str, List[str]] = {}
            for person in act.persons:
                fn = person.first_name or "Inconnu"
                ln = person.last_name or "Inconnu"
                matched_id = self._find_matching_person_id(tree, block_index, fn, ln)
                pid = matched_id if matched_id else self._generate_person_id(person)

                role = (person.role or "").lower()
                if role not in role_map:
                    role_map[role] = []
                role_map[role].append(pid)

                if pid in tree.nodes:
                    tree.nodes[pid].mentions += 1
                    if person.occupation and not getattr(tree.nodes[pid], "occupation", None):
                        tree.nodes[pid].occupation = person.occupation
                else:
                    tree.nodes[pid] = ConsolidatedPerson(
                        id=pid,
                        first_name=fn,
                        last_name=ln,
                        mentions=1,
                        occupation=person.occupation
                    )
                    block_key = self._get_block_key(fn, ln)
                    if block_key not in block_index:
                        block_index[block_key] = []
                    block_index[block_key].append(pid)

                if not self.graph.has_node(pid):
                    self.graph.add_node(pid, first_name=fn, last_name=ln)

            # Création des arêtes de filiation (parent -> enfant)
            children = role_map.get("enfant", [])
            fathers = role_map.get("père", []) + role_map.get("father", [])
            mothers = role_map.get("mère", []) + role_map.get("mother", [])

            for child_pid in children:
                for dad_pid in fathers:
                    if dad_pid != child_pid:
                        rel = Relationship(source_id=dad_pid, target_id=child_pid, rel_type="pere")
                        if rel not in tree.edges:
                            tree.edges.append(rel)
                        self.graph.add_edge(dad_pid, child_pid, rel_type="pere")
                for mom_pid in mothers:
                    if mom_pid != child_pid:
                        rel = Relationship(source_id=mom_pid, target_id=child_pid, rel_type="mere")
                        if rel not in tree.edges:
                            tree.edges.append(rel)
                        self.graph.add_edge(mom_pid, child_pid, rel_type="mere")

        return tree

    def find_common_ancestor(self, p1_id: str, p2_id: str) -> Optional[str]:
        """
        Trouve le plus proche ancêtre commun en créant un sous-graphe orienté (DAG)
        filtré uniquement sur les arêtes de filiation directes (Parent -> Enfant).
        """
        if not self.graph.has_node(p1_id) or not self.graph.has_node(p2_id):
            return None

        # Filtrage des arêtes orientées parent -> enfant pour garantir un DAG
        dag = nx.DiGraph()
        for u, v, data in self.graph.edges(data=True):
            rel_type = (data.get("rel_type") or "").lower()
            if rel_type in ("pere", "mere", "parent", "father", "mother", "parent_of", ""):
                dag.add_edge(u, v)

        if not dag.has_node(p1_id) or not dag.has_node(p2_id):
            return None

        try:
            if nx.is_directed_acyclic_graph(dag):
                return nx.lowest_common_ancestor(dag, p1_id, p2_id)
        except Exception:
            pass
        return None

    def get_relationship_path(self, p1_id: str, p2_id: str) -> List[str]:
        """Retourne le chemin le plus court liant deux individus dans le graphe généalogique."""
        if not self.graph.has_node(p1_id) or not self.graph.has_node(p2_id):
            return []
        try:
            undirected = self.graph.to_undirected()
            return nx.shortest_path(undirected, source=p1_id, target=p2_id)
        except Exception:
            return []