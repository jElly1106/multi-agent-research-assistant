"""Offline unified Reader demo: synthetic abstracts with absent local PDFs."""
import json

from .agents.reader import empty_analysis
from .reader_pipeline import run_reader


class SyntheticAbstract:
    def analyze(self, paper):
        return empty_analysis(paper).model_copy(update={"problem": "Synthetic demonstration only"})


if __name__ == "__main__":
    result = run_reader([
        {"title": "SYNTHETIC Paper", "authors": [], "source": "synthetic", "abstract": "Synthetic evidence"}
    ], abstract_analyzer_factory=SyntheticAbstract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["paper_analysis"][0]["problem"] != "Synthetic demonstration only":
        raise SystemExit(1)
