"""Socle de reconnaissance d'écriture manuscrite (HTR) multi-moteurs.

POURQUOI CETTE ARCHITECTURE
Aucun moteur ne lit de façon fiable une main d'Ancien Régime. La stratégie retenue est donc
d'exécuter PLUSIEURS moteurs sur la même image et de mesurer leur accord : le taux d'accord
fournit un score de confiance RÉEL, là où le code d'origine annonçait 0,95 sur une phrase
constante inventée.

COMMENT AJOUTER UN MOTEUR
  1. créer src/ocr/backends/<nom>.py ;
  2. y définir une classe héritant de HTRBackend, avec name, available() et transcribe() ;
  3. la décorer avec @HTRRegistry.register ;
  4. l'importer dans src/ocr/backends/__init__.py ;
  5. l'ajouter à CERTUS_HTR_BACKENDS pour l'activer.
Rien d'autre n'est à modifier. Ne branchez jamais un moteur ailleurs que par ce registre.

DIAGNOSTIC
    python -m src.ocr.htr
affiche les moteurs connus, ceux qui sont réellement utilisables, et la raison précise pour
les autres.

RÈGLE ABSOLUE
Un moteur qui ne peut pas transcrire lève une exception. Il ne retourne JAMAIS de texte
inventé, ni une chaîne vide silencieuse. Un texte simulé n'existe que si
CERTUS_ALLOW_SIMULATED=1 et porte alors is_simulated=True.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Type

logger = logging.getLogger("certus.ocr.htr")

ENV_BACKENDS = "CERTUS_HTR_BACKENDS"
# « simulated » figure dans la liste par défaut sans risque : ce moteur se déclare
# indisponible tant que CERTUS_ALLOW_SIMULATED=1 n'est pas positionné.
DEFAULT_BACKENDS = "claude_vision,simulated"


class HTRError(RuntimeError):
    """Erreur de transcription. Toujours préférable à un texte inventé."""


class HTRBackendUnavailable(HTRError):
    """Le moteur existe mais n'est pas utilisable (dépendance ou clé manquante)."""


@dataclass
class HTRResult:
    """Transcription produite par un moteur unique."""

    text: str
    backend: str
    confidence: Optional[float] = None
    is_simulated: bool = False
    warnings: List[str] = field(default_factory=list)
    raw: Optional[dict] = None

    @property
    def illegible_markers(self) -> int:
        """Nombre de passages que le moteur a déclarés illisibles ou incertains."""
        return self.text.count("[illisible]") + self.text.count("(?)")


@dataclass
class ConsensusResult:
    """Résultat consolidé de plusieurs moteurs sur une même image."""

    text: str
    primary_backend: str
    agreement: float
    results: List[HTRResult]
    is_simulated: bool = False

    @property
    def backends_used(self) -> List[str]:
        return [r.backend for r in self.results]

    @property
    def needs_human_review(self) -> bool:
        """Un accord faible ou beaucoup de passages illisibles exigent une relecture.

        Sur ces écritures, la validation humaine n'est pas un luxe : c'est la seule façon
        d'obtenir une généalogie fiable. Le seuil est volontairement exigeant.
        """
        return self.agreement < 0.85 or any(r.illegible_markers > 0 for r in self.results)


class HTRBackend(ABC):
    """Contrat que doit respecter tout moteur de transcription."""

    #: identifiant court, utilisé dans CERTUS_HTR_BACKENDS et dans les traces
    name: str = "abstrait"
    #: description affichée par le diagnostic
    description: str = ""

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Retourne (utilisable, raison). La raison doit être actionnable si inutilisable."""

    @abstractmethod
    def transcribe(self, image_path: Path) -> HTRResult:
        """Transcrit l'image. Lève HTRError en cas d'échec, ne fabrique jamais de texte."""

    def ensure_available(self) -> None:
        ok, reason = self.available()
        if not ok:
            raise HTRBackendUnavailable(f"Moteur « {self.name} » indisponible : {reason}")


class HTRRegistry:
    """Registre des moteurs. Unique point de branchement autorisé."""

    _backends: Dict[str, Type[HTRBackend]] = {}

    @classmethod
    def register(cls, backend_class: Type[HTRBackend]) -> Type[HTRBackend]:
        name = getattr(backend_class, "name", None)
        if not name or name == "abstrait":
            raise ValueError(
                f"{backend_class.__name__} doit définir un attribut de classe 'name' explicite."
            )
        cls._backends[name] = backend_class
        return backend_class

    @classmethod
    def known(cls) -> Dict[str, Type[HTRBackend]]:
        return dict(cls._backends)

    @classmethod
    def instantiate(cls, name: str) -> HTRBackend:
        if name not in cls._backends:
            raise HTRError(
                f"Moteur HTR inconnu : « {name} ». Moteurs enregistrés : "
                f"{', '.join(sorted(cls._backends)) or 'aucun'}."
            )
        return cls._backends[name]()

    @classmethod
    def selected_names(cls) -> List[str]:
        """Moteurs demandés par l'environnement, dans l'ordre de préférence."""
        raw = os.environ.get(ENV_BACKENDS) or DEFAULT_BACKENDS
        return [part.strip() for part in raw.split(",") if part.strip()]

    @classmethod
    def usable(cls) -> List[HTRBackend]:
        """Instancie les moteurs demandés qui sont réellement utilisables."""
        usable: List[HTRBackend] = []
        for name in cls.selected_names():
            if name not in cls._backends:
                logger.warning("Moteur HTR « %s » demandé mais non enregistré.", name)
                continue
            backend = cls.instantiate(name)
            ok, reason = backend.available()
            if ok:
                usable.append(backend)
            else:
                logger.info("Moteur HTR « %s » écarté : %s", name, reason)
        return usable

    @classmethod
    def diagnostics(cls) -> List[tuple[str, bool, str]]:
        report = []
        for name, backend_class in sorted(cls._backends.items()):
            try:
                ok, reason = backend_class().available()
            except Exception as exc:  # pragma: no cover - moteur mal écrit
                ok, reason = False, f"erreur à l'instanciation : {exc}"
            report.append((name, ok, reason))
        return report


# ------------------------------------------------------------------------------ consensus
def _similarity(a: str, b: str) -> float:
    """Similarité normalisée entre deux transcriptions, dans [0, 1]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz.distance.Levenshtein import normalized_similarity

        return float(normalized_similarity(a, b))
    except ImportError:  # pragma: no cover - rapidfuzz est une dépendance déclarée
        shorter, longer = sorted((a, b), key=len)
        common = sum(1 for x, y in zip(shorter, longer) if x == y)
        return common / len(longer)


def transcribe_with_consensus(
    image_path: Path, backends: Optional[Sequence[HTRBackend]] = None
) -> ConsensusResult:
    """Exécute les moteurs disponibles et consolide leurs transcriptions.

    Le texte retenu est celui qui ressemble le plus aux autres (médoïde) : c'est la lecture
    la moins atypique, un choix plus robuste que « le premier moteur configuré ».
    L'accord moyen entre moteurs devient le score de confiance.
    """
    engines = list(backends) if backends is not None else HTRRegistry.usable()
    if not engines:
        raise HTRBackendUnavailable(
            "Aucun moteur HTR utilisable. Lancez « python -m src.ocr.htr » pour connaître "
            f"la raison pour chaque moteur, puis configurez {ENV_BACKENDS}."
        )

    results: List[HTRResult] = []
    failures: List[str] = []
    for backend in engines:
        try:
            results.append(backend.transcribe(Path(image_path)))
        except HTRError as exc:
            failures.append(f"{backend.name} : {exc}")
            logger.warning("Moteur « %s » en échec : %s", backend.name, exc)

    if not results:
        raise HTRError(
            "Tous les moteurs HTR ont échoué sur cette image. Détail : " + " | ".join(failures)
        )

    if len(results) == 1:
        only = results[0]
        # Un seul moteur : aucun accord mesurable. On n'invente pas de score élevé, on
        # retient celui que le moteur annonce, à défaut une valeur volontairement prudente.
        return ConsensusResult(
            text=only.text,
            primary_backend=only.backend,
            agreement=only.confidence if only.confidence is not None else 0.5,
            results=results,
            is_simulated=only.is_simulated,
        )

    scores: List[float] = []
    for index, result in enumerate(results):
        others = [r for j, r in enumerate(results) if j != index]
        scores.append(sum(_similarity(result.text, o.text) for o in others) / len(others))

    best_index = max(range(len(results)), key=lambda i: scores[i])
    agreement = sum(scores) / len(scores)
    logger.info(
        "Consensus HTR sur %d moteurs : accord moyen %.2f, lecture retenue « %s ».",
        len(results),
        agreement,
        results[best_index].backend,
    )
    return ConsensusResult(
        text=results[best_index].text,
        primary_backend=results[best_index].backend,
        agreement=agreement,
        results=results,
        is_simulated=any(r.is_simulated for r in results),
    )


def _print_diagnostics() -> int:
    # Exécuté via « python -m », ce fichier est chargé sous le nom __main__ : son registre
    # local n'est PAS celui qu'alimentent les moteurs. On passe donc par le module canonique.
    import src.ocr.backends  # noqa: F401  (déclenche l'enregistrement des moteurs)
    from src.ocr.htr import ENV_BACKENDS, HTRRegistry

    print("=" * 78)
    print("MOTEURS HTR — DIAGNOSTIC")
    print("=" * 78)
    report = HTRRegistry.diagnostics()
    if not report:
        print("  Aucun moteur enregistré.")
        return 1
    for name, ok, reason in report:
        print(f"  {'UTILISABLE ' if ok else 'INDISPONIBLE'}  {name}")
        if not ok:
            print(f"                {reason}")
    print("-" * 78)
    selected = HTRRegistry.selected_names()
    usable = [b.name for b in HTRRegistry.usable()]
    print(f"  {ENV_BACKENDS} = {', '.join(selected)}")
    print(f"  Réellement utilisables : {', '.join(usable) if usable else 'AUCUN'}")
    if len(usable) < 2:
        print("  Avertissement : le consensus exige au moins deux moteurs pour produire")
        print("  un score de confiance mesuré plutôt que déclaré.")
    return 0 if usable else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    raise SystemExit(_print_diagnostics())
