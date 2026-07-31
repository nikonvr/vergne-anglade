# CLAUDE.md

**Lisez [AGENTS.md](AGENTS.md) : il fait autorité sur ce dépôt.** Ce fichier n'en est qu'un
rappel, destiné aux outils qui chargent `CLAUDE.md` automatiquement.

## Les six règles non négociables

1. **Ne jamais fabriquer de donnée.** Pas de valeur de repli inventée — ni date, ni lieu, ni
   nom, ni URL de source, ni score de confiance. En cas d'impossibilité : lever une exception.
2. **Toute donnée non sourcée** porte `is_simulated=True`, un `source_type` préfixé
   `SIMULATED_` et des scores à `0.0`. La simulation exige `CERTUS_ALLOW_SIMULATED=1`.
3. **L'identité repose sur `source_id`**, jamais sur le nom. Deux homonymes sont deux personnes.
4. **Aucun secret dans le code**, jamais en valeur par défaut de `os.environ.get`.
5. **Aucun `except: pass`.** Journalisez au minimum en `WARNING`.
6. **Les patronymes se définissent dans `src/genealogy/variants.py`, nulle part ailleurs.**

## Décisions du propriétaire — ne pas modifier de sa propre initiative

- `VERGNES` est une variante de `VERGNE` ; `JEHL` et `IEHL` sont le même nom.
- `LAVERGNE` et `LEVERGNE` sont des familles **distinctes**, exclues du fonds.
- Comparaison des patronymes **exacte** — jamais par sous-chaîne.
- Les **personnes vivantes restent publiées** : n'ajoutez aucun filtre d'anonymisation.
- Un **parrain ou témoin ne crée jamais de filiation**.

## Avant de conclure une tâche

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe scripts/check_invariants.py
```

Références à ne pas dégrader : **118 tests en moins de 20 s**, **9 invariants sur 9**,
233 individus, 316 liens, graphe acyclique, 0 xref GEDCOM invalide.

## Pièges immédiats

- N'exécutez **jamais** `attic/build_certus.py` : il réécrit du code périmé.
- `index.html` est **généré** — modifiez `scripts/build_standalone.py`.
- Le champ de recherche est `last_name`, pas `surname` (`extra="forbid"`).
- État réel de la lecture de registres : `python -m src.ocr.htr`.
