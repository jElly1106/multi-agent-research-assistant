"""Synthetic standalone CLI acceptance; no network/model calls."""
import json
import io
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from research_assistant import reader_cli


def test_offline_cli_subprocess_with_real_pdf(tmp_path):
    from test_reader_pdf import make_pdf
    pdf = tmp_path / "synthetic.pdf"
    make_pdf(pdf)
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"papers": [
        {"title": "Synthetic", "authors": [], "source": "synthetic", "abstract": "Synthetic"}],
        "pdf_paths": {"Synthetic": str(pdf)}, "pdf_options": {"max_workers": 2}}), encoding="utf-8")
    output = tmp_path / "result.json"
    run = subprocess.run([sys.executable, "-B", "-m", "research_assistant.reader_cli",
        "--input", str(source), "--output", str(output), "--offline"],
        capture_output=True, text=True, timeout=40)
    assert run.returncode == 0, run.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["preparation"]["materials"][0]["status"] == "ok"
    assert result["paper_analysis"][0]["method"] == ""
    assert result["budget"]["admitted_calls"] == 0


def test_cli_refuses_overwrite_before_calls(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    output = tmp_path / "existing.json"
    output.write_text("preserve", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(reader_cli, "run_reader", run)
    with pytest.raises(FileExistsError):
        reader_cli.main(["--input", str(source), "--output", str(output)])
    run.assert_not_called()
    assert output.read_text() == "preserve"


def test_cli_failure_removes_incomplete_file_and_restores_environment(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    output = tmp_path / "failed.json"
    monkeypatch.setenv("READER_USE_LLM", "1")
    def fail(**kwargs):
        assert os.environ["READER_USE_LLM"] == "0"
        raise ValueError("synthetic failure")
    monkeypatch.setattr(reader_cli, "run_reader", fail)
    with pytest.raises(ValueError, match="synthetic failure"):
        reader_cli.main(["--input", str(source), "--output", str(output), "--offline"])
    assert not output.exists()
    assert os.environ["READER_USE_LLM"] == "1"


def test_cli_download_mode_is_explicit_and_offline_exclusive(tmp_path, monkeypatch, capsys):
    source = tmp_path / "input.json"
    source.write_text('{"papers": [], "download_options": {"max_requests": 1}}', encoding="utf-8")
    remote = Mock(return_value={"paper_analysis": [], "acquisition": []})
    monkeypatch.setattr(reader_cli, "run_reader_with_downloads", remote)
    with pytest.raises(SystemExit):
        reader_cli.main(["--input", str(source)])
    with pytest.raises(SystemExit):
        reader_cli.main(["--input", str(source), "--offline", "--download-arxiv"])
    remote.assert_not_called()
    reader_cli.main(["--input", str(source), "--download-arxiv"])
    assert remote.call_args.kwargs["download_options"] == {"max_requests": 1}


def test_cli_default_never_enables_downloads(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    remote = Mock(side_effect=AssertionError("unexpected download"))
    monkeypatch.setattr(reader_cli, "run_reader_with_downloads", remote)
    reader_cli.main(["--input", str(source), "--offline"])
    remote.assert_not_called()


@pytest.mark.parametrize("old", [None, "1"])
def test_no_llm_allows_download_mode_and_restores_environment(tmp_path, monkeypatch, old):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    if old is None:
        monkeypatch.delenv("READER_USE_LLM", raising=False)
    else:
        monkeypatch.setenv("READER_USE_LLM", old)
    def run(**kwargs):
        assert os.environ["READER_USE_LLM"] == "0"
        return {"paper_analysis": [], "acquisition": []}
    remote = Mock(side_effect=run)
    monkeypatch.setattr(reader_cli, "run_reader_with_downloads", remote)
    reader_cli.main(["--input", str(source), "--download-arxiv", "--no-llm"])
    remote.assert_called_once()
    assert os.environ.get("READER_USE_LLM") == old


def test_cli_legacy_console_preserves_unicode_json(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    synthetic = {"synthetic": "PDF symbols: ∗ ﬁ 😀"}
    monkeypatch.setattr(reader_cli, "run_reader", lambda **kw: synthetic)
    buffer = io.BytesIO()
    console = io.TextIOWrapper(buffer, encoding="gbk")
    monkeypatch.setattr(reader_cli.sys, "stdout", console)
    reader_cli.main(["--input", str(source), "--offline"])
    console.flush()
    encoded = buffer.getvalue().decode("gbk")
    assert json.loads(encoded) == synthetic
    assert "\\u2217" in encoded


def test_cli_file_output_remains_utf8(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text('{"papers": []}', encoding="utf-8")
    output = tmp_path / "result.json"
    synthetic = {"synthetic": "PDF symbols: ∗ ﬁ 😀"}
    monkeypatch.setattr(reader_cli, "run_reader", lambda **kw: synthetic)
    reader_cli.main(["--input", str(source), "--output", str(output), "--offline"])
    assert json.loads(output.read_text(encoding="utf-8")) == synthetic
    assert "∗" in output.read_text(encoding="utf-8")
