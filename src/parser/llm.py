"""Extraction structurée d'un acte à partir de sa transcription.

Deux chemins, dans cet ordre :
  1. un modèle de langage, guidé par le contexte BMS de src/ocr/bms.py (Anthropic si
     ANTHROPIC_API_KEY est défini, sinon toute API compatible OpenAI, Ollama compris) ;
  2. à défaut, un repli heuristique par règles, dont la confiance annoncée est basse.

Le vocabulaire métier (types d'actes, rôles, abréviations, patronymes attendus) n'est PAS
défini ici : il vient de src/ocr/bms.py, lui-même adossé à src/genealogy/variants.py.
Ne recopiez jamais de liste de patronymes dans ce fichier.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional

from src.core.models import Act, Person
from src.ocr.bms import (
    ANCIENT_OCCUPATIONS,
    build_extraction_prompt,
    canonical_role,
    detect_act_type,
    expand_abbreviations,
    known_surnames_hint,
)

logger = logging.getLogger("certus.parser.llm")

# Confiance du repli heuristique : volontairement basse, il ne comprend pas l'acte.
HEURISTIC_CONFIDENCE_WITH_NAMES = 0.45
HEURISTIC_CONFIDENCE_WITHOUT_NAMES = 0.15

# Mots en capitales qui ne sont pas des patronymes.
_STOPWORDS = {
    "L'AN", "LE", "LA", "LES", "DU", "DE", "DES", "ET", "EN", "PAR", "AN", "NOUS",
    "MOI", "DIT", "DITE", "SON", "SA", "AU", "AUX", "SUR", "POUR", "AVEC", "ONT",
}
_SURNAME_RE = re.compile(r"\b[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]{3,}(?:[ -][A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]{2,})?\b")


class LLMActParser:
    """Parser sémantique d'actes, guidé par le lexique paléographique du fonds."""

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        api_base: Optional[str] = None,
        temperature: float = 0.0,
    ):
        self.model_name = os.getenv("LLM_MODEL", model_name)
        self.api_base = os.getenv("LLM_API_BASE", api_base)
        self.temperature = temperature
        self.lexicon = ANCIENT_OCCUPATIONS

    def build_prompt(self, text: str) -> str:
        """Consigne d'extraction, incluant lexique des métiers et patronymes attendus."""
        return (
            build_extraction_prompt(text)
            + "\n\nMétiers anciens fréquents dans ce fonds : "
            + ", ".join(self.lexicon)
            + "\nPatronymes attendus (aide à la lecture, ne les forcez pas) : "
            + ", ".join(known_surnames_hint())
        )

    # ------------------------------------------------------------------ modèles de langage
    def _parse_json_payload(self, raw_json: str, text: str) -> Act:
        data = json.loads(raw_json)
        persons = [
            Person(
                first_name=p.get("first_name"),
                last_name=p.get("last_name"),
                role=canonical_role(p.get("role", "mentionné")),
                occupation=p.get("occupation"),
            )
            for p in data.get("persons", [])
        ]
        confidence = float(data.get("confidence_score", 0.0))
        uncertain = data.get("uncertain_fields") or []
        if uncertain:
            # Le modèle a signalé des champs douteux : la confiance doit en tenir compte.
            confidence = min(confidence, 0.75)
            logger.info("Champs signalés incertains par le modèle : %s", ", ".join(uncertain))
        return Act(
            act_type=data.get("act_type", "inconnu"),
            date=data.get("date"),
            location=data.get("location"),
            confidence_score=confidence,
            persons=persons,
            source_text=text,
        )

    def _parse_with_anthropic(self, text: str) -> Optional[Act]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic

            client = anthropic.Anthropic()
            response = client.messages.create(
                model=os.getenv("CERTUS_EXTRACTION_MODEL", "claude-opus-5"),
                max_tokens=2048,
                temperature=self.temperature,
                messages=[{"role": "user", "content": self.build_prompt(text)}],
            )
            payload = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            )
            match = re.search(r"\{.*\}", payload, re.S)
            if not match:
                logger.warning("Réponse du modèle sans JSON exploitable.")
                return None
            return self._parse_json_payload(match.group(0), text)
        except Exception as exc:
            # Journalisé, jamais avalé : le silence masquait toute panne du modèle.
            logger.warning("Extraction Anthropic en échec : %s", exc)
            return None

    def _parse_with_openai(self, text: str) -> Optional[Act]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key and not self.api_base:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key or "ollama", base_url=self.api_base)
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": self.build_prompt(text)}],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            return self._parse_json_payload(response.choices[0].message.content, text)
        except Exception as exc:
            logger.warning("Extraction compatible OpenAI en échec : %s", exc)
            return None

    def parse_with_llm(self, text: str) -> Optional[Act]:
        """Tente une extraction par modèle de langage. Retourne None si aucun n'aboutit."""
        return self._parse_with_anthropic(text) or self._parse_with_openai(text)

    # ------------------------------------------------------------------ repli heuristique
    def _heuristic_parse(self, text: str) -> Act:
        """Extraction par règles : détecte le type d'acte et les patronymes en capitales.

        Ce repli ne comprend ni les filiations ni les dates : il attribue le rôle neutre
        « mentionné » et annonce une confiance basse. L'ancienne version classait en
        « naissance » tout texte contenant la sous-chaîne « né », donc aussi « donné » ou
        « ordonné », et annonçait pourtant 0,90.
        """
        expanded = expand_abbreviations(text)
        act_type = detect_act_type(expanded)

        persons: List[Person] = []
        for candidate in sorted(set(_SURNAME_RE.findall(text))):
            if candidate in _STOPWORDS:
                continue
            persons.append(Person(first_name=None, last_name=candidate, role="mentionné"))

        confidence = (
            HEURISTIC_CONFIDENCE_WITH_NAMES if persons else HEURISTIC_CONFIDENCE_WITHOUT_NAMES
        )
        logger.info(
            "Extraction heuristique (aucun modèle disponible) : type « %s », %d patronyme(s), "
            "confiance %.2f.",
            act_type,
            len(persons),
            confidence,
        )
        return Act(
            act_type=act_type,
            confidence_score=confidence,
            persons=persons,
            source_text=text,
        )

    def parse(self, text: str) -> Act:
        """Extrait un Act de la transcription fournie."""
        if not text or not text.strip():
            return Act(act_type="inconnu", confidence_score=0.0, source_text=text)

        llm_act = self.parse_with_llm(text)
        if llm_act is not None:
            return llm_act
        return self._heuristic_parse(text)
