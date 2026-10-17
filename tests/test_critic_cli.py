from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_evaluation_cli_accepts_powershell_utf8_bom_files(tmp_path):
    state = tmp_path / "state.json"
    labels = tmp_path / "labels.json"
    history = tmp_path / "history.json"
    output = tmp_path / "metrics.json"
    for path, payload in ((state, {}), (labels, {}), (history, [])):
        path.write_text(json.dumps(payload), encoding="utf-8-sig")
    result = subprocess.run([
        sys.executable, "-m", "examples.evaluate_run", "--input", str(state),
        "--annotations", str(labels), "--history", str(history), "--output", str(output),
    ], cwd=Path(__file__).parents[1], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["paper_count"] == 0


def test_live_cli_structural_failure_accepts_bom_without_network(tmp_path):
    state = tmp_path / "state.json"
    output = tmp_path / "critic.json"
    state.write_text("{}", encoding="utf-8-sig")
    result = subprocess.run([
        sys.executable, "-m", "examples.critic_live_demo", "--input", str(state), "--output", str(output),
    ], cwd=Path(__file__).parents[1], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["critic_result"]["decision"] == "FAIL"
