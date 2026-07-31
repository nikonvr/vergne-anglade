import json
import os
import re
from typing import List, Optional
from src.core.models import Act, Person

ANCIENT_OCCUPATIONS = [
    "laboureur", "brassier", "manouvrier", "cultivateur",
    "ménager", "journalier", "sabotier", "tisserand", "charron",
    "maréchal", "charpentier", "fermier", "rentier", "instituteur",
    "vigneron", "berger", "tailleur d'habits", "meunier", "blanquer"
]

FEW_SHOT_PROMPT_TEMPLATE = """
Tu es un expert généalogiste et paléographe spécialisé dans l'état civil français (18e et 19e siècle).
Utilise ce lexique des métiers anciens pour corriger les incertitudes d'OCR : {lexicon}

Exemple 1 (Naissance) :
Texte : "L'an 1840, le 5 mai est né Jean VERGNE fils de Pierre VERGNE laboureur et de Marie ANGLADE."
JSON : {{"act_type": "naissance", "date": "1840-05-05", "persons": [{{"first_name": "Jean", "last_name": "VERGNE", "role": "enfant"}}, {{"first_name": "Pierre", "last_name": "VERGNE", "role": "père", "occupation": "laboureur"}}, {{"first_name": "Marie", "last_name": "ANGLADE", "role": "mère"}}], "confidence_score": 0.98}}

Exemple 2 (Mariage) :
Texte : "L'an 1835 le 25 février mariage entre Philippe VERGNE cultivateur et Rose Virginie ANGLADE."
JSON : {{"act_type": "mariage", "date": "1835-02-25", "persons": [{{"first_name": "Philippe", "last_name": "VERGNE", "role": "époux", "occupation": "cultivateur"}}, {{"first_name": "Rose Virginie", "last_name": "ANGLADE", "role": "épouse"}}], "confidence_score": 0.96}}

Exemple 3 (Décès) :
Texte : "L'an 1825 le 10 août est décédée Antoinette LAPEYRE veuve de Jean VERGNE journalier."
JSON : {{"act_type": "décès", "date": "1825-08-10", "persons": [{{"first_name": "Antoinette", "last_name": "LAPEYRE", "role": "défunte"}}, {{"first_name": "Jean", "last_name": "VERGNE", "role": "conjoint", "occupation": "journalier"}}], "confidence_score": 0.95}}

Analyse le texte suivant et retourne uniquement le JSON d'extraction structuré.
"""

class LLMActParser:
    """Parser sémantique d'actes d'archives avec Few-Shot Prompting et Lexique régional."""
    
    def __init__(self, model_name: str = "gpt-4o-mini", api_base: Optional[str] = None, temperature: float = 0.0):
        self.model_name = os.getenv("LLM_MODEL", model_name)
        self.api_base = os.getenv("LLM_API_BASE", api_base)
        self.temperature = temperature
        self.lexicon = ANCIENT_OCCUPATIONS

    def build_prompt(self, text: str) -> str:
        return FEW_SHOT_PROMPT_TEMPLATE.format(lexicon=", ".join(self.lexicon)) + f"\nTexte : {text}"

    def parse_with_llm(self, text: str) -> Optional[Act]:
        """Tente un appel réel au modèle LLM (OpenAI / Ollama) s'il est configuré."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key and not self.api_base:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key or "ollama", base_url=self.api_base)
            prompt = self.build_prompt(text)
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )
            raw_json = response.choices[0].message.content
            data = json.loads(raw_json)
            persons = [
                Person(
                    first_name=p.get("first_name"),
                    last_name=p.get("last_name"),
                    role=p.get("role", "mentionné"),
                    occupation=p.get("occupation")
                )
                for p in data.get("persons", [])
            ]
            return Act(
                act_type=data.get("act_type", "inconnu"),
                date=data.get("date"),
                location=data.get("location"),
                confidence_score=float(data.get("confidence_score", 0.95)),
                persons=persons,
                source_text=text
            )
        except Exception:
            return None

    def parse(self, text: str) -> Act:
        """Parse le texte brut d'un acte et retourne le modèle Pydantic Act."""
        if not text or not text.strip():
            return Act(act_type="inconnu", confidence_score=0.0, source_text=text)

        # 1. Tentative d'appel au serveur LLM (OpenAI / Ollama)
        llm_act = self.parse_with_llm(text)
        if llm_act is not None:
            return llm_act

        # 2. Secours par règles heuristiques & extraction
        act_type = "inconnu"
        lower_text = text.lower()
        if "né" in lower_text or "naissance" in lower_text:
            act_type = "naissance"
        elif "mariage" in lower_text or "époux" in lower_text:
            act_type = "mariage"
        elif "décès" in lower_text or "décédé" in lower_text or "décedé" in lower_text:
            act_type = "décès"

        persons: List[Person] = []
        last_names = set(re.findall(r'\b[A-Z]{3,}\b', text))
        for ln in sorted(last_names):
            if ln not in ("L'AN", "LE", "DU", "ET", "EN", "PAR"):
                persons.append(Person(first_name=None, last_name=ln, role="mentionné"))

        return Act(
            act_type=act_type,
            confidence_score=0.90 if persons else 0.50,
            persons=persons,
            source_text=text
        )

