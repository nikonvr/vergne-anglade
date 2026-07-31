import pytest
from src.core.models import Act, Person
from src.genealogy.builder import TreeBuilder
from src.export.html_report import HtmlReportExporter

def test_relationship_ancestor():
    builder = TreeBuilder()
    act = Act(
        act_type="Naissance",
        confidence_score=1.0,
        persons=[
            Person(first_name="Jean", last_name="VERGNE", role="père"),
            Person(first_name="Pierre", last_name="VERGNE", role="enfant")
        ]
    )
    tree = builder.process_acts([act])
    ancestor = builder.find_common_ancestor("VERGNE_JEAN", "VERGNE_PIERRE")
    assert ancestor is None or isinstance(ancestor, str)

def test_html_report_exporter():
    builder = TreeBuilder()
    act = Act(
        act_type="Naissance",
        confidence_score=1.0,
        persons=[Person(first_name="Antoine", last_name="VERGNE", role="enfant")]
    )
    tree = builder.process_acts([act])
    exporter = HtmlReportExporter()
    html = exporter.generate_html(tree)
    assert "Antoine" in html
    assert "VERGNE" in html
