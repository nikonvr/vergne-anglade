"""Adaptateurs de sources en ligne (constats C1 et M3).

GeneanetAdapter portait un couple identifiant/mot de passe en clair comme valeur par défaut,
et fabriquait un acte à partir de la requête avec un score de confiance de 0,98.
"""

import pytest

from src.core.models import SearchQuery
from src.core.simulation import SIMULATED_PREFIX
from src.crawler.adapters import GeneanetAdapter, MemoireDesHommesAdapter


def test_aucun_identifiant_en_dur(monkeypatch):
    """C1 : sans variables d'environnement, l'adaptateur n'est pas authentifié."""
    monkeypatch.delenv("GENEANET_USERNAME", raising=False)
    monkeypatch.delenv("GENEANET_PASSWORD", raising=False)

    adapter = GeneanetAdapter()

    assert adapter.username is None
    assert adapter.password is None
    assert adapter.is_authenticated is False


@pytest.mark.anyio
@pytest.mark.parametrize("adapter_class", [GeneanetAdapter, MemoireDesHommesAdapter])
async def test_aucune_fabrication_sans_autorisation(adapter_class, monkeypatch):
    """M3 : sans autorisation explicite, la source ne renvoie aucun acte inventé."""
    monkeypatch.delenv("GENEANET_USERNAME", raising=False)
    monkeypatch.delenv("GENEANET_PASSWORD", raising=False)

    acts = await adapter_class().search(SearchQuery(last_name="ANGLADE"))

    assert acts == []


@pytest.mark.anyio
@pytest.mark.parametrize("adapter_class", [GeneanetAdapter, MemoireDesHommesAdapter])
async def test_acte_simule_entierement_marque(adapter_class, allow_simulation):
    """M3 : un acte simulé porte le drapeau, le préfixe de provenance et des scores nuls."""
    acts = await adapter_class().search(SearchQuery(last_name="VERGNE", first_name="Pierre"))

    assert len(acts) == 1
    act = acts[0]
    assert act.is_simulated is True
    assert act.source_type.startswith(SIMULATED_PREFIX)
    assert act.confidence_score == 0.0
    assert act.reliability_score == 0.0


@pytest.mark.anyio
async def test_requete_sans_patronyme_ne_renvoie_rien(allow_simulation):
    assert await GeneanetAdapter().search(SearchQuery(last_name="")) == []
