"""Moteurs HTR de référence du domaine — branchements à compléter.

Ces trois moteurs sont les outils que la communauté archivistique utilise réellement sur les
registres anciens. Ils ne sont PAS implémentés : chaque classe expose ce qu'il faut faire et
refuse de fonctionner tant que ce n'est pas fait, plutôt que de retourner un texte factice.

TRANSKRIBUS (READ Coop) — la référence pour l'écriture manuscrite européenne. Modèles
publics entraînés sur des mains françaises des 17e et 18e siècles, donc le meilleur candidat
pour ce fonds. API REST, compte et crédits requis.

KRAKEN / eScriptorium — chaîne HTR libre, auto-hébergeable, modèles publics téléchargeables.
Aucun coût, aucune donnée envoyée à un tiers, mais segmentation à régler soi-même.

TESSERACT — OCR pour l'IMPRIMÉ uniquement. Inutile sur une main d'Ancien Régime ; utile en
revanche sur les tables décennales et les actes d'état civil imprimés de la fin du 19e.

À FAIRE POUR EN ACTIVER UN
  1. implémenter available() : vérifier la clé ou le binaire, retourner une raison précise ;
  2. implémenter transcribe() : appeler le service, lever HTRError en cas d'échec ;
  3. supprimer l'appel à _not_implemented() ;
  4. ajouter le moteur à CERTUS_HTR_BACKENDS.
Ne modifiez rien d'autre : le registre suffit à l'intégrer au consensus.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from src.ocr.htr import HTRBackend, HTRBackendUnavailable, HTRRegistry, HTRResult


def _not_implemented(name: str, guidance: str) -> HTRBackendUnavailable:
    return HTRBackendUnavailable(
        f"Le moteur « {name} » n'est pas encore implémenté. {guidance} "
        "Il refuse de produire une transcription plutôt que d'en inventer une."
    )


@HTRRegistry.register
class TranskribusBackend(HTRBackend):
    name = "transkribus"
    description = "Transkribus (READ Coop) : référence HTR pour les mains anciennes."

    ENV_USER = "TRANSKRIBUS_USER"
    ENV_PASSWORD = "TRANSKRIBUS_PASSWORD"
    ENV_MODEL_ID = "TRANSKRIBUS_MODEL_ID"

    def available(self) -> tuple[bool, str]:
        if not os.environ.get(self.ENV_USER) or not os.environ.get(self.ENV_PASSWORD):
            return False, f"définissez {self.ENV_USER} et {self.ENV_PASSWORD}."
        if not os.environ.get(self.ENV_MODEL_ID):
            return False, (
                f"définissez {self.ENV_MODEL_ID} avec l'identifiant d'un modèle adapté au "
                "français des 17e-18e siècles."
            )
        return False, "identifiants présents, mais l'appel REST reste à implémenter."

    def transcribe(self, image_path: Path) -> HTRResult:
        raise _not_implemented(
            self.name,
            "Implémentez l'authentification, le téléversement de l'image, le lancement de "
            "la reconnaissance avec le modèle choisi, l'attente du résultat puis la lecture "
            "du PAGE XML retourné.",
        )


@HTRRegistry.register
class KrakenBackend(HTRBackend):
    name = "kraken"
    description = "Kraken / eScriptorium : HTR libre, exécuté localement."

    ENV_MODEL_PATH = "CERTUS_KRAKEN_MODEL"

    def available(self) -> tuple[bool, str]:
        try:
            import kraken  # noqa: F401
        except ImportError:
            return False, "paquet « kraken » absent : installez-le pour l'exécution locale."
        model = os.environ.get(self.ENV_MODEL_PATH)
        if not model:
            return False, (
                f"définissez {self.ENV_MODEL_PATH} vers un modèle de reconnaissance "
                "adapté au français ancien."
            )
        if not Path(model).exists():
            return False, f"modèle introuvable au chemin indiqué par {self.ENV_MODEL_PATH}."
        return False, "modèle présent, mais l'enchaînement segmentation puis reconnaissance reste à implémenter."

    def transcribe(self, image_path: Path) -> HTRResult:
        raise _not_implemented(
            self.name,
            "Implémentez la segmentation en lignes (blla.mlmodel) puis la reconnaissance "
            "ligne par ligne avec le modèle configuré.",
        )


@HTRRegistry.register
class TesseractBackend(HTRBackend):
    name = "tesseract"
    description = "Tesseract : IMPRIMÉ uniquement, inadapté à l'écriture manuscrite ancienne."

    def available(self) -> tuple[bool, str]:
        if shutil.which("tesseract") is None:
            return False, "binaire « tesseract » absent du PATH."
        return False, (
            "binaire présent, mais l'appel reste à implémenter. Attention : Tesseract ne lit "
            "pas l'écriture manuscrite ancienne ; ne l'activez que pour des documents imprimés."
        )

    def transcribe(self, image_path: Path) -> HTRResult:
        raise _not_implemented(
            self.name,
            "Implémentez l'appel en langue « fra ». À réserver aux tables décennales et "
            "actes imprimés.",
        )
