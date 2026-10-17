"""Verify the recorded real-API replay offline, including tamper detection."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from examples.search_replay_demo import RecordedTransport, replay
from examples.search_replay_demo import main as replay_main
from research_assistant.search.models import ProviderError


RECORDING = Path(__file__).parents[1] / "examples" / "fixtures" / "search_recording"
ARXIV_RECORDING = RECORDING.with_name("search_recording_arxiv")


def test_actual_recorded_responses_reproduce_identical_papers_without_network(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "invalid\nplaceholder")
    def reject_network(*args, **kwargs):
        raise AssertionError("Offline replay attempted live HTTP")
    monkeypatch.setattr("research_assistant.search.transport.HttpTransport.get", reject_network)
    result = replay(RECORDING / "search_round1.json", RECORDING / "raw")
    assert result["verified_equal"] is True
    assert len(result["state"]["papers"]) == 5
    assert all(p["source"] == "crossref" for p in result["state"]["papers"])
    assert "离线重放" in result["notice"]


def test_recorded_response_tampering_is_rejected(tmp_path):
    data = json.loads((RECORDING / "search_round1.json").read_text("utf-8"))
    request = next(r for r in data["search_audit"]["requests"] if r["status"] == "success")
    evidence = request["response_evidence"]
    shutil.copy2(RECORDING / "raw" / (evidence["response_sha256"] + ".response"), tmp_path)
    (tmp_path / (evidence["response_sha256"] + ".response")).write_bytes(b"tampered")
    with pytest.raises(ProviderError, match="SHA-256"):
        RecordedTransport(data["search_audit"], tmp_path).get(evidence["request_url"])


def test_real_arxiv_recording_reproduces_official_metadata_without_network(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("arXiv replay attempted live HTTP")
    monkeypatch.setattr("research_assistant.search.transport.HttpTransport.get", reject_network)
    result = replay(ARXIV_RECORDING / "search_round1.json", ARXIV_RECORDING / "raw")
    assert result["verified_equal"]
    assert len(result["state"]["papers"]) == 5
    assert all(p["source"] == "arxiv" and p["abstract"] for p in result["state"]["papers"])


def test_default_replay_entry_uses_openalex_recording(monkeypatch, tmp_path):
    output = tmp_path / "replay.json"
    monkeypatch.setattr("sys.argv", ["search_replay_demo", "--output", str(output)])
    assert replay_main() == 0
    data = json.loads(output.read_text("utf-8"))
    assert data["verified_equal"] and {p["source"] for p in data["state"]["papers"]} == {"openalex"}
