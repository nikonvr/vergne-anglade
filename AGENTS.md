# AGENTS.md — Corridor de codage CERTUS-GENEALOGY

**Ce fichier fait autorité.** Il prévaut sur toute habitude, tout raccourci et toute
supposition. Si une consigne ici contredit ce que vous jugez élégant, appliquez la consigne.

Ce projet reconstruit une généalogie à partir de registres d'archives. La donnée produite
sert de **preuve** : une donnée inventée est bien plus nuisible qu'une donnée absente. Toutes
les règles ci-dessous découlent de cette phrase.

---

## 1. Les six règles non négociables

| # | Règle | Pourquoi elle existe |
|---|---|---|
| **R1** | **Ne jamais fabriquer de donnée.** Aucune valeur de repli inventée : ni date, ni lieu, ni nom, ni URL de source, ni score de confiance. En cas d'impossibilité, **lever une exception** ou retourner `None`/liste vide, jamais une valeur plausible. | Le code affichait 334 actes comme sourcés alors qu'aucun ne l'était : URL d'archives en repli, transcription inventée, confiance à 0,95 par défaut. |
| **R2** | **Toute donnée non sourcée porte `is_simulated=True`**, un `source_type` préfixé `SIMULATED_`, et `confidence_score=0.0` / `reliability_score=0.0`. La simulation n'existe que si `CERTUS_ALLOW_SIMULATED=1`. | Une donnée de démonstration devenue indiscernable d'une preuve corrompt tout le fonds. |
| **R3** | **L'identité d'une personne repose sur `source_id`**, jamais sur son nom. Deux personnes de même nom sont deux personnes. | 27 individus réels étaient fusionnés en 15 nœuds ; 7 personnes distinctes portant le même nom n'en formaient qu'une, créant des cycles où un individu était son propre ancêtre. |
| **R4** | **Aucun secret dans le code.** Jamais de littéral en valeur par défaut de `os.environ.get`. | Un couple identifiant/mot de passe a été poussé sur le dépôt distant. |
| **R5** | **Aucun échec silencieux.** `except: pass` est interdit. Journalisez au minimum en `WARNING`, avec le nom du composant fautif. | Un import GEDCOM en échec était indistinguable d'un import vide. |
| **R6** | **Les patronymes se définissent dans `src/genealogy/variants.py`, nulle part ailleurs.** | La liste était recopiée dans quatre fichiers, qui ont divergé. |

---

## 2. Règles métier du fonds — décisions du propriétaire

Ces règles ne sont **pas** déductibles du code ni des données. Elles ont été arbitrées
explicitement. **Ne les modifiez jamais de votre propre initiative.**

### 2.1 Patronymes

| Décision | Détail |
|---|---|
| `VERGNES` **est** une variante de `VERGNE` | même lignée, fusionne à la consolidation |
| `JEHL` **et** `IEHL` sont **le même nom** | fusionnent à la consolidation |
| `LAVERGNE` et `LEVERGNE` ne sont **PAS** des variantes de `VERGNE` | familles **distinctes**, exclues du fonds. Codé dans `NOT_BRANCH_SURNAMES` |
| `BRUNET`, `BRUNEAU`, `BRUNSTEIN`, `LANGLADE`… | patronymes **distincts**, jamais assimilés à `BRUN` ou `ANGLADE` |

La comparaison des patronymes est **EXACTE**, au groupe de variantes près. La comparaison
par sous-chaîne est **interdite** : `"VERGNE" in "LAVERGNE"` est vrai et rattachait
15 individus étrangers au fonds.

### 2.2 Personnes vivantes

Le fonds publié contient des personnes vraisemblablement vivantes (12 individus nés entre
1951 et 1994). **C'est une décision assumée du propriétaire.**

- **N'ajoutez aucun filtre** de confidentialité, d'anonymisation ou de masquage.
- **Ne retirez pas** un filtre existant s'il en apparaissait un.
- Toute évolution sur ce point exige une **décision explicite du propriétaire**, pas une
  initiative d'agent, dans un sens comme dans l'autre.

### 2.3 Parenté spirituelle

Un **parrain**, une **marraine** ou un **témoin** ne créent **jamais** de lien de filiation,
même s'ils portent le même patronyme que l'enfant : c'est très fréquemment un oncle ou un
grand-parent. Utilisez `src.ocr.bms.creates_filiation()`.

---

## 3. Où modifier quoi

**Cherchez votre besoin dans ce tableau avant d'ouvrir un fichier.** Modifier ailleurs
duplique une source de vérité et sera rejeté par les invariants.

| Besoin | Fichier unique à modifier |
|---|---|
| Ajouter/retirer un patronyme, une variante, une exclusion | `src/genealogy/variants.py` |
| Vocabulaire des actes : formules, rôles, abréviations, mois, métiers | `src/ocr/bms.py` |
| Prompts de transcription et d'extraction | `src/ocr/bms.py` |
| Ajouter un moteur de transcription | `src/ocr/backends/<nom>.py` + import dans `backends/__init__.py` |
| Logique de consensus entre moteurs | `src/ocr/htr.py` |
| Prétraitement d'image | `src/ocr/florence.py` |
| Lecture du GEDCOM source | `src/parser/gedcom_importer.py` |
| Identité et fusion des individus | `src/genealogy/builder.py` |
| Écriture du GEDCOM exporté | `src/export/gedcom.py` |
| Schéma de données | `src/core/models.py` puis `src/database/models.py` |
| Migration de base | `src/database/engine.py` (`_ensure_columns`) |
| Endpoints HTTP | `src/api/main.py` |
| Page publique | `scripts/build_standalone.py` — **jamais `index.html` à la main** |
| Un nouvel invariant à faire respecter | `scripts/check_invariants.py` |

---

## 4. Rituel de vérification — obligatoire avant de conclure

Exécutez **les trois** commandes, dans cet ordre. Ne déclarez jamais une tâche terminée sans
les avoir passées.

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe scripts/check_invariants.py
```

```bash
CERTUS_GEDCOM_PATH="D:/drivefl/gene/2022/2026-02_export.ged" .venv/Scripts/python.exe -m scripts.build_standalone
```

Repères actuels, à ne pas dégrader :

| Indicateur | Valeur de référence |
|---|---|
| Tests | **118 passés, < 20 s** |
| Invariants | **9 sur 9 respectés** |
| Individus consolidés | 233 |
| Liens de filiation | 316 |
| Actes | 293 |
| Graphe acyclique | **oui, 0 cycle** |
| Xrefs GEDCOM invalides | **0** |

Si le nombre de tests baisse, vous avez supprimé une protection. Si la durée explose, vous
avez réintroduit un accès au fonds GEDCOM de 2,2 Mo dans une fixture.

---

## 5. Pièges connus de ce dépôt

1. **`attic/build_certus.py`** — ne l'exécutez **jamais**. Ce générateur réécrit des versions
   périmées de 13 fichiers source (son `process_acts` retourne un arbre vide). Il est
   conservé pour mémoire, hors du chemin d'exécution.
2. **`index.html` est un artefact généré.** Toute modification manuelle sera écrasée au
   prochain build. Modifiez `scripts/build_standalone.py`.
3. **Le cache d'arbre est un attribut de classe** (`CertusOrchestrator._tree_cache`) alors que
   le graphe `networkx` vit sur l'instance du `TreeBuilder`. Servir l'arbre en cache **sans
   son builder** vide le graphe et rend toute analyse de parenté muette. Appelez
   `reset_tree_cache()` entre deux tests.
4. **`SearchQuery` refuse les champs inconnus** (`extra="forbid"`). Le champ est `last_name`,
   pas `surname`. Un mauvais nom lève désormais au lieu d'être ignoré.
5. **Les dates GEDCOM restent brutes** (`"21 FEB 1972"`, `"an IV"`). Ne les normalisez pas en
   ISO : la fidélité à la source primerait toujours sur le confort de tri.
6. **Les lieux sont des chemins à virgules** (`"Ville,CP,Département,Région,PAYS,"`). Pour
   l'affichage, ne gardez que le premier segment.
7. **`src/ocr/florence.py` porte un nom trompeur** : aucun modèle Florence-2 n'a jamais été
   branché. `HTREngine` est l'alias canonique. Renommer le module est souhaitable, mais
   c'est un changement transverse à faire d'un seul coup.
8. **Python 3.14 diffère** : les annotations y sont évaluées tardivement. Un symbole de
   `typing` non importé passe inaperçu en local et casse à l'import en 3.11, que cible la CI.
   `inspect.signature` sur vos classes publiques révèle le problème.

---

## 6. Lire les registres — état réel et feuille de route

### 6.1 Ce qui existe aujourd'hui

Le prétraitement d'image est **réel** (CLAHE + filtrage médian sous OpenCV, repli PIL).
Le socle multi-moteurs est **en place** : protocole, registre, consensus, diagnostic.

**Aucun moteur n'est actif par défaut.** Vérifiez toujours l'état réel avant de conclure :

```bash
.venv/Scripts/python.exe -m src.ocr.htr
```

Cette commande liste chaque moteur, dit s'il est utilisable, et **pourquoi** il ne l'est pas.

| Moteur | État | Pour l'activer |
|---|---|---|
| `claude_vision` | **implémenté** | définir `ANTHROPIC_API_KEY` |
| `simulated` | implémenté, tests uniquement | `CERTUS_ALLOW_SIMULATED=1` |
| `transkribus` | **à implémenter** | compte READ Coop + appel REST |
| `kraken` | **à implémenter** | modèle local + segmentation |
| `tesseract` | **à implémenter** | binaire présent ; **imprimé seulement** |

### 6.2 Pourquoi ces registres sont difficiles

- Avant **1737**, les actes sont fréquemment en **latin**.
- De **1793 à 1805**, les dates suivent le **calendrier républicain** (« 12 vendémiaire an IV »).
- L'orthographe n'est pas fixée : un même patronyme varie d'un acte à l'autre.
- Les **abréviations par suspension** sont massives (`led.`, `Dlle`, `fs`).
- L'encre traverse le papier ; les pages sont gondolées, tachées, parfois délavées.

C'est pourquoi `src/ocr/bms.py` existe : **le contexte pèse plus que le moteur.** Une graphie
ambiguë se résout par la formule attendue, non par un meilleur modèle.

### 6.3 Feuille de route, par ordre de rendement décroissant

1. **Découpage acte par acte.** Le gain le plus important, et de loin. Les services de vision
   redimensionnent les images au-delà d'environ 1568 px sur le grand côté : sur une page
   entière, le détail des jambages disparaît. Segmentez la page en bandes horizontales (les
   actes sont empilés verticalement) et transcrivez chaque acte séparément.
   → à ajouter dans `src/ocr/florence.py`, exposé comme `segment_acts(image) -> list[Path]`.
2. **Un second moteur, pour le consensus.** Avec un seul moteur, `agreement` n'est pas mesuré
   mais déclaré. `transkribus` est le meilleur candidat : ses modèles publics couvrent le
   français des 17e-18e siècles. Deux moteurs suffisent à obtenir une confiance réelle.
3. **Variantes de prétraitement.** Produire 2-3 binarisations (seuil global, adaptatif,
   correction d'inclinaison) et les soumettre au même moteur : les désaccords révèlent les
   passages fragiles. → `preprocess_variants(image) -> list[Path]`.
4. **Validation humaine assistée.** `ConsensusResult.needs_human_review` signale déjà les
   transcriptions douteuses. Il manque l'écran de relecture : afficher les variantes côte à
   côte et laisser l'humain trancher. Sur ces écritures, **la relecture n'est pas un luxe.**
5. **Boucle de retour.** Les corrections humaines constituent un corpus de vérité, exploitable
   pour affiner un modèle Kraken local.

### 6.4 Règles impératives du pipeline de lecture

- Un moteur qui ne peut pas lire **lève une exception**. Il ne retourne jamais de texte
  inventé, ni une chaîne vide silencieuse (**R1**).
- Le score de confiance vient de l'**accord mesuré entre moteurs**, jamais d'une constante.
- Les incertitudes du modèle doivent rester **visibles** : `[illisible]` et `(?)` sont
  transportés jusqu'à l'interface, pas nettoyés.
- Ne « corrigez » jamais une transcription vers un patronyme du fonds. Les patronymes fournis
  au modèle sont une **aide à la lecture**, pas une contrainte.

---

## 7. Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `CERTUS_GEDCOM_PATH` | fonds GEDCOM source | `D:/drivefl/gene/2022/2026-02_export.ged` |
| `CERTUS_DB_URL` | base SQLAlchemy | `sqlite:///certus_genealogy.db` |
| `CERTUS_API_TOKEN` | jeton Bearer des endpoints mutants | **non défini → endpoints désactivés (503)** |
| `CERTUS_CORS_ORIGINS` | origines autorisées, séparées par des virgules | `http://localhost:8000,http://127.0.0.1:8000` |
| `CERTUS_ALLOWED_DIRS` | racines autorisées pour un chemin fourni par le client | répertoire courant + dossier du GEDCOM |
| `CERTUS_ALLOW_SIMULATED` | autorise les sources simulées | désactivé |
| `CERTUS_HTR_BACKENDS` | moteurs, par ordre de préférence | `claude_vision,simulated` |
| `CERTUS_HTR_MAX_EDGE` | réduction avant envoi au moteur de vision | `1568` |
| `CERTUS_OCR_OUTPUT_DIR` | images prétraitées | `.certus_cache/preprocessed` |
| `CERTUS_SEGMENT_MIN_GAP` | hauteur minimale (px) d'une bande blanche séparatrice d'actes | `20` |
| `CERTUS_SEGMENT_MIN_HEIGHT` | hauteur minimale (px) d'un acte découpé retenu | `50` |
| `CERTUS_SEGMENT_MARGIN_RATIO` | ratio des marges latérales à ignorer pour la détection de la zone de texte | `0.15` |
| `CERTUS_SEGMENT_GAP_FACTOR` | facteur multiplicateur d'écart adaptatif pour la séparation des actes | `2.0` |
| `CERTUS_BATCH_LEDGER` | chemin du registre JSON de suivi des traitements par lot | `.certus_cache/batch_ledger.json` |
| `ANTHROPIC_API_KEY` | moteur `claude_vision` et extraction | — |

---

## 8. Style

- **Commentaires, messages d'erreur et journaux en français.** L'interface aussi.
- Un commentaire explique **pourquoi**, pas **quoi**. Quand vous corrigez un défaut,
  mentionnez le comportement fautif : c'est ce qui empêche sa réapparition.
- Type hints sur toute fonction publique. Vérifiez que chaque symbole `typing` est importé.
- Pas de fonction de plus de 50 lignes sans raison ; pas de classe fourre-tout.
- Ne créez pas de fichier de documentation supplémentaire : enrichissez ceux qui existent.

---

## 9. Si vous êtes bloqué

1. Relisez la section 3 : votre besoin correspond-il à un fichier unique ?
2. Lancez le rituel de vérification (section 4) — l'erreur y est souvent déjà décrite.
3. Lancez `python -m src.ocr.htr` si le sujet touche la lecture des registres.
4. En cas de doute sur une **règle métier** (patronymes, personnes vivantes, filiation),
   **arrêtez-vous et demandez au propriétaire.** Ne tranchez pas seul : ces arbitrages
   engagent la validité de la généalogie, pas seulement la qualité du code.
