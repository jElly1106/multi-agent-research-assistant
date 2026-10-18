"""Offline synthetic P2 demo; no credentials, PDF dependency or model calls."""
import json

from .reader_fulltext import analyze_fulltext_materials


class SyntheticAnalyzer:
    def analyze(self, chunk):
        return {"claims": [{"field": "method", "value": "Synthetic method A",
                            "quote": "Synthetic method A"}]}


def main():
    text = "Synthetic method A uses synthetic inputs."
    result = analyze_fulltext_materials(
        [{"title": "SYNTHETIC Paper", "authors": [], "source": "synthetic"}],
        [{"paper_title": "SYNTHETIC Paper", "status": "ok", "issues": [],
          "pages": [{"page": 1, "text": text}],
          "chunks": [{"index": 1, "page": 1, "start": 0, "end": len(text), "text": text}]}],
        analyzer_factory=SyntheticAnalyzer,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["paper_analysis"][0]["method"] != "Synthetic method A":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
