"""Full Reader node in isolation, with synthetic papers/PDFs/model responses."""
import copy
import json
from unittest.mock import Mock

import pytest

from research_assistant.reader_node import create_fulltext_reader_node
from research_assistant.schemas import PaperAnalysis
from test_reader_pipeline import SyntheticAbstract, SyntheticFulltext


def paper(title="Synthetic"):
    return {"title": title, "authors": [], "source": "synthetic", "abstract": "Synthetic evidence"}


def test_fulltext_node_contract_replacement_and_configuration_copy(tmp_path):
    from test_reader_pdf import make_pdf
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A",))
    paths = {"Synthetic": path}
    options = {"max_calls": 10}
    node = create_fulltext_reader_node(paths, budget_options=options,
        abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=SyntheticFulltext)
    paths.clear()
    options["max_calls"] = 0
    state = {"papers": [paper(), paper(), paper("Missing")],
             "paper_analysis": [{"paper_title": "Stale"}], "method_summary": {"synthetic": True}}
    before = copy.deepcopy(state)
    result = node(state)
    assert set(result) == {"paper_analysis"}
    assert [a["paper_title"] for a in result["paper_analysis"]] == ["Synthetic", "Missing"]
    assert result["paper_analysis"][0]["method"] == "Synthetic method A"
    assert result["paper_analysis"][1]["method"] == "Synthetic abstract method"
    assert state == before
    for analysis in result["paper_analysis"]:
        PaperAnalysis.model_validate(analysis)
    assert json.loads(json.dumps(result)) == result
    assert node({"papers": [paper("New")]})["paper_analysis"][0]["paper_title"] == "New"
    assert node({}) == {"paper_analysis": []}


def test_node_does_not_download_by_default(monkeypatch):
    remote = Mock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr("research_assistant.reader_node.run_reader_with_downloads", remote)
    node = create_fulltext_reader_node()
    result = node({"papers": [{**paper(), "url": "https://arxiv.org/abs/2401.12345"}]})
    assert result["paper_analysis"][0]["method"] == ""
    remote.assert_not_called()


@pytest.mark.parametrize("options", [
    {"download_arxiv": 1}, {"download_options": {}},
    {"download_arxiv": True, "download_options": []},
    {"download_arxiv": True, "download_options": {"max_requests": 0}},
    {"pdf_paths": {"": "bad.pdf"}}, {"budget_options": {"max_calls": 0}},
    {"fulltext_options": {"reconcile": 1}}, {"pdf_options": {"max_workers": 9}},
])
def test_invalid_factory_configuration_fails_before_work(options):
    with pytest.raises(ValueError):
        create_fulltext_reader_node(**options)


def test_node_conflict_rejected_before_analyzer_construction():
    factory = Mock()
    node = create_fulltext_reader_node(abstract_analyzer_factory=factory)
    with pytest.raises(ValueError):
        node({"papers": [paper(), {**paper(), "abstract": "Synthetic conflict"}]})
    factory.assert_not_called()


def test_download_node_with_synthetic_http_and_cleanup(tmp_path, monkeypatch):
    from test_reader_pdf import make_pdf
    from test_reader_download import Response
    from research_assistant import reader_download
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A",))
    monkeypatch.setattr(reader_download, "_NEXT_REQUEST", 0)
    monkeypatch.setattr(reader_download, "_BLOCKED_UNTIL", 0)
    monkeypatch.setattr(reader_download, "_open", lambda *a: Response(path.read_bytes()))
    seen = []
    original = reader_download.download_pdf
    def fetch(url, destination, **options):
        seen.append(destination)
        return original(url, destination, **options)
    monkeypatch.setattr(reader_download, "download_pdf", fetch)
    node = create_fulltext_reader_node(download_arxiv=True,
        abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=SyntheticFulltext)
    result = node({"papers": [{**paper(), "url": "https://arxiv.org/abs/2401.12345"}]})
    assert result["paper_analysis"][0]["method"] == "Synthetic method A"
    assert seen and all(not p.exists() and not p.parent.exists() for p in seen)
