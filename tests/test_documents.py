"""Policy documents in any format: extraction, OCR routing, segmentation,
the corpus, and the upload endpoint. A fake OCR backend keeps these fast and
offline; the one test with the real OCR model is marked slow."""

import base64
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from agents.documents import (
    Page,
    clean_grounding,
    extract,
    html_text,
    ingest,
    layout,
    load_corpus,
    segment,
)

SAMPLES = Path("data/policies")


class FakeOCR:
    name = "fake"

    def __init__(self, text: str = "1. Fixed windows. Guest faculty teach only in agreed windows.") -> None:
        self.text = text
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return self.text, 0.9


def test_html_keeps_content_and_drops_site_chrome():
    text = html_text((SAMPLES / "room-bookings.html").read_text(encoding="utf-8"))
    assert "## 4.1 Auditorium bookings" in text and "Seminar Room 1 | 40 | Projector" in text
    for chrome in ("cookies", "analytics", "Contact", "Privacy", "Related links"):
        assert chrome not in text


def test_pdf_text_layer_needs_no_ocr():
    ocr = FakeOCR()
    pages = extract(SAMPLES / "exam-regulations.pdf", ocr)
    assert [p.method for p in pages] == ["text layer", "text layer"] and ocr.calls == 0
    rules = segment("exam-regulations.pdf", pages)
    assert [r.id for r in rules] == ["EXAM-3.1", "EXAM-3.2", "EXAM-3.3", "EXAM-3.4", "EXAM-3.5"]
    assert rules[3].pages == (2,) and rules[0].source == "exam-regulations.pdf"
    joined = " ".join(r.text for r in rules)
    assert "Page 1 of 2" not in joined and "Office of the Controller" not in joined  # running header/footer


def test_scanned_pdf_goes_to_ocr():
    ocr = FakeOCR()
    pages = extract(SAMPLES / "guest-faculty-circular.pdf", ocr)
    assert ocr.calls == 1 and pages[0].method == "ocr: fake" and pages[0].confidence == 0.9


def test_sidecar_from_unlimited_ocr_takes_precedence(tmp_path):
    src = tmp_path / "scan.png"
    Image.new("RGB", (40, 40), "white").save(src)
    (tmp_path / "scan.png.ocr.json").write_text(json.dumps({
        "model": "baidu/Unlimited-OCR",
        "pages": {"1": "<|ref|>title<|/ref|><|det|>[[1,2,3,4]]<|/det|>\n## 2.1 Notice period\nMoves need a week."}}))
    ocr = FakeOCR()
    pages = extract(src, ocr)
    assert ocr.calls == 0 and pages[0].method == "ocr: baidu/Unlimited-OCR (precomputed)"
    assert [r.id for r in segment("scan.png", pages)] == ["SCAN-2.1"]


def test_segment_handles_ocr_artifacts_and_signatures():
    text = ("Circular No.AO/2026/14\nGuest and Visiting Faculty\n"
            "1.Fixed windows. Guest faculty teach only in agreed\nwindows.\n"
            "2. Notice period. A guest lecture may be moved.only with a week's notice..\n"
            "3. Supervision. A practical may run only when the lab in-\ncharge is present.\n\nRegistrar (Academic)")
    rules = segment("circular.pdf", [Page(1, text, "ocr: fake")])
    assert [(r.id, r.title) for r in rules] == [("CIRCUL-1", "Fixed windows"), ("CIRCUL-2", "Notice period"),
                                                 ("CIRCUL-3", "Supervision")]
    assert rules[1].text == "A guest lecture may be moved only with a week's notice."
    assert rules[2].text == "A practical may run only when the lab in-charge is present."  # hyphen joined, no signature


def test_explicit_ids_and_chunk_fallback():
    rules = segment("x.md", [Page(1, "## 7.1 Parking [P-PARK]\nStaff park in lot B.", "markdown")])
    assert rules[0].id == "P-PARK" and rules[0].number == "7.1"
    prose = segment("memo.txt", [Page(1, "Classes on the day of the convocation are cancelled.\n\nMake them up later.",
                                     "markdown")])
    assert len(prose) == 1 and prose[0].id == "MEMO-1" and "convocation" in prose[0].text


def test_layout_breaks_paragraphs_on_gaps_and_indents():
    boxes = [(0, 10, 0, 300, "1. First rule starts", 1.0), (12, 22, 0, 280, "and continues.", 1.0),
             (50, 60, 0, 300, "2. Second rule.", 1.0), (62, 72, 200, 300, "Signature", 1.0)]
    assert layout(boxes) == "1. First rule starts\nand continues.\n\n2. Second rule.\n\nSignature"


def test_clean_grounding():
    assert clean_grounding("<|ref|>Title<|/ref|><|det|>[[1,2,3,4]]<|/det|> text<|end|>") == "Title text"


def test_corpus_merges_documents_and_keeps_ids_unique(tmp_path):
    for f in ("room-bookings.html", "exam-regulations.pdf"):
        shutil.copy(SAMPLES / f, tmp_path / f)
    (tmp_path / "exam-regulations-copy.html").write_text("<h2>3.1 Examination weeks</h2><p>Duplicate.</p>")
    rules, reports = load_corpus(Path("data/handbook.md"), tmp_path, FakeOCR())
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids)) and "EXAM-3.1-2" in ids and "P-LUNCH" in ids
    assert {r.name for r in reports} >= {"handbook.md", "room-bookings.html", "exam-regulations.pdf"}


@pytest.mark.slow
def test_real_ocr_reads_the_notice_photo():
    report = ingest(SAMPLES / "lab-notice.jpg")
    assert [r.title for r in report.rules] == ["Advance notice", "Capacity", "Supervision", "Maintenance"]
    assert "48 hours" in report.rules[0].text and report.pages[0].confidence > 0.8


def test_upload_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from web.app import COORDINATOR, World, create_web_app

    monkeypatch.setenv("NTS_POLICY_DIR", str(tmp_path))
    c = TestClient(create_web_app(World(seed_history=False)))
    page = b"<html><nav>Menu</nav><main><h2>5.1 Field trips</h2><p>Trips need two weeks' notice.</p></main></html>"
    body = {"name": "trips.html", "data": base64.b64encode(page).decode()}
    assert c.post("/api/handbook/documents", json=body, headers={"X-User": "F-104"}).status_code == 403
    assert c.post("/api/handbook/documents", json={**body, "name": "x.exe"}, headers={"X-User": COORDINATOR}).status_code == 422
    r = c.post("/api/handbook/documents", json=body, headers={"X-User": COORDINATOR}).json()
    assert [x["id"] for x in r["rules"]] == ["TRIPS-5.1"]
    hits = c.get("/api/handbook/search?q=field trip notice", headers={"X-User": "F-104"}).json()["results"]
    assert hits[0]["id"] == "TRIPS-5.1" and hits[0]["source"] == "trips.html" and hits[0]["method"] == "html"
    assert c.get("/api/handbook/documents", headers={"X-User": "F-104"}).status_code == 403
    docs = c.get("/api/handbook/documents", headers={"X-User": COORDINATOR}).json()["documents"]
    assert any(d["name"] == "trips.html" for d in docs)
    assert c.delete("/api/handbook/documents/trips.html", headers={"X-User": COORDINATOR}).json() == {"removed": "trips.html"}
    assert all(r["source"] != "trips.html" for r in c.get("/api/handbook", headers={"X-User": "F-104"}).json())
