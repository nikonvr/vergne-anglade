import pytest
from src.core.models import SearchQuery, Act, Person
from src.core.meta_orchestrator import MetaOrchestrator
from src.crawler.adapters import BaseSourceAdapter, GallicaAdapter, CsvAdapter

class MockSourceAdapter(BaseSourceAdapter):
    async def search(self, query: SearchQuery):
        return [
            Act(
                act_type="Mariage",
                date="1835-02-25",
                location=query.location,
                confidence_score=0.95,
                source_type="MOCK_SOURCE",
                persons=[Person(first_name="Jean", last_name=query.last_name, role="époux")]
            )
        ]

@pytest.mark.anyio
async def test_meta_orchestrator_parallel_search():
    mock_adapter_1 = MockSourceAdapter()
    mock_adapter_2 = MockSourceAdapter()
    
    meta = MetaOrchestrator(sources=[mock_adapter_1, mock_adapter_2])
    query = SearchQuery(last_name="VERGNE", location="Anglards-de-Salers")
    
    acts = await meta.search_everywhere(query)
    assert len(acts) == 2
    assert acts[0].persons[0].last_name == "VERGNE"

@pytest.mark.anyio
async def test_meta_orchestrator_tree_consolidation():
    mock_adapter = MockSourceAdapter()
    meta = MetaOrchestrator(sources=[mock_adapter])
    query = SearchQuery(last_name="VERGNE", location="Anglards-de-Salers")
    
    tree = await meta.build_consolidated_tree(query)
    assert "VERGNE_JEAN" in tree.nodes
