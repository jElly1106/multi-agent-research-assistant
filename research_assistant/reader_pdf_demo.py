"""Offline synthetic PDF acceptance: python -m research_assistant.reader_pdf_demo."""
import json
import tempfile
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .reader_materials import prepare_paper_materials


def main():
    with tempfile.TemporaryDirectory(prefix="reader-synthetic-") as folder:
        path = Path(folder) / "synthetic.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (SYNTHETIC acceptance text only) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(path)
        papers = [{"title": title, "authors": [], "source": "synthetic"}
                  for title in ["SYNTHETIC Available", "SYNTHETIC Missing"]]
        result = prepare_paper_materials(papers, {"SYNTHETIC Available": path})
        print(json.dumps({"synthetic": True, "materials": [
            {"paper_title": m["paper_title"], "status": m["status"],
             "pages": len(m["pages"]), "chunks": len(m["chunks"]), "issues": m["issues"]}
            for m in result["materials"]]}, indent=2))
        if ([m["status"] for m in result["materials"]] != ["ok", "failed"]
                or result["materials"][1]["issues"][0]["code"] != "local_pdf_missing"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
