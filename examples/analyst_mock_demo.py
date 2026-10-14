"""运行：python -m examples.analyst_mock_demo；不读取密钥，不发起模型请求。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from research_assistant.agents.analyst import create_analyst_node


def main() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "analyst_mock.json").read_text(encoding="utf-8")
    )
    model = Mock()
    model.invoke.return_value = fixture["model_response"]
    result = create_analyst_node(model)(fixture["state"])
    print(json.dumps({"notice": fixture["notice"], **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
