import pytest
from src.parser.llm import LLMActParser

def test_parser_build_prompt():
    parser = LLMActParser()
    prompt = parser.build_prompt("Texte de test")
    assert "laboureur" in prompt
    assert "Texte : Texte de test" in prompt

def test_parser_parse_act():
    parser = LLMActParser()
    raw = "L'an 1845 est né Jean VERGNE fils de Pierre VERGNE à Aurillac."
    act = parser.parse(raw)
    assert act.act_type == "naissance"
    assert act.confidence_score > 0.0
    assert any(p.last_name == "VERGNE" for p in act.persons)
