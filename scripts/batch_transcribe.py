"""Pipeline de transcription par lot et persistance des actes en base.

Ce script parcourt un répertoire d'images d'archives, les découpe en actes via
FlorenceOCREngine.segment_acts, les transcrit via transcribe_with_consensus, extrait
les entités via LLMActParser, et persiste les actes en base par lot (ActRepository.save_acts).

Idempotence et traçabilité :
Un registre JSON (CERTUS_BATCH_LEDGER) enregistre les empreintes SHA-256 des images traitées
et les identifiants d'actes créés pour éviter toute duplication.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, ".")

from src.database.engine import DatabaseManager
from src.database.repository import ActRepository
from src.ocr.florence import FlorenceOCREngine
from src.ocr.htr import ConsensusResult, HTRError, transcribe_with_consensus
from src.parser.llm import LLMActParser

logger = logging.getLogger("certus.batch")

DEFAULT_LEDGER_PATH = ".certus_cache/batch_ledger.json"


def get_ledger_path() -> Path:
    raw = os.environ.get("CERTUS_BATCH_LEDGER") or DEFAULT_LEDGER_PATH
    p = Path(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_ledger(ledger_path: Path) -> dict:
    if ledger_path.exists():
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                return {
                    str(Path(k).resolve()).replace("\\", "/").lower(): v
                    for k, v in raw_data.items()
                }
        except Exception as exc:
            logger.warning(
                "Impossible de lire le registre JSON (%s), un nouveau registre sera créé : %s",
                ledger_path,
                exc,
            )
    return {}


def save_ledger(ledger: dict, ledger_path: Path) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ledger_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
    tmp_path.replace(ledger_path)


def process_batch(
    source_dir: Path | str,
    limit: Optional[int] = None,
    dry_run: bool = False,
    resume: bool = True,
    force: bool = False,
    delay: float = 0.0,
    db_manager: Optional[DatabaseManager] = None,
) -> int:
    source_p = Path(source_dir)
    if not source_p.exists():
        logger.error("Répertoire source introuvable : %s", source_p)
        return 1

    # Import des backends pour enregistrer tous les moteurs dans HTRRegistry
    import src.ocr.backends  # noqa: F401

    ledger_path = get_ledger_path()
    ledger = load_ledger(ledger_path) if (resume and not dry_run) else {}

    # Récupérer les images
    if source_p.is_file():
        image_files = [source_p]
    else:
        valid_exts = {".jpg", ".jpeg", ".png"}
        image_files = sorted(
            [
                p
                for p in source_p.rglob("*")
                if p.suffix.lower() in valid_exts
                and ".certus_cache" not in p.parts
                and ".venv" not in p.parts
            ]
        )

    logger.info(
        "Traitement du répertoire %s : %d image(s) trouvée(s).", source_p, len(image_files)
    )

    engine = FlorenceOCREngine()
    parser = LLMActParser()

    if db_manager is None:
        db_manager = DatabaseManager()
        db_manager.init_db()

    processed_count = 0
    skipped_count = 0
    failed_count = 0
    created_acts_total = 0
    simulated_acts_total = 0
    review_needed_images: List[str] = []

    images_to_process = []
    for img_path in image_files:
        rel_key = str(img_path.resolve()).replace("\\", "/").lower()
        sha256 = compute_sha256(img_path)

        if not force and resume and rel_key in ledger:
            entry = ledger[rel_key]
            if entry.get("status") == "OK" and entry.get("sha256") == sha256:
                skipped_count += 1
                continue

        images_to_process.append((img_path, rel_key, sha256))

    if limit is not None and limit > 0:
        images_to_process = images_to_process[:limit]

    logger.info(
        "Images à traiter : %d (%d sautées).", len(images_to_process), skipped_count
    )

    has_error = False

    for idx, (img_path, rel_key, sha256) in enumerate(images_to_process, start=1):
        logger.info(
            "[%d/%d] Traitement de l'image %s...", idx, len(images_to_process), img_path.name
        )
        if delay > 0 and idx > 1:
            time.sleep(delay)

        try:
            # 1. Découpage en actes
            segments = engine.segment_acts(img_path)
            logger.info("  -> %d segment(s) produit(s).", len(segments))

            acts_for_image = []
            segment_consensuses: List[ConsensusResult] = []

            # 2. Transcription et parsing par segment
            for seg_idx, seg_path in enumerate(segments, start=1):
                consensus = transcribe_with_consensus(seg_path)
                segment_consensuses.append(consensus)

                act = parser.parse(consensus.text)
                act.source_text = consensus.text
                act.url_source = None  # Pas de fausse URL (R1)

                if consensus.is_simulated:
                    act.is_simulated = True
                    backend_name = consensus.primary_backend.upper()
                    if backend_name == "SIMULATED":
                        act.source_type = "SIMULATED_SIMULATED"
                    elif backend_name.startswith("SIMULATED_"):
                        act.source_type = backend_name
                    else:
                        act.source_type = f"SIMULATED_{backend_name}"
                    act.confidence_score = 0.0
                    act.reliability_score = 0.0
                else:
                    act.is_simulated = False
                    act.source_type = f"HTR_{consensus.primary_backend.upper()}"
                    act.reliability_score = consensus.agreement

                acts_for_image.append(act)

            needs_review = any(c.needs_human_review for c in segment_consensuses)
            if needs_review:
                review_needed_images.append(img_path.name)

            is_img_simulated = any(c.is_simulated for c in segment_consensuses)
            if is_img_simulated:
                simulated_acts_total += len(acts_for_image)

            old_entry = ledger.get(rel_key, {})
            old_act_ids = old_entry.get("act_ids", [])

            # 3. Persistance (remplacement des actes existants de cette image)
            created_act_ids = []
            if not dry_run:
                session = db_manager.get_session()
                try:
                    repo = ActRepository(session)
                    if old_act_ids:
                        deleted_count = repo.delete_acts_by_ids(old_act_ids, commit=False)
                        logger.info(
                            "Remplacement de %d acte(s) existant(s) pour %s (IDs: %s).",
                            deleted_count,
                            img_path.name,
                            old_act_ids,
                        )
                    created_act_ids = repo.save_acts(acts_for_image)
                finally:
                    session.close()
            else:
                if old_act_ids:
                    logger.info(
                        "  [DRY-RUN] Supprimerait %d acte(s) existant(s) pour %s (IDs: %s).",
                        len(old_act_ids),
                        img_path.name,
                        old_act_ids,
                    )
                logger.info(
                    "  [DRY-RUN] %d acte(s) prêt(s) à persister.", len(acts_for_image)
                )

            created_acts_total += len(acts_for_image)
            processed_count += 1

            # 4. Mettre à jour le registre
            if not dry_run:
                ledger[rel_key] = {
                    "path": str(img_path),
                    "sha256": sha256,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "num_segments": len(segments),
                    "num_acts_created": len(acts_for_image),
                    "act_ids": created_act_ids,
                    "status": "OK",
                    "error_message": None,
                    "is_simulated": is_img_simulated,
                    "needs_human_review": needs_review,
                }
                save_ledger(ledger, ledger_path)

        except Exception as exc:
            has_error = True
            failed_count += 1
            logger.warning("Échec du traitement de l'image %s : %s", img_path.name, exc)
            if not dry_run:
                ledger[rel_key] = {
                    "path": str(img_path),
                    "sha256": sha256,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "num_segments": 0,
                    "num_acts_created": 0,
                    "act_ids": [],
                    "status": "FAILED",
                    "error_message": str(exc),
                    "is_simulated": False,
                    "needs_human_review": False,
                }
                save_ledger(ledger, ledger_path)

    # ------------------------------------------------------------------ Rapport final
    print("\n" + "=" * 78)
    print("RAPPORT DE TRAITEMENT PAR LOT — CERTUS GENEALOGY")
    print("=" * 78)
    print(f"  Images traitées avec succès : {processed_count}")
    print(f"  Images sautées (idempotence): {skipped_count}")
    print(f"  Images en échec             : {failed_count}")
    print(f"  Total d'actes créés         : {created_acts_total}")
    print(f"  Actes marqués is_simulated  : {simulated_acts_total}")
    print(f"  Mode exécution              : {'DRY-RUN (aucune écriture DB)' if dry_run else 'RÉEL'}")
    if review_needed_images:
        print("-" * 78)
        print(f"  Images nécessitant une relecture humaine ({len(review_needed_images)}) :")
        for img_name in review_needed_images:
            print(f"    - {img_name}")
    print("=" * 78)

    return 1 if has_error else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline de transcription par lot des registres d'archives CERTUS-GENEALOGY."
    )
    parser.add_argument(
        "--source", required=True, help="Répertoire ou fichier des scans d'archives (obligatoire)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Ne traiter que les N premières images non traitées"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Exécute sans écrire en DB ni dans le registre"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Reprendre en sautant les images déjà traitées (par défaut)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forcer le retraitement même pour les images déjà traitées",
    )
    parser.add_argument(
        "--delay", type=float, default=0.0, help="Pause en secondes entre deux images (défaut 0)"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    return process_batch(
        source_dir=args.source,
        limit=args.limit,
        dry_run=args.dry_run,
        resume=args.resume,
        force=args.force,
        delay=args.delay,
    )


if __name__ == "__main__":
    sys.exit(main())
