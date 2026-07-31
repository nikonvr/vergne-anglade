import logging
import re
from typing import Dict, List, Optional, Set

import networkx as nx

from src.core.models import Act
from src.genealogy.models import ConsolidatedPerson, FamilyTree, Relationship
from src.genealogy.variants import (
    NOT_BRANCH_SURNAMES,
    canonical_surname,
    normalize_surname,
)

logger = logging.getLogger("certus.genealogy.builder")

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

# Un identifiant de nœud doit rester utilisable comme référence GEDCOM et comme clé JSON.
_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_]+")
# Année sur 4 chiffres dans une date GEDCOM ("21 FEB 1972", "ABT 1830", "1793").
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")

# Seuils de la correspondance approchée, volontairement conservateurs (voir _surnames_match).
_FUZZY_MIN_LENGTH = 6
_FUZZY_MAX_DISTANCE = 1
_FUZZY_COMMON_PREFIX = 2

# Champs d'état civil recopiés de Person vers ConsolidatedPerson.
_CIVIL_FIELDS = ("sex", "birth_date", "birth_place", "death_date", "death_place")

# Rôles reconnus comme filiation directe, par type de lien.
_FATHER_ROLES = ("père", "pere", "father")
_MOTHER_ROLES = ("mère", "mere", "mother")
_CHILD_ROLES = ("enfant", "child")


class TreeBuilder:
    def __init__(self):
        self.graph = nx.DiGraph()

    # ------------------------------------------------------------------ identité
    @staticmethod
    def _normalize(name: Optional[str], default: str = "INCONNU") -> str:
        normalized = normalize_surname(name)
        return normalized if normalized else default

    @staticmethod
    def _year(*dates: Optional[str]) -> Optional[str]:
        """Retourne la première année trouvée dans les dates fournies."""
        for date in dates:
            if not date:
                continue
            match = _YEAR_RE.search(str(date))
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        return _ID_SAFE_RE.sub("", str(raw)) or "INCONNU"

    def _generate_person_id(self, person) -> str:
        """Construit un identifiant d'individu STABLE et non ambigu.

        Par ordre de priorité :
          1. l'identifiant de la source (GEDCOM @I3@) : identité faisant autorité, deux
             individus distincts de la source ne peuvent jamais être confondus ;
          2. sinon PATRONYME_PRÉNOM_ANNÉE, l'année départageant les homonymes ;
          3. sinon PATRONYME_PRÉNOM (dernier recours, sans désambiguïsation possible).

        L'ancienne version se limitait au cas 3, ce qui fusionnait en un seul nœud tous les
        homonymes d'une lignée — jusqu'à sept personnes différentes portant le même nom —
        et créait des cycles où un individu devenait son propre ancêtre.
        Le patronyme est ramené à sa forme canonique pour que les variantes attestées
        (VERGNE / VERGNES) partagent la même identité.
        """
        if getattr(person, "source_id", None):
            return self._sanitize_id(person.source_id)

        surname = canonical_surname(person.last_name) or "INCONNU"
        first_name = self._normalize(person.first_name)
        year = self._year(
            getattr(person, "birth_date", None), getattr(person, "death_date", None)
        )
        base = f"{surname}_{first_name}"
        return self._sanitize_id(f"{base}_{year}" if year else base)

    # ---------------------------------------------------- correspondance approchée
    def _get_block_key(self, fn: str, ln: str) -> str:
        """Clé de regroupement des candidats à la fusion.

        Seul le prénom sert de clé : il doit de toute façon être identique pour qu'une
        fusion soit envisagée, donc ce regroupement ne peut écarter aucun candidat.
        L'ancienne clé incluait les trois premières lettres du patronyme, ce qui empêchait
        définitivement la fusion des variantes différant par leur initiale (JEHL / IEHL).
        """
        return self._normalize(fn, "INC")

    @staticmethod
    def _surnames_match(a: str, b: str) -> bool:
        """Indique si deux patronymes peuvent désigner la même personne.

        Règle conservatrice : égalité stricte, ou variante attestée (traitée en amont par la
        forme canonique), ou faute de frappe sur un nom long. L'ancien seuil
        max(2, 45 % de la longueur) fusionnait à tort des familles distinctes
        (paires en ...AT / ...ET, patronyme court et son dérivé en -ET).
        """
        na, nb = normalize_surname(a), normalize_surname(b)
        if not na or not nb:
            return False
        if na == nb:
            return True
        # Règle métier : un patronyme exclu n'est jamais assimilé à un autre.
        if na in NOT_BRANCH_SURNAMES or nb in NOT_BRANCH_SURNAMES:
            return False
        if canonical_surname(na) == canonical_surname(nb):
            return True
        if min(len(na), len(nb)) < _FUZZY_MIN_LENGTH:
            return False
        if na[:_FUZZY_COMMON_PREFIX] != nb[:_FUZZY_COMMON_PREFIX]:
            return False
        return _levenshtein(na, nb) <= _FUZZY_MAX_DISTANCE

    def _find_matching_person_id(
        self, tree: FamilyTree, index: Dict[str, List[str]], person
    ) -> Optional[str]:
        """Cherche un individu déjà connu correspondant à celui-ci.

        La correspondance approchée ne s'applique QU'AUX individus dépourvus
        d'identifiant de source : quand la source fournit une identité, elle fait foi.
        """
        if getattr(person, "source_id", None):
            return None

        target_fn = self._normalize(person.first_name)
        target_ln = person.last_name
        target_year = self._year(
            getattr(person, "birth_date", None), getattr(person, "death_date", None)
        )
        for pid in index.get(self._get_block_key(person.first_name, person.last_name), []):
            existing = tree.nodes[pid]
            if existing.source_id:
                continue
            if self._normalize(existing.first_name) != target_fn:
                continue
            if not self._surnames_match(existing.last_name, target_ln):
                continue
            # Deux années connues et différentes désignent deux personnes différentes.
            # Sans cette vérification, la correspondance approchée annulait le discriminant
            # de la clé composite et refusionnait les homonymes qu'elle sert à séparer.
            existing_year = self._year(existing.birth_date, existing.death_date)
            if target_year and existing_year and target_year != existing_year:
                continue
            return pid
        return None

    # ------------------------------------------------------------------ noeuds
    def _add_or_update_person(
        self, tree: FamilyTree, block_index: Dict[str, List[str]], pid: str, person
    ) -> None:
        fn = person.first_name or "Inconnu"
        ln = person.last_name or "Inconnu"

        if pid in tree.nodes:
            node = tree.nodes[pid]
            node.mentions += 1
            if person.occupation and not node.occupation:
                node.occupation = person.occupation
        else:
            node = ConsolidatedPerson(
                id=pid,
                source_id=getattr(person, "source_id", None),
                first_name=fn,
                last_name=ln,
                mentions=1,
                occupation=person.occupation,
            )
            tree.nodes[pid] = node
            block_index.setdefault(
                self._get_block_key(person.first_name, person.last_name), []
            ).append(pid)

        # État civil : la première valeur connue gagne, on n'écrase jamais par un vide.
        for field in _CIVIL_FIELDS:
            value = getattr(person, field, None)
            if value and not getattr(node, field, None):
                setattr(node, field, value)

        if not self.graph.has_node(pid):
            self.graph.add_node(pid, first_name=fn, last_name=ln)

    # ------------------------------------------------------------------ liens
    def _link_parent_child(
        self,
        tree: FamilyTree,
        parents: List[str],
        child_pid: str,
        rel_type: str,
        family_id: Optional[str],
    ) -> None:
        for parent_pid in parents:
            if parent_pid == child_pid:
                # Auto-filiation : symptôme d'une identité mal résolue, à rendre visible.
                logger.warning(
                    "Filiation ignorée : %s serait son propre parent (%s)", child_pid, rel_type
                )
                continue
            rel = Relationship(
                source_id=parent_pid,
                target_id=child_pid,
                rel_type=rel_type,
                family_id=family_id,
            )
            if rel not in tree.edges:
                tree.edges.append(rel)
            self.graph.add_edge(parent_pid, child_pid, rel_type=rel_type, family_id=family_id)

    def _add_relationships(
        self, tree: FamilyTree, role_map: Dict[str, List[str]], family_id: Optional[str]
    ) -> None:
        children: List[str] = []
        fathers: List[str] = []
        mothers: List[str] = []
        for role, pids in role_map.items():
            if role in _CHILD_ROLES:
                children.extend(pids)
            elif role in _FATHER_ROLES:
                fathers.extend(pids)
            elif role in _MOTHER_ROLES:
                mothers.extend(pids)

        for child_pid in children:
            self._link_parent_child(tree, fathers, child_pid, "pere", family_id)
            self._link_parent_child(tree, mothers, child_pid, "mere", family_id)

    # ------------------------------------------------------------------ pipeline
    def process_acts(self, acts: List[Act]) -> FamilyTree:
        tree = FamilyTree()
        block_index: Dict[str, List[str]] = {}

        for act in acts:
            role_map: Dict[str, List[str]] = {}

            for person in act.persons:
                matched_id = self._find_matching_person_id(tree, block_index, person)
                pid = matched_id if matched_id else self._generate_person_id(person)

                role_map.setdefault((person.role or "").lower(), []).append(pid)
                self._add_or_update_person(tree, block_index, pid, person)

            self._add_relationships(tree, role_map, act.family_id)

        return tree

    # ------------------------------------------------------------------ analyse
    def _filiation_dag(self) -> nx.DiGraph:
        """Sous-graphe orienté restreint aux arêtes de filiation directe."""
        dag = nx.DiGraph()
        for u, v, data in self.graph.edges(data=True):
            rel_type = (data.get("rel_type") or "").lower()
            if rel_type in ("pere", "mere", "parent", "father", "mother", "parent_of", ""):
                dag.add_edge(u, v)
        return dag

    def detect_cycles(self, limit: int = 5) -> List[List[str]]:
        """Retourne au plus `limit` cycles de filiation détectés (liste vide si sain)."""
        dag = self._filiation_dag()
        cycles: List[List[str]] = []
        try:
            for cycle in nx.simple_cycles(dag):
                cycles.append(cycle)
                if len(cycles) >= limit:
                    break
        except Exception as exc:  # pragma: no cover - dépend de la version networkx
            logger.error("Détection de cycles impossible : %s", exc)
        return cycles

    def validate(self) -> dict:
        """Rapport de cohérence du graphe, exploitable en test de non-régression."""
        cycles = self.detect_cycles()
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "is_acyclic": not cycles,
            "cycles": cycles,
        }

    def find_common_ancestor(self, p1_id: str, p2_id: str) -> Optional[str]:
        """Retourne le plus proche ancêtre commun de deux individus, ou None.

        Le calcul exige un graphe acyclique. Si des cycles existent, ils traduisent une
        erreur d'identification des individus : on la journalise explicitement au lieu de
        renvoyer None silencieusement, ce qui masquait le défaut.
        """
        if not self.graph.has_node(p1_id) or not self.graph.has_node(p2_id):
            return None

        dag = self._filiation_dag()
        if not dag.has_node(p1_id) or not dag.has_node(p2_id):
            return None

        if not nx.is_directed_acyclic_graph(dag):
            logger.error(
                "Graphe de filiation cyclique : calcul d'ancêtre commun impossible. "
                "Cycles détectés (max 5) : %s",
                self.detect_cycles(),
            )
            return None

        try:
            return nx.lowest_common_ancestor(dag, p1_id, p2_id)
        except nx.NetworkXError as exc:
            logger.warning("Ancêtre commun indéterminé entre %s et %s : %s", p1_id, p2_id, exc)
            return None

    def get_relationship_path(self, p1_id: str, p2_id: str) -> List[str]:
        """Retourne le chemin le plus court reliant deux individus, ou une liste vide."""
        if not self.graph.has_node(p1_id) or not self.graph.has_node(p2_id):
            return []
        try:
            return nx.shortest_path(self.graph.to_undirected(), source=p1_id, target=p2_id)
        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []

    # ------------------------------------------------------------------ sous-arbres
    def subtree_ids(self, root_id: str, up: int = 3, down: int = 3, include_siblings: bool = True) -> Set[str]:
        """Identifiants du sous-arbre centré sur `root_id` (racine incluse).

        Remonte au plus `up` générations par les arêtes de filiation ENTRANTES (parents)
        et descend au plus `down` générations par les arêtes SORTANTES (enfants). Si
        include_siblings est True, inclut également la fratrie à chaque niveau d'ascendance.
        """
        if not self.graph.has_node(root_id):
            return set()

        ids: Set[str] = {root_id}
        dag = self._filiation_dag()
        if not dag.has_node(root_id):
            return ids

        frontier = {root_id}
        for _ in range(max(0, up)):
            frontier = {parent for node in frontier for parent in dag.predecessors(node)}
            if not frontier:
                break
            ids |= frontier
            if include_siblings:
                siblings = {child for parent in frontier for child in dag.successors(parent)}
                ids |= siblings

        frontier = {root_id}
        for _ in range(max(0, down)):
            frontier = {child for node in frontier for child in dag.successors(node)}
            if not frontier:
                break
            ids |= frontier

        return ids

    def subtree(
        self, tree: FamilyTree, root_id: str, up: int = 3, down: int = 3, include_siblings: bool = True
    ) -> FamilyTree:
        """Restreint un arbre déjà construit au sous-arbre centré sur `root_id`.

        `tree` doit provenir de `process_acts()` sur CE builder : le filtrage s'appuie sur
        `self.graph`, qui n'existe que sur l'instance ayant construit l'arbre (voir le piège
        du cache d'arbre décrit dans AGENTS.md — le graphe networkx vit sur l'instance, pas
        sur le FamilyTree lui-même).
        """
        keep = self.subtree_ids(root_id, up=up, down=down)
        nodes = {nid: person for nid, person in tree.nodes.items() if nid in keep}
        edges = [
            rel for rel in tree.edges if rel.source_id in keep and rel.target_id in keep
        ]
        return FamilyTree(nodes=nodes, edges=edges)
