from __future__ import annotations

import json
import sys

from research_assistant.demo_stubs import (
    demo_analyst_node,
    demo_critic_node,
    demo_reader_node,
    demo_search_node,
    demo_writer_node,
)
from research_assistant.graph import build_research_graph


def main() -> None:
    topic = " ".join(sys.argv[1:]).strip() or "Multimodal Time Series Forecasting"

    app = build_research_graph(
        search_node=demo_search_node,
        reader_node=demo_reader_node,
        analyst_node=demo_analyst_node,
        critic_node=demo_critic_node,
        writer_node=demo_writer_node,
    )

    result = app.invoke(
        {
            "topic": topic,
            "critic_round": 0,
            "max_critic_rounds": 2,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
