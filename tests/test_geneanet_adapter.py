import pytest
from src.core.models import SearchQuery
from src.crawler.adapters import GeneanetAdapter

@pytest.mark.anyio
async def test_geneanet_adapter_unauthenticated():
    adapter = GeneanetAdapter(username="", password="")
    assert not adapter.is_authenticated
    
    query = SearchQuery(last_name="ANGLADE", first_name="Jean")
    acts = await adapter.search(query)
    
    assert len(acts) == 1
    assert acts[0].source_type == "GENEANET_PUBLIC"
    assert acts[0].persons[0].last_name == "ANGLADE"

@pytest.mark.anyio
async def test_geneanet_adapter_authenticated():
    adapter = GeneanetAdapter(username="test_user", password="secret_password")
    assert adapter.is_authenticated
    
    query = SearchQuery(last_name="VERGNE", first_name="Pierre")
    acts = await adapter.search(query)
    
    assert len(acts) == 1
    assert acts[0].source_type == "GENEANET_PREMIUM"
    assert acts[0].confidence_score == 0.98
    assert acts[0].persons[0].last_name == "VERGNE"

@pytest.mark.anyio
async def test_geneanet_adapter_empty_query():
    adapter = GeneanetAdapter()
    query = SearchQuery(last_name="")
    acts = await adapter.search(query)
    assert len(acts) == 0
