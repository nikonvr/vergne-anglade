# CERTUS-GENEALOGY

Reconstruction généalogique **sourcée** d'une branche familiale : import d'un fichier
GEDCOM, collecte d'actes auprès de sources d'archives, consolidation des personnes en
un graphe de filiation, puis publication d'une page HTML autonome et d'exports
(GEDCOM, JSON, Mermaid).

Le projet est structuré autour d'une règle centrale : **une donnée publiée doit être
traçable jusqu'à sa source**. Voir la section
[Provenance et fiabilité des données](#provenance-et-fiabilité-des-données).

Les patronymes de la branche étudiée ne sont pas dispersés dans le code : ils sont
définis une seule fois dans `src/genealogy/variants.py` (`BRANCH_SURNAMES`).

---

## Architecture

```
.
├── src/
│   ├── core/
│   │   ├── models.py             Modèles Pydantic du domaine : Act, Person, SearchQuery
│   │   ├── simulation.py         Garde-fou anti-fabrication (CERTUS_ALLOW_SIMULATED)
│   │   ├── orchestrator.py       Chaîne de traitement OCR → LLM → base → arbre
│   │   └── meta_orchestrator.py  Recherche parallèle sur toutes les sources déclarées
│   ├── crawler/
│   │   ├── base.py               Base abstraite des robots d'archives départementales
│   │   ├── factory.py            Fabrique : enregistrement d'un robot par code de département
│   │   ├── cantal.py             Robot département 15
│   │   ├── puy_de_dome.py        Robot département 63
│   │   ├── gallica.py            Client SRU de la presse historique Gallica / BnF
│   │   └── adapters.py           Adaptateurs de recherche unifiés (Gallica, CSV, Geneanet)
│   ├── parser/
│   │   ├── gedcom_importer.py    Import GEDCOM filtré sur les patronymes de la branche
│   │   ├── csv_importer.py       Import de relevés associatifs au format CSV
│   │   └── llm.py                Extraction sémantique optionnelle d'un acte par LLM
│   ├── ocr/
│   │   └── florence.py           Prétraitement des images de registres (OpenCV, sinon PIL)
│   ├── genealogy/
│   │   ├── models.py             ConsolidatedPerson, Relationship, FamilyTree
│   │   ├── builder.py            TreeBuilder : consolidation des personnes, graphe networkx
│   │   └── variants.py           Patronymes de la branche et variantes orthographiques
│   ├── database/
│   │   ├── engine.py             DatabaseManager : moteur, sessions, init_db + migration légère
│   │   ├── models.py             Tables SQLAlchemy DBAct / DBPerson
│   │   └── repository.py         ActRepository : lecture et écriture des actes
│   ├── export/
│   │   ├── gedcom.py             Export GEDCOM 5.5.1 et diagramme Mermaid
│   │   └── html_report.py        Rapport généalogique HTML imprimable
│   ├── api/
│   │   └── main.py               Application FastAPI + WebSocket de progression
│   └── gui/
│       └── index.html            Interface d'administration servie par l'API
├── scripts/
│   ├── build_standalone.py       Génère la page publique autonome
│   └── daily_archival_cron.py    Veille quotidienne puis régénération de la page publique
├── tests/                        Suite pytest
├── index.html                    Page publiée par GitHub Pages (artefact versionné)
├── vergne_genealogy_standalone.html  Page publique autonome (artefact versionné)
└── certus_genealogy.db           Base SQLite locale (artefact régénérable, non versionné)
```

Flux de données typique :

```
GEDCOM / CSV / archives  ──►  parser, crawler  ──►  Act + Person (Pydantic)
                                                          │
                                                          ▼
                                              ActRepository  ──►  SQLite
                                                          │
                                                          ▼
                                        TreeBuilder  ──►  FamilyTree (graphe networkx)
                                                          │
                                       ┌──────────────────┴──────────────────┐
                                       ▼                                     ▼
                              API FastAPI + IHM                  page publique + exports
```

---

## Prérequis

- Python **3.11 ou plus récent**
- [uv](https://docs.astral.sh/uv/) (recommandé) ou `pip`
- Un fichier GEDCOM source pour alimenter la base (voir `CERTUS_GEDCOM_PATH`)
- Optionnel : OpenCV/Pillow pour le prétraitement d'images, une clé d'API LLM pour
  l'analyse sémantique des transcriptions

Aucun service externe n'est nécessaire pour lancer l'API ou les tests : le stockage par
défaut est un fichier SQLite local.

---

## Installation

Avec `uv` :

```bash
uv venv
uv pip install -e ".[dev]"
```

Avec `pip` :

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate # Linux / macOS
pip install -e ".[dev]"
```

Les dépendances de fonctionnement (`pydantic`, `sqlalchemy`, `networkx`, `fastapi`,
`uvicorn`, `rapidfuzz`) sont **obligatoires** et installées par défaut. Les extras sont
optionnels :

| Extra | Contenu | Utilité |
|-------|---------|---------|
| `dev` | pytest, pytest-timeout, anyio, httpx, ruff, black, mypy | tests et qualité de code |
| `ocr` | opencv-python, numpy, Pillow, torch, transformers | prétraitement des images de registres |
| `llm` | openai | analyse sémantique optionnelle d'une transcription |

```bash
uv pip install -e ".[dev,ocr]"     # tests + prétraitement d'images
```

---

## Variables d'environnement

Toutes les variables sont facultatives : chacune possède une valeur par défaut
utilisable en développement.

| Variable | Rôle | Défaut |
|----------|------|--------|
| `CERTUS_GEDCOM_PATH` | Chemin du fichier GEDCOM source. | chemin local du poste d'origine, à redéfinir sur toute autre machine |
| `CERTUS_DB_URL` | URL SQLAlchemy de la base. | `sqlite:///certus_genealogy.db` |
| `CERTUS_API_TOKEN` | Jeton `Bearer` exigé par les endpoints mutants. Non défini, ces endpoints sont désactivés et répondent `503`. | *(non défini)* |
| `CERTUS_CORS_ORIGINS` | Origines autorisées par CORS, séparées par des virgules. | `http://localhost:8000,http://127.0.0.1:8000` |
| `CERTUS_ALLOWED_DIRS` | Racines autorisées pour les chemins de fichiers fournis par un client, séparées par `os.pathsep`. | répertoire courant + répertoire parent de `CERTUS_GEDCOM_PATH` |
| `CERTUS_ALLOW_SIMULATED` | `1` pour autoriser les sources simulées (voir plus bas). | désactivé |
| `CERTUS_OCR_OUTPUT_DIR` | Répertoire des images prétraitées. | `.certus_cache/preprocessed` |

La valeur par défaut de `CERTUS_GEDCOM_PATH` désigne un fichier présent sur le poste
d'origine du fonds : sur toute autre machine (autre poste, intégration continue), la
variable doit être définie explicitement, sans quoi les traitements qui dépendent du
GEDCOM signalent que la source est introuvable au lieu de produire un arbre vide.

Variables propres à l'analyse LLM optionnelle (`src/parser/llm.py`) :
`OPENAI_API_KEY`, `LLM_MODEL`, `LLM_API_BASE`.

Les identifiants de l'adaptateur Geneanet sont lus depuis `GENEANET_USERNAME` et
`GENEANET_PASSWORD` ; aucun identifiant n'est écrit en dur dans le code.

---

## Lancer l'API

```bash
uvicorn src.api.main:app --reload --port 8000
```

| Route | Description |
|-------|-------------|
| `GET /` | Interface d'administration (`src/gui/index.html`) |
| `GET /standalone` | Page publique autonome |
| `GET /api/stats` | Compteurs globaux calculés depuis la base |
| `GET /api/tree` | Arbre consolidé (nœuds et relations) |
| `GET /api/relationship` | Analyse du lien de parenté entre deux personnes |
| `GET /api/acts/recent` | Liste des actes |
| `GET /api/acts/{act_id}` | Détail d'un acte par sa clé primaire |
| `GET /api/export/json` | Graphe au format JSON |
| `GET /api/export/mermaid` | Diagramme Mermaid |
| `GET /api/export/gedcom` | Téléchargement d'un fichier GEDCOM |
| `POST /api/search` | Recherche multi-sources |
| `POST /api/pipeline/process` | Traitement d'une image de registre |
| `POST /api/import/gedcom` | Import d'un fichier GEDCOM |
| `WS /ws/progress` | Progression du traitement en temps réel |

Les endpoints mutants (`POST`) exigent l'en-tête `Authorization: Bearer <CERTUS_API_TOKEN>`.
Tant que `CERTUS_API_TOKEN` n'est pas défini, ils restent désactivés.

Documentation interactive générée par FastAPI : <http://localhost:8000/docs>.

---

## Régénérer la page publique

```bash
python scripts/build_standalone.py
```

Le script relit la base, reconstruit l'arbre et réécrit les artefacts publiés
`vergne_genealogy_standalone.html` et `index.html`. Ces deux fichiers sont
**volontairement versionnés** : ils constituent le site GitHub Pages.

La veille quotidienne complète (recherche en ligne, puis régénération) :

```bash
python scripts/daily_archival_cron.py
```

Le workflow `.github/workflows/daily_update.yml` exécute cette veille chaque nuit. Il
lance d'abord la suite de tests, puis **saute la régénération et la publication** si le
GEDCOM source est introuvable sur le runner : `index.html` n'est jamais écrasé par un
arbre vide. La base SQLite n'est pas publiée.

---

## Traitement par lot des registres d'archives

Le script `scripts/batch_transcribe.py` permet d'exécuter le pipeline de transcription par lot, idempotent et reprenable, sur un répertoire de scans de registres :

```bash
# Traitement par lot sur un répertoire d'images d'archives
python scripts/batch_transcribe.py --source /chemin/vers/scans

# Exécution en mode simulation / validation sans écriture en base (--dry-run)
python scripts/batch_transcribe.py --source /chemin/vers/scans --limit 5 --dry-run

# Forcer le retraitement d'images déjà enregistrées au registre (--force)
python scripts/batch_transcribe.py --source /chemin/vers/scans --force
```

Le script s'appuie sur le registre JSON `.certus_cache/batch_ledger.json` (ou `CERTUS_BATCH_LEDGER`) pour mémoriser les empreintes SHA-256 des images et les identifiants d'actes créés, garantissant ainsi qu'aucun doublon n'est généré lors de réexécutions successives.

---

## Tests

```bash
python -m pytest
```

La configuration pytest se trouve dans `pyproject.toml` (`testpaths = ["tests"]`,
`pythonpath = ["."]`). Chaque test dispose d'un délai maximal de 120 secondes
(`pytest-timeout`) : un dépassement signale un test bloqué, la suite complète devant
rester rapide. Les tests utilisent une base SQLite temporaire distincte de la base de
travail.

Qualité de code :

```bash
ruff check .
mypy src
```

---

## Provenance et fiabilité des données

Le projet distingue strictement une **donnée sourcée** d'une **donnée simulée**. Aucun
composant n'a le droit d'inventer une information et de la présenter comme un relevé
d'archives.

Règles appliquées :

1. **Échec explicite plutôt qu'invention.** Un composant incapable de produire une
   donnée réelle (moteur OCR non branché, téléchargement d'archives non implémenté,
   source injoignable) lève une exception claire. Il ne retourne jamais une valeur
   « plausible ».
2. **Simulation désactivée par défaut.** Le mode simulation n'est autorisé que si
   `CERTUS_ALLOW_SIMULATED=1`. Sinon, les composants concernés lèvent
   `SimulationDisabledError` (`src/core/simulation.py`).
3. **Marquage obligatoire.** Toute donnée produite en mode simulé porte :
   - `is_simulated=True` sur l'acte ;
   - un `source_type` préfixé par `SIMULATED_` ;
   - `confidence_score = 0.0` et `reliability_score = 0.0`.
4. **Pas de comblement des trous.** Une date, un lieu, une URL de source ou un texte
   d'acte absent reste absent : il n'est jamais remplacé par une valeur par défaut
   vraisemblable, ni dans la base, ni dans les exports, ni dans la page publique.
5. **Aucune donnée simulée en production.** Le workflow de veille force
   `CERTUS_ALLOW_SIMULATED=0`.

En conséquence, la page publique et les exports n'affichent un indice de confiance ou
une référence de source que lorsque l'information existe réellement en base.

---

## Licence

Distribué sous licence MIT. Voir le fichier [LICENSE](LICENSE).

Le code est sous licence MIT ; les documents d'archives et les données généalogiques du
fonds familial ne sont pas couverts par cette licence et ne sont pas versionnés dans ce
dépôt (voir `.gitignore`).
