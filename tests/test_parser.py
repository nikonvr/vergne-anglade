"""Extraction d'un acte depuis sa transcription (constats M3 et Mod3)."""

import pytest

from src.ocr.bms import canonical_role, creates_filiation, detect_act_type
from src.parser.llm import HEURISTIC_CONFIDENCE_WITH_NAMES, LLMActParser


def test_prompt_contient_le_contexte_metier():
    prompt = LLMActParser().build_prompt("Texte de test")

    assert "Texte de test" in prompt
    assert "laboureur" in prompt  # lexique des métiers anciens
    assert "parrain" in prompt.lower()  # rôles des registres paroissiaux
    assert "VERGNE" in prompt  # patronymes attendus, importés de variants.py


def test_repli_heuristique_annonce_une_confiance_basse(monkeypatch):
    """M3 : l'ancien repli par règles annonçait 0,90 sans rien comprendre de l'acte."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_BASE", raising=False)

    act = LLMActParser().parse("L'an 1845 est né Jean VERGNE fils de Pierre VERGNE à Aurillac.")

    assert act.act_type == "naissance"
    assert act.confidence_score == HEURISTIC_CONFIDENCE_WITH_NAMES
    assert any(p.last_name == "VERGNE" for p in act.persons)
    # Le repli ne prétend pas connaître les filiations.
    assert {p.role for p in act.persons} == {"mentionné"}


def test_texte_vide_donne_une_confiance_nulle():
    act = LLMActParser().parse("   ")
    assert act.act_type == "inconnu"
    assert act.confidence_score == 0.0


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("L'an 1845 est né Jean, fils de Pierre", "naissance"),
        ("a été baptisé ce jour, parrain Jean", "baptême"),
        ("ont contracté mariage en présence de", "mariage"),
        ("a été inhumé au cimetière", "sépulture"),
        ("constaté le décès en son domicile", "décès"),
        # Le piège historique : « ordonné » contient « né ».
        ("il a donné son consentement et ordonné", "inconnu"),
        # Registres antérieurs à 1737, rédigés en latin.
        ("baptizatus est filius Petri", "baptême"),
    ],
)
def test_detection_du_type_d_acte(texte, attendu):
    assert detect_act_type(texte) == attendu


def test_detection_insensible_aux_accents():
    """Les registres anciens omettent souvent les accents, et le HTR les restitue mal."""
    assert detect_act_type("constate le deces") == "décès"
    assert detect_act_type("a ete inhume") == "sépulture"


@pytest.mark.parametrize(
    "brut, canonique",
    [
        ("fils", "enfant"),
        ("filius", "enfant"),
        ("Père", "père"),
        ("mater", "mère"),
        ("matris", "mère"),  # génitif latin de mater : la mère, jamais le père
        ("patrinus", "parrain"),
        ("testis", "témoin"),
    ],
)
def test_roles_canoniques(brut, canonique):
    assert canonical_role(brut) == canonique


@pytest.mark.parametrize("role", ["parrain", "marraine", "témoin", "officiant", "patrinus"])
def test_parrains_et_temoins_ne_creent_pas_de_filiation(role):
    """Un parrain est fréquemment un oncle : le prendre pour le père fabrique une filiation."""
    assert creates_filiation(role) is False


@pytest.mark.parametrize("role", ["père", "mère", "enfant", "fils", "mater"])
def test_roles_de_filiation(role):
    assert creates_filiation(role) is True
