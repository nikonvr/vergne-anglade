"""Connaissance métier des registres paroissiaux BMS (baptêmes, mariages, sépultures).

Ce module ne contient aucune dépendance ni aucun appel réseau : c'est le socle de
vocabulaire utilisé pour guider la reconnaissance d'écriture manuscrite (HTR) et
l'extraction structurée. Sur les mains d'Ancien Régime, ce contexte pèse davantage sur le
résultat que le choix du moteur : une graphie ambiguë se résout par la formule attendue.

Sources de la difficulté, à connaître avant de toucher au pipeline :
  - avant 1737 les actes sont fréquemment en LATIN, ensuite en français ;
  - les dates sont écrites en toutes lettres, et de 1793 à 1805 dans le calendrier
    républicain (« le 12 vendémiaire an IV ») ;
  - l'orthographe n'est pas fixée : un même patronyme varie d'un acte à l'autre ;
  - les abréviations par suspension sont massives (« led. », « Dlle », « fs ») ;
  - l'encre traverse le papier et les registres sont souvent gondolés ou tachés.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List

from src.genealogy.variants import BRANCH_SURNAMES

# --------------------------------------------------------------------------------------
# Types d'actes et formules déclenchantes. Les clés servent de valeur canonique pour
# Act.act_type ; les listes servent d'indices de détection et de guidage du modèle.
# --------------------------------------------------------------------------------------
#
# Deux régimes coexistent dans le fonds : les registres PAROISSIAUX (baptême, mariage,
# sépulture) jusqu'en 1792, puis l'ÉTAT CIVIL (naissance, mariage, décès). Les deux
# vocabulaires doivent être reconnus.
ACT_TYPE_CUES: Dict[str, List[str]] = {
    "naissance": [
        "est né", "est née", "sont nés", "naissance", "né le", "née le",
        "nous a présenté un enfant", "déclaration de naissance",
    ],
    "décès": [
        "décès", "est décédé", "est décédée", "acte de décès", "constaté le décès",
        "déclaration de décès",
    ],
    "baptême": [
        "baptême", "baptesme", "a été baptisé", "a esté baptisée", "né et baptisé",
        "parrain", "marraine",
        # Latin
        "baptizatus", "baptizata", "baptismi", "patrinus", "matrina",
    ],
    "mariage": [
        "mariage", "épousé", "espousé", "ont contracté mariage", "fiançailles",
        "en présence de", "publication des bans", "dispense de bans",
        # Latin
        "matrimonium", "contraxerunt", "coniuges", "sponsus", "sponsa",
    ],
    "sépulture": [
        "sépulture", "sepulture", "inhumé", "inhumée", "a été enterré", "décédé",
        "corps de", "cimetière",
        # Latin
        "sepultus", "sepulta", "obiit", "defunctus",
    ],
}

# --------------------------------------------------------------------------------------
# Rôles rencontrés dans les actes. La valeur est le rôle canonique attendu par
# src/genealogy/builder.py pour établir les filiations (« père », « mère », « enfant »).
# --------------------------------------------------------------------------------------
ROLE_SYNONYMS: Dict[str, str] = {
    # Filiation — seuls ces rôles créent une arête dans le graphe.
    "fils": "enfant", "fille": "enfant", "enfant": "enfant",
    "filius": "enfant", "filia": "enfant",
    "père": "père", "pere": "père", "pater": "père", "patris": "père",
    # matris est le génitif de mater : c'est bien la MÈRE.
    "mère": "mère", "mere": "mère", "mater": "mère", "matris": "mère",
    # Mariage
    "époux": "époux", "espoux": "époux", "marié": "époux", "sponsus": "époux",
    "épouse": "épouse", "espouse": "épouse", "mariée": "épouse", "sponsa": "épouse",
    # Sépulture
    "défunt": "défunt", "défunte": "défunt", "defunctus": "défunt",
    # Témoins et parenté spirituelle : conservés comme mentions, sans filiation.
    "parrain": "parrain", "patrinus": "parrain",
    "marraine": "marraine", "matrina": "marraine",
    "témoin": "témoin", "temoin": "témoin", "testis": "témoin",
    "curé": "officiant", "vicaire": "officiant", "prêtre": "officiant",
    "presbyter": "officiant", "officiant": "officiant",
}

# Rôles qui NE doivent PAS produire de lien de filiation, même s'ils désignent un parent
# spirituel. Un parrain est très souvent un oncle : le confondre avec un père fabrique une
# filiation fausse.
NON_FILIATION_ROLES = ("parrain", "marraine", "témoin", "officiant")

# --------------------------------------------------------------------------------------
# Abréviations par suspension, omniprésentes dans les registres.
# --------------------------------------------------------------------------------------
ABBREVIATIONS: Dict[str, str] = {
    "led.": "ledit", "ledt": "ledit", "lad.": "ladite", "ladte": "ladite",
    "fs": "fils", "fe": "femme", "ve": "veuve", "vve": "veuve",
    "Sr": "sieur", "Sieur": "sieur", "Dlle": "demoiselle", "Dme": "dame",
    "Me": "maître", "Mre": "maître", "Msr": "monsieur",
    "St": "saint", "Ste": "sainte",
    "pnt": "présent", "presens": "présents",
    "susd.": "susdit", "susdt": "susdit",
    "hon.": "honorable", "hble": "honorable",
    "deced.": "décédé", "dccd": "décédé",
}

# --------------------------------------------------------------------------------------
# Mois : graphies anciennes du calendrier grégorien, puis calendrier républicain
# (22 septembre 1793 - 31 décembre 1805), indispensable pour la période révolutionnaire.
# --------------------------------------------------------------------------------------
OLD_MONTH_SPELLINGS: Dict[str, str] = {
    "janvier": "01", "febvrier": "02", "fevrier": "02", "février": "02",
    "mars": "03", "avril": "04", "may": "05", "mai": "05", "juin": "06",
    "juillet": "07", "aoust": "08", "août": "08", "aout": "08",
    "septembre": "09", "7bre": "09", "octobre": "10", "8bre": "10",
    "novembre": "11", "9bre": "11", "decembre": "12", "décembre": "12", "10bre": "12",
    "xbre": "12",
}

REPUBLICAN_MONTHS: List[str] = [
    "vendémiaire", "brumaire", "frimaire",
    "nivôse", "pluviôse", "ventôse",
    "germinal", "floréal", "prairial",
    "messidor", "thermidor", "fructidor",
]

# Jours complémentaires en fin d'année républicaine.
REPUBLICAN_COMPLEMENTARY_DAYS = "sansculottides"

# --------------------------------------------------------------------------------------
# Métiers anciens : lexique de désambiguïsation. Une graphie douteuse se tranche souvent
# par le métier attendu dans la région et l'époque.
# --------------------------------------------------------------------------------------
ANCIENT_OCCUPATIONS: List[str] = [
    "laboureur", "brassier", "manouvrier", "cultivateur", "ménager", "journalier",
    "sabotier", "tisserand", "charron", "maréchal", "maréchal-ferrant", "charpentier",
    "fermier", "métayer", "rentier", "instituteur", "vigneron", "berger", "bergère",
    "tailleur d'habits", "meunier", "blanquer", "cordonnier", "cabaretier", "aubergiste",
    "maçon", "menuisier", "tonnelier", "boulanger", "tuilier", "scieur de long",
    "domestique", "servante", "propriétaire", "notaire royal", "praticien",
    "marchand", "colporteur", "chaudronnier", "cardeur", "peigneur de chanvre",
]


def known_surnames_hint() -> List[str]:
    """Patronymes attendus dans le fonds, pour lever les ambiguïtés de graphie.

    Importés de src/genealogy/variants.py : ne jamais recopier une liste de patronymes ici.
    Attention, c'est une AIDE, pas une contrainte — le modèle ne doit pas forcer un
    patronyme du fonds sur une graphie qui n'y correspond pas.
    """
    return list(BRANCH_SURNAMES)


def expand_abbreviations(text: str) -> str:
    """Développe les abréviations connues, en préservant le texte d'origine ailleurs."""
    result = text
    for short, full in ABBREVIATIONS.items():
        result = result.replace(f" {short} ", f" {full} ")
    return result


def fold(text: str) -> str:
    """Minuscule sans accents.

    La comparaison doit être insensible aux accents : l'ancien français les omet
    fréquemment, et les moteurs de transcription les restituent de façon irrégulière.
    « constate le deces » doit être reconnu comme « constaté le décès ».
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def detect_act_type(text: str) -> str:
    """Devine le type d'acte d'après les formules présentes. Retourne 'inconnu' si indécis.

    Le comptage d'indices évite le biais de l'ancienne heuristique, qui classait en
    « naissance » tout texte contenant la sous-chaîne « né » — donc aussi « née », mais
    surtout « donné », « ordonné » ou « nébuleux ».
    """
    lowered = fold(text)
    scores = {
        act_type: sum(1 for cue in cues if fold(cue) in lowered)
        for act_type, cues in ACT_TYPE_CUES.items()
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "inconnu"


def canonical_role(raw_role: str) -> str:
    """Ramène un rôle lu dans l'acte à sa forme canonique attendue par le constructeur."""
    if not raw_role:
        return "mentionné"
    return ROLE_SYNONYMS.get(raw_role.strip().lower(), raw_role.strip().lower())


def creates_filiation(role: str) -> bool:
    """Indique si ce rôle doit produire un lien de filiation.

    Un parrain ou un témoin ne crée JAMAIS de filiation, même s'il porte le même patronyme
    que l'enfant : c'est fréquemment un oncle ou un grand-parent.
    """
    return canonical_role(role) not in NON_FILIATION_ROLES


def build_transcription_prompt() -> str:
    """Consigne de transcription paléographique, sans extraction ni interprétation.

    Le modèle doit rendre ce qu'il LIT, y compris les graphies fautives : la normalisation
    intervient plus tard. Toute incertitude doit rester visible plutôt que d'être comblée.
    """
    return f"""Tu es paléographe, spécialiste des registres paroissiaux français (BMS) du 16e au 19e siècle.

Transcris FIDÈLEMENT le texte manuscrit de cette image de registre.

Règles impératives :
1. Respecte l'orthographe d'origine, y compris fautive ou archaïque. Ne modernise rien.
2. Note [illisible] pour tout passage que tu ne peux pas lire. N'INVENTE JAMAIS un mot,
   un nom ni une date pour combler un trou : une lacune signalée vaut mieux qu'une
   plausibilité fausse.
3. Pour une lecture incertaine, écris ta lecture suivie de (?) — exemple : Vergne(?).
4. Conserve la mise en page : un acte par paragraphe, dans l'ordre du registre.
5. Les actes antérieurs à 1737 sont souvent en latin : transcris en latin, ne traduis pas.
6. Développe les abréviations entre crochets : led[it], D[emoi]selle.

Contexte utile :
- Abréviations fréquentes : {", ".join(sorted(ABBREVIATIONS)[:14])}
- Mois anciens : {", ".join(sorted(set(OLD_MONTH_SPELLINGS)))}
- Calendrier républicain (1793-1805) : {", ".join(REPUBLICAN_MONTHS)}
- Métiers de la région et de l'époque : {", ".join(ANCIENT_OCCUPATIONS[:22])}
- Patronymes attendus dans ce fonds (AIDE À LA LECTURE, ne les force pas) :
  {", ".join(known_surnames_hint())}

Réponds uniquement par la transcription, sans commentaire ni préambule."""


def build_extraction_prompt(text: str) -> str:
    """Consigne d'extraction structurée à partir d'une transcription."""
    roles = sorted({canonical_role(r) for r in ROLE_SYNONYMS})
    return f"""Tu es généalogiste, spécialiste de l'état civil et des registres paroissiaux français.

À partir de la transcription ci-dessous, produis un JSON strictement conforme :

{{
  "act_type": un de {sorted(ACT_TYPE_CUES)} ou "inconnu",
  "date": la date en clair telle qu'elle figure dans l'acte (n'invente pas de format ISO
          si l'acte ne le permet pas ; conserve « an IV » pour le calendrier républicain),
  "location": la paroisse ou la commune si elle est mentionnée, sinon null,
  "persons": [ {{"first_name": ..., "last_name": ..., "role": ..., "occupation": ...}} ],
  "confidence_score": ta confiance réelle entre 0.0 et 1.0,
  "uncertain_fields": [liste des champs dont tu n'es pas sûr]
}}

Règles impératives :
1. Rôles autorisés : {", ".join(roles)}.
2. Un PARRAIN, une MARRAINE ou un TÉMOIN ne sont JAMAIS le père ou la mère, même s'ils
   portent le même patronyme : c'est très souvent un oncle ou un grand-parent.
3. Si une information est absente de la transcription, mets null. N'INVENTE RIEN — ni date,
   ni lieu, ni prénom. Une extraction incomplète est exploitable, une extraction inventée
   corrompt la généalogie.
4. confidence_score doit refléter ton incertitude réelle. N'annonce pas 0.95 par défaut.
5. Signale dans uncertain_fields tout champ issu d'une lecture douteuse (marquée (?) ou
   [illisible] dans la transcription).

Transcription :
{text}"""
