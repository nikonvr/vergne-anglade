"""Politique anti-fabrication : garde-fou commun à toutes les sources de données.

Règle du projet : aucun composant ne doit inventer de donnée silencieusement.
Un composant incapable de produire une donnée réelle lève une exception claire,
SAUF si la simulation est explicitement autorisée par CERTUS_ALLOW_SIMULATED=1.

Toute donnée produite en mode simulé doit obligatoirement porter :
  - is_simulated=True
  - un source_type préfixé par SIMULATED_PREFIX
  - confidence_score=0.0 et reliability_score=0.0
"""

import logging
import os

logger = logging.getLogger("certus.simulation")

# Nom figé de la variable d'environnement autorisant les sources simulées.
ENV_ALLOW_SIMULATED = "CERTUS_ALLOW_SIMULATED"

# Préfixe obligatoire des source_type des données simulées.
SIMULATED_PREFIX = "SIMULATED_"

# Valeurs acceptées comme « vrai » pour CERTUS_ALLOW_SIMULATED.
_TRUE_VALUES = {"1", "true", "yes", "oui", "on"}


class SimulationDisabledError(RuntimeError):
    """Levée quand un composant ne peut produire qu'une donnée simulée alors que
    la simulation n'est pas autorisée."""


def simulation_allowed() -> bool:
    """Indique si les sources simulées sont autorisées (CERTUS_ALLOW_SIMULATED)."""
    return os.environ.get(ENV_ALLOW_SIMULATED, "").strip().lower() in _TRUE_VALUES


def require_simulation(component: str) -> None:
    """Autorise le composant à produire une donnée simulée, ou lève SimulationDisabledError.

    À appeler AVANT toute génération de donnée non sourcée.
    """
    if not simulation_allowed():
        raise SimulationDisabledError(
            f"{component} ne peut produire aucune donnée réelle et la simulation est "
            f"désactivée. Définissez {ENV_ALLOW_SIMULATED}=1 pour autoriser explicitement "
            f"des données simulées (elles seront marquées is_simulated=True, "
            f"source_type '{SIMULATED_PREFIX}...' et scores à 0.0)."
        )
    logger.warning(
        "%s produit une donnée SIMULÉE (non sourcée) : %s=1 est actif.",
        component,
        ENV_ALLOW_SIMULATED,
    )


def simulated_source_type(source_type: str) -> str:
    """Retourne le source_type préfixé SIMULATED_ (idempotent)."""
    clean = (source_type or "UNKNOWN").strip() or "UNKNOWN"
    if clean.startswith(SIMULATED_PREFIX):
        return clean
    return f"{SIMULATED_PREFIX}{clean}"


def is_simulated_source_type(source_type: str) -> bool:
    """Indique si un source_type désigne une donnée simulée."""
    return (source_type or "").startswith(SIMULATED_PREFIX)
