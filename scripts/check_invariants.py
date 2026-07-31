"""Vérificateur d'invariants du projet CERTUS-GENEALOGY.

Ce script est le GARDE-FOU MÉCANIQUE du dépôt. Chaque invariant correspond à un défaut réel
constaté par un audit et corrigé : le rôle de ce fichier est d'empêcher sa réapparition.

Usage :
    python scripts/check_invariants.py          # rapport complet, code de sortie 1 si échec
    python scripts/check_invariants.py --list   # liste les invariants sans les exécuter

Les invariants purement statiques sont ici ; les invariants de comportement sont dans
tests/test_invariants.py, qui réutilise ces mêmes fonctions.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("src", "scripts")
PUBLIC_PAGE = PROJECT_ROOT / "index.html"


# ---------------------------------------------------------------------------- utilitaires
@dataclass
class Violation:
    location: str
    message: str


@dataclass
class Invariant:
    code: str
    title: str
    rationale: str
    check: Callable[[], List[Violation]]
    skipped_reason: str | None = field(default=None)


# Ce fichier contient les motifs interdits sous forme de littéraux : il s'auto-signalerait.
SELF = Path(__file__).resolve()


def python_files() -> Iterable[Path]:
    for directory in SOURCE_DIRS:
        root = PROJECT_ROOT / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path.resolve() == SELF:
                continue
            yield path


def code_only(source: str) -> str:
    """Retire commentaires et docstrings.

    Indispensable : les commentaires de ce dépôt CITENT les motifs interdits pour expliquer
    ce qui a été corrigé. Les rechercher sans filtrer produirait des faux positifs.
    """
    kept: List[str] = []
    previous = tokenize.NEWLINE
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                continue
            if token.type == tokenize.STRING and previous in (
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENCODING,
            ):
                continue  # docstring de module, de classe ou de fonction
            kept.append(token.string)
            if token.type not in (tokenize.NL, tokenize.COMMENT):
                previous = token.type
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    return "\n".join(kept)


def scan_code(pattern: re.Pattern[str], message: str) -> List[Violation]:
    """Cherche un motif interdit dans le code effectif de src/ et scripts/."""
    violations: List[Violation] = []
    for path in python_files():
        source = path.read_text(encoding="utf-8", errors="ignore")
        stripped = code_only(source)
        if pattern.search(stripped):
            violations.append(Violation(str(path.relative_to(PROJECT_ROOT)), message))
    return violations


def read_page() -> str | None:
    if not PUBLIC_PAGE.exists():
        return None
    return PUBLIC_PAGE.read_text(encoding="utf-8", errors="ignore")


# ------------------------------------------------------------------------- INV-01 secrets
_SECRET_DEFAULT = re.compile(
    r"""environ(?:ment)?\s*(?:\.get\(|\[)\s*["'][A-Z0-9_]*"""
    r"""(?:PASSWORD|PASSWD|USERNAME|USER|TOKEN|SECRET|API_KEY|KEY)["']\s*,\s*["'][^"']+["']""",
    re.IGNORECASE,
)
_SECRET_ASSIGN = re.compile(
    r"""^\s*(?:self\.)?(?:password|passwd|api_key|secret|token)\s*(?::\s*[^=]+)?=\s*["'][^"']{3,}["']""",
    re.IGNORECASE | re.MULTILINE,
)


def check_no_hardcoded_secrets() -> List[Violation]:
    violations = scan_code(
        _SECRET_DEFAULT,
        "valeur par défaut littérale sur une variable d'environnement sensible : "
        "un identifiant en clair avait déjà été poussé sur le dépôt distant.",
    )
    violations += scan_code(
        _SECRET_ASSIGN,
        "affectation littérale d'un mot de passe, d'un jeton ou d'une clé d'API.",
    )
    return violations


# ---------------------------------------------------------------- INV-02 fabrication de données
_FABRICATION_PATTERNS = [
    (
        re.compile(r"""url_source\s+or\s+["']"""),
        "url_source remplacé par une URL littérale : cela fabriquait une provenance pour "
        "des actes qui n'en ont aucune (334 actes sur 334 avaient url_source à NULL).",
    ),
    (
        re.compile(r"""confidence(?:_score)?\s+or\s+[0-9]"""),
        "score de confiance remplacé par une constante : la fiabilité affichée devient fausse.",
    ),
    (
        re.compile(r"""source_text\s+or\s+f?["']"""),
        "transcription remplacée par un texte littéral : c'est une invention présentée "
        "comme le contenu du registre.",
    ),
    (
        re.compile(r"""(?:reliability_score|confidence_score)\s*=\s*(?:0\.9|1\.0)\s*,?\s*\n?\s*.*is_simulated\s*=\s*True"""),
        "un acte simulé doit porter des scores à 0.0, jamais un score élevé.",
    ),
]


def check_no_fabricated_fallbacks() -> List[Violation]:
    violations: List[Violation] = []
    for pattern, message in _FABRICATION_PATTERNS:
        violations += scan_code(pattern, message)
    return violations


# --------------------------------------------------------------------------- INV-03 CORS
_WILDCARD_CORS = re.compile(r"""allow_origins\s*=\s*\[\s*["']\*["']""")


def check_no_wildcard_cors() -> List[Violation]:
    return scan_code(
        _WILDCARD_CORS,
        "allow_origins=['*'] combiné à allow_credentials=True permettait à n'importe quel "
        "site d'appeler l'API avec les cookies du visiteur.",
    )


# ------------------------------------------------------------------ INV-04 échecs silencieux
_SILENT_EXCEPT = re.compile(r"except[^\n:]*:\s*\n\s*pass\b")
_BARE_EXCEPT = re.compile(r"except\s*:")


def check_no_silent_failures() -> List[Violation]:
    violations = scan_code(
        _SILENT_EXCEPT,
        "'except ...: pass' masque la panne. Journalisez au minimum en WARNING : un import "
        "GEDCOM en échec devenait indistinguable d'un import vide.",
    )
    violations += scan_code(_BARE_EXCEPT, "'except:' nu intercepte jusqu'aux interruptions.")
    return violations


# ------------------------------------------------- INV-05 source unique des patronymes
def check_single_source_of_surnames() -> List[Violation]:
    """Aucune liste de patronymes ne doit être dupliquée hors de variants.py."""
    variants_file = PROJECT_ROOT / "src" / "genealogy" / "variants.py"
    if not variants_file.exists():
        return [Violation("src/genealogy/variants.py", "fichier manquant : c'est la source unique de vérité des patronymes.")]

    from_variants = re.compile(r'"(VERGNE|ANGLADE|BRUN|JEHL|IEHL|VERNHE|VERNHES|VERGNES)"')
    violations: List[Violation] = []
    for path in python_files():
        if path == variants_file:
            continue
        stripped = code_only(path.read_text(encoding="utf-8", errors="ignore"))
        matches = set(from_variants.findall(stripped))
        if len(matches) >= 2:
            violations.append(
                Violation(
                    str(path.relative_to(PROJECT_ROOT)),
                    f"liste de patronymes dupliquée ({', '.join(sorted(matches))}). "
                    "Importez BRANCH_SURNAMES depuis src/genealogy/variants.py : la liste "
                    "était auparavant recopiée dans quatre fichiers.",
                )
            )
    return violations


# ----------------------------------------------------- INV-06 filtre de patronyme exact
def check_surname_matching_is_exact() -> List[Violation]:
    """Les importeurs (GEDCOM et CSV) doivent comparer les patronymes exactement, jamais par sous-chaîne."""
    violations: List[Violation] = []

    # 1. gedcom_importer.py
    gedcom_importer = PROJECT_ROOT / "src" / "parser" / "gedcom_importer.py"
    if not gedcom_importer.exists():
        violations.append(Violation("src/parser/gedcom_importer.py", "fichier manquant."))
    else:
        stripped = code_only(gedcom_importer.read_text(encoding="utf-8", errors="ignore"))
        if "same_surname_group" not in stripped and "is_branch_surname" not in stripped:
            violations.append(
                Violation(
                    "src/parser/gedcom_importer.py",
                    "le filtre de branche doit utiliser same_surname_group ou is_branch_surname (comparaison exacte). "
                    "La comparaison par sous-chaîne rattachait 15 individus à tort : "
                    "'VERGNE' in 'LAVERGNE' est vrai, de même que BRUN pour BRUNET.",
                )
            )
        if re.search(r"\bin\s*\(\s*(?:ln|last_name)\b", stripped) or re.search(
            r"for\s+s\s+in\s+surnames\s*\)", stripped
        ):
            violations.append(
                Violation(
                    "src/parser/gedcom_importer.py",
                    "comparaison de patronyme par sous-chaîne détectée.",
                )
            )

    # 2. csv_importer.py
    csv_importer = PROJECT_ROOT / "src" / "parser" / "csv_importer.py"
    if not csv_importer.exists():
        violations.append(Violation("src/parser/csv_importer.py", "fichier manquant."))
    else:
        stripped_csv = code_only(csv_importer.read_text(encoding="utf-8", errors="ignore"))
        if "is_branch_surname" not in stripped_csv and "same_surname_group" not in stripped_csv:
            violations.append(
                Violation(
                    "src/parser/csv_importer.py",
                    "le filtre de patronyme CSV doit utiliser is_branch_surname ou same_surname_group (comparaison exacte).",
                )
            )
        if re.search(r"\bnot\s+in\s+last_name\b", stripped_csv) or re.search(r"\bin\s+last_name\b", stripped_csv):
            violations.append(
                Violation(
                    "src/parser/csv_importer.py",
                    "comparaison de patronyme par sous-chaîne détectée.",
                )
            )

    return violations


# --------------------------------------------------------------- INV-07 dépendances
def check_declared_dependencies() -> List[Violation]:
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return [Violation("pyproject.toml", "fichier manquant.")]
    content = pyproject.read_text(encoding="utf-8", errors="ignore")
    violations: List[Violation] = []
    if "playwright" in content:
        violations.append(
            Violation(
                "pyproject.toml",
                "playwright est déclaré mais jamais importé : dépendance lourde inutile.",
            )
        )
    for required in ("sqlalchemy", "networkx", "fastapi", "rapidfuzz"):
        if required not in content:
            violations.append(
                Violation(
                    "pyproject.toml",
                    f"{required} est utilisé par le code mais absent des dépendances. "
                    "L'oubli de sqlalchemy rendait la tâche planifiée systématiquement en échec.",
                )
            )
    return violations


# ------------------------------------------------------------ INV-08 artefacts du dépôt
def check_repository_artifacts() -> List[Violation]:
    violations: List[Violation] = []
    if (PROJECT_ROOT / "build_certus.py").exists():
        violations.append(
            Violation(
                "build_certus.py",
                "ce générateur réécrit des versions PÉRIMÉES de 13 fichiers source "
                "(son process_acts retourne un arbre vide). Il doit rester dans attic/.",
            )
        )
    duplicate = PROJECT_ROOT / "vergne_genealogy_standalone.html"
    if duplicate.exists():
        violations.append(
            Violation(
                "vergne_genealogy_standalone.html",
                "doublon strictement identique à index.html (270 Ko), régénéré et versionné "
                "à chaque build. Un seul artefact publié : index.html.",
            )
        )
    egg_info = list((PROJECT_ROOT / "src").glob("*.egg-info"))
    for path in egg_info:
        if any((path / name).exists() for name in ("PKG-INFO",)):
            # Présent sur disque est acceptable ; c'est le suivi par git qui est proscrit.
            pass
    return violations


# ----------------------------------------------------- INV-09 page publique sans invention
_PAGE_FORBIDDEN = [
    ("100% V", "affirmation de fiabilité en dur : elle doit être calculée depuis les données."),
    ("246 membres", "effectif codé en dur : il doit être calculé."),
    ("349 liens", "nombre de liens codé en dur : il doit être calculé."),
    (
        "archives.cantal.fr",
        "URL de registre utilisée comme valeur de repli : elle fabriquait une provenance "
        "pour les 334 actes qui n'en avaient aucune.",
    ),
    (
        "Acte d'état civil original enregistré",
        "transcription inventée, affichée comme le contenu officiel du registre.",
    ),
    (
        "Transcription Officielle",
        "titre qui promet davantage que ce que la donnée contient.",
    ),
    (
        "openModalForPerson(",
        "nom interpolé dans un attribut d'événement : une apostrophe dans un patronyme "
        "cassait le bouton. Utilisez des attributs data-* et une délégation d'événement.",
    ),
]


def check_public_page_has_no_invention() -> List[Violation]:
    page = read_page()
    if page is None:
        return []
    return [
        Violation("index.html", f"chaîne interdite « {needle} » : {reason}")
        for needle, reason in _PAGE_FORBIDDEN
        if needle in page
    ]


# ------------------------------------------------------------------------- registre
INVARIANTS: List[Invariant] = [
    Invariant(
        "INV-01",
        "Aucun secret en clair",
        "Un couple identifiant/mot de passe avait été poussé sur le dépôt distant.",
        check_no_hardcoded_secrets,
    ),
    Invariant(
        "INV-02",
        "Aucune donnée fabriquée",
        "Des valeurs de repli inventées présentaient 334 actes non sourcés comme sourcés.",
        check_no_fabricated_fallbacks,
    ),
    Invariant(
        "INV-03",
        "CORS jamais permissif",
        "allow_origins=['*'] avec allow_credentials=True exposait l'API à tout site tiers.",
        check_no_wildcard_cors,
    ),
    Invariant(
        "INV-04",
        "Aucun échec silencieux",
        "Une dizaine de 'except: pass' masquaient les pannes réelles.",
        check_no_silent_failures,
    ),
    Invariant(
        "INV-05",
        "Patronymes définis en un seul endroit",
        "La liste des patronymes était recopiée dans quatre fichiers, qui ont divergé.",
        check_single_source_of_surnames,
    ),
    Invariant(
        "INV-06",
        "Filtre de patronyme exact",
        "La comparaison par sous-chaîne rattachait 15 individus étrangers à la branche.",
        check_surname_matching_is_exact,
    ),
    Invariant(
        "INV-07",
        "Dépendances déclarées et utilisées",
        "sqlalchemy manquait, playwright était déclaré sans être importé.",
        check_declared_dependencies,
    ),
    Invariant(
        "INV-08",
        "Pas d'artefact dangereux à la racine",
        "build_certus.py réécrit du code périmé ; le doublon HTML pesait 270 Ko.",
        check_repository_artifacts,
    ),
    Invariant(
        "INV-09",
        "Page publique sans invention",
        "La page affichait « 100% Vérifié » et des effectifs figés, même sur un arbre vide.",
        check_public_page_has_no_invention,
    ),
]


def run(selected: Iterable[str] | None = None) -> int:
    chosen = [inv for inv in INVARIANTS if not selected or inv.code in selected]
    failures = 0
    print("=" * 78)
    print("VÉRIFICATION DES INVARIANTS - CERTUS-GENEALOGY")
    print("=" * 78)
    for invariant in chosen:
        violations = invariant.check()
        if not violations:
            print(f"  OK      {invariant.code}  {invariant.title}")
            continue
        failures += 1
        print(f"  ÉCHEC   {invariant.code}  {invariant.title}")
        print(f"          Pourquoi : {invariant.rationale}")
        for violation in violations:
            print(f"          -> {violation.location}")
            print(f"             {violation.message}")
    print("-" * 78)
    if failures:
        print(f"{failures} invariant(s) violé(s) sur {len(chosen)}. Corrigez avant de livrer.")
    else:
        print(f"Les {len(chosen)} invariants sont respectés.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérifie les invariants du projet.")
    parser.add_argument("--list", action="store_true", help="liste les invariants")
    parser.add_argument("--only", nargs="*", help="codes d'invariants à vérifier")
    args = parser.parse_args()

    if args.list:
        for invariant in INVARIANTS:
            print(f"{invariant.code}  {invariant.title}\n          {invariant.rationale}")
        return 0
    return run(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
