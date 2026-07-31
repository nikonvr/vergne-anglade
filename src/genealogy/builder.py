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

    @staticmethod
    def _normalize(name: Optional[str], default: str = "INCONNU") -> str:
        return name.strip().upper() if name else default

    def _generate_person_id(self, person) -> str:
        return f"{self._normalize(person.last_name)}_{self._normalize(person.first_name)}"

    def _get_block_key(self, fn: str, ln: str) -> str:
        return f"{self._normalize(fn, 'INC')[:3]}_{self._normalize(ln, 'INC')[:3]}"

    def _find_matching_person_id(self, tree: FamilyTree, index: Dict[str, List[str]], fn: str, ln: str) -> Optional[str]:
        target_fn = self._normalize(fn)
        target_ln = self._normalize(ln)
        block_key = self._get_block_key(fn, ln)
        
        for pid in index.get(block_key, []):
            existing = tree.nodes[pid]
            ex_fn = self._normalize(existing.first_name)
            ex_ln = self._normalize(existing.last_name)
            
            if ex_fn == target_fn:
                dist = _levenshtein(ex_ln, target_ln)
                max_allowed = max(2, int(len(target_ln) * 0.45))
                if ex_ln == target_ln or dist <= max_allowed:
                    return pid
        return None

    def _add_or_update_person(self, tree: FamilyTree, block_index: Dict[str, List[str]], pid: str, fn: str, ln: str, occupation: Optional[str]):
        if pid in tree.nodes:
            tree.nodes[pid].mentions += 1
            if occupation and not getattr(tree.nodes[pid], "occupation", None):
                tree.nodes[pid].occupation = occupation
        else:
            tree.nodes[pid] = ConsolidatedPerson(
                id=pid, first_name=fn, last_name=ln, mentions=1, occupation=occupation
            )
            block_index.setdefault(self._get_block_key(fn, ln), []).append(pid)

        if not self.graph.has_node(pid):
            self.graph.add_node(pid, first_name=fn, last_name=ln)

    def _link_parent_child(self, tree: FamilyTree, parents: List[str], child_pid: str, rel_type: str):
        for parent_pid in parents:
            if parent_pid != child_pid:
                rel = Relationship(source_id=parent_pid, target_id=child_pid, rel_type=rel_type)
                if rel not in tree.edges:
                    tree.edges.append(rel)
                self.graph.add_edge(parent_pid, child_pid, rel_type=rel_type)

    def _add_relationships(self, tree: FamilyTree, role_map: Dict[str, List[str]]):
        children = role_map.get("enfant", [])
        fathers = role_map.get("père", []) + role_map.get("father", [])
        mothers = role_map.get("mère", []) + role_map.get("mother", [])

        for child_pid in children:
            self._link_parent_child(tree, fathers, child_pid, "pere")
            self._link_parent_child(tree, mothers, child_pid, "mere")

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

                role_map.setdefault((person.role or "").lower(), []).append(pid)
                self._add_or_update_person(tree, block_index, pid, fn, ln, person.occupation)

            self._add_relationships(tree, role_map)

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