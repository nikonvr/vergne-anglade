"""Source unique de vérité des patronymes de la branche et de leurs variantes.

Ce module remplace les listes de patronymes dupliquées dans le projet :
  - src/parser/gedcom_importer.py (défaut de parse_branch, parse_vergne_branch)
  - scripts/build_standalone.py (liste passée à parse_branch)
  - src/export/gedcom.py (classement couleur de export_mermaid)

Toute modification de la branche étudiée se fait ICI et nulle part ailleurs.
"""

import unicodedata
from typing import Dict, List, Optional, Set

# --------------------------------------------------------------------------------------
# Patronymes filtrés à l'import GEDCOM (union historique des listes dupliquées).
# Cette liste produit les 334 actes de la base de référence.
# --------------------------------------------------------------------------------------
BRANCH_SURNAMES: List[str] = [
    "VERGNE",
    "VERGNES",
    "VERNHE",
    "VERNHES",
    "ANGLADE",
    "BRUN",
    "JEHL",
    "IEHL",
]

# --------------------------------------------------------------------------------------
# RÈGLE MÉTIER (confirmée par le propriétaire du projet) — NE PAS REVENIR EN ARRIÈRE.
#
# Ces patronymes ne sont PAS des variantes de la branche : ce sont des familles
# distinctes, malgré leur ressemblance graphique. Ils doivent rester hors de la
# généalogie et ne jamais être fusionnés avec un patronyme de la branche.
#
# Ils étaient auparavant captés à tort par GedcomImporter._is_match, qui comparait
# par SOUS-CHAÎNE ("VERGNE" in "LAVERGNE" -> vrai). Mesure sur le fonds de référence :
# le filtre par sous-chaîne retenait 150 individus au lieu de 135, soit 15 faux
# positifs (LAVERGNE ×5, BRUNET DEBAINES ×3, ANSELMET DES BRUNAUX ×2, BRUNSTEIN ×2,
# BRUNEAU, BRUNET, STEINBRUNN).
# --------------------------------------------------------------------------------------
NOT_BRANCH_SURNAMES: Set[str] = {
    "LAVERGNE",
    "LEVERGNE",
}

# --------------------------------------------------------------------------------------
# Groupes de patronymes considérés comme équivalents (variantes orthographiques attestées
# dans les actes et les relevés du fonds familial). Sert à la désambiguïsation des
# homonymes : deux patronymes du même groupe désignent la même lignée.
# --------------------------------------------------------------------------------------
SURNAME_VARIANT_GROUPS: List[Set[str]] = [
    {"VERGNE", "VERGNES", "VERNHE", "VERNHES"},
    {"JEHL", "IEHL"},
    {"LASCOMBE", "LASCOMBES"},
]

# --------------------------------------------------------------------------------------
# Classes CSS Mermaid -> patronymes, pour le coloriage par région d'origine.
# Les patronymes absents de ce mapping reçoivent DEFAULT_REGION_STYLE.
# --------------------------------------------------------------------------------------
REGION_STYLE_GROUPS: Dict[str, List[str]] = {
    "cantal": ["VERGNE", "VERGNES", "VERNHE", "VERNHES", "ANGLADE", "BRUN"],
    "provence": ["JEHL", "IEHL"],
}

# Classe CSS de repli pour tout patronyme hors REGION_STYLE_GROUPS.
DEFAULT_REGION_STYLE: str = "defaut"


def normalize_surname(s: Optional[str]) -> str:
    """Normalise un patronyme : majuscules, accents retirés, espaces normalisés.

    Retourne une chaîne vide si l'entrée est vide ou None.
    """
    if not s:
        return ""
    # NFKD sépare les diacritiques, on ne garde que les caractères non combinants.
    decomposed = unicodedata.normalize("NFKD", str(s))
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.upper().split())


# Index normalisé patronyme -> indice de groupe, construit une seule fois.
_VARIANT_INDEX: Dict[str, int] = {}
for _group_idx, _group in enumerate(SURNAME_VARIANT_GROUPS):
    for _name in _group:
        _VARIANT_INDEX[normalize_surname(_name)] = _group_idx

# Index normalisé patronyme -> classe CSS, construit une seule fois.
_STYLE_INDEX: Dict[str, str] = {}
for _style_class, _names in REGION_STYLE_GROUPS.items():
    for _name in _names:
        _STYLE_INDEX[normalize_surname(_name)] = _style_class


def same_surname_group(a: Optional[str], b: Optional[str]) -> bool:
    """Indique si deux patronymes désignent la même lignée.

    True si les patronymes normalisés sont identiques, ou s'ils appartiennent au même
    groupe de variantes attestées. Deux patronymes inconnus et différents -> False.
    """
    na, nb = normalize_surname(a), normalize_surname(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Règle métier : un patronyme exclu n'est équivalent qu'à lui-même. Ce garde-fou rend
    # impossible la fusion LAVERGNE/VERGNE même si un groupe de variantes était mal édité.
    if na in NOT_BRANCH_SURNAMES or nb in NOT_BRANCH_SURNAMES:
        return False
    group_a = _VARIANT_INDEX.get(na)
    return group_a is not None and group_a == _VARIANT_INDEX.get(nb)


def surname_group(s: Optional[str]) -> Optional[Set[str]]:
    """Retourne le groupe de variantes contenant ce patronyme, ou None."""
    idx = _VARIANT_INDEX.get(normalize_surname(s))
    return SURNAME_VARIANT_GROUPS[idx] if idx is not None else None


def canonical_surname(s: Optional[str]) -> str:
    """Retourne la forme canonique d'un patronyme (premier élément trié de son groupe).

    Permet de bâtir des identités stables : VERNHES et VERGNE renvoient la même clé.
    """
    normalized = normalize_surname(s)
    idx = _VARIANT_INDEX.get(normalized)
    if idx is None:
        return normalized
    return sorted(normalize_surname(n) for n in SURNAME_VARIANT_GROUPS[idx])[0]


def is_branch_surname(s: Optional[str]) -> bool:
    """Indique si le patronyme appartient à la branche étudiée (variantes incluses).

    Comparaison EXACTE, au groupe de variantes près : VERGNES est accepté (variante de
    VERGNE), mais BRUNET, LANGLADE ou LAVERGNE sont rejetés. C'est le filtre de référence
    pour l'import ; il remplace l'ancienne comparaison par sous-chaîne, qui rattachait
    15 individus à tort au fonds (voir NOT_BRANCH_SURNAMES).
    """
    if normalize_surname(s) in NOT_BRANCH_SURNAMES:
        return False
    return any(same_surname_group(s, branch) for branch in BRANCH_SURNAMES)


def region_style_for_surname(s: Optional[str]) -> str:
    """Retourne la classe CSS Mermaid associée au patronyme, ou DEFAULT_REGION_STYLE."""
    normalized = normalize_surname(s)
    if not normalized:
        return DEFAULT_REGION_STYLE
    style = _STYLE_INDEX.get(normalized)
    if style:
        return style
    # Repli par groupe de variantes (ex. VERGNES absent du mapping mais du groupe cantal).
    group = surname_group(normalized)
    if group:
        for name in group:
            style = _STYLE_INDEX.get(normalize_surname(name))
            if style:
                return style
    return DEFAULT_REGION_STYLE
