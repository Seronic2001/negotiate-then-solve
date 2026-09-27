"""Policy documents in whatever form the institute has them (proposal L3).

The policy agent retrieves from a list of ``Rule``s. This module builds that
list from files in any of these forms:

* Markdown (the handbook: ``## <number> <title> [RULE-ID]`` headings);
* HTML pages: scripts, navigation, headers, footers, cookie banners and side
  panels are dropped; headings, paragraphs, lists and tables are kept;
* PDFs: the text layer page by page; a page without one (a scan) is rendered
  and read by OCR;
* images (a scan, a phone photo of a notice): OCR.

OCR backends, chosen with ``NTS_OCR`` or ``--ocr``:

* ``rapidocr`` (default): PaddleOCR's PP-OCR detector and English recogniser
  as ONNX, on the CPU. The English model (9 MB) is downloaded on first use;
  the bundled Chinese-English one drops the spaces between English words.
* ``unlimited``: Baidu's Unlimited-OCR (3B, MIT) behind a vLLM server
  (``NTS_OCR_URL``, e.g. ``http://gpu-box:8000/v1``). It needs 8 GB of VRAM
  in bf16, so it runs on a GPU machine or Kaggle, not on the laptop. Pages
  it has already read can also be supplied as a ``<file>.ocr.json`` sidecar
  written by ``notebooks/unlimited_ocr_kaggle.ipynb``; sidecars take
  precedence over the live backend.

OCR results are cached by image hash in ``runs/ocr_cache``. The extracted
text is then cut into rules at numbered headings ("3.2 Timetable changes",
"2. Capacity. ..."); a document without them is cut into paragraph chunks.
Rules keep their provenance (file, pages, and whether the text came from a
text layer, HTML or OCR), and the IDs are ``<DOC>-<number>`` unless the
document gives its own ``[ID]``.

    uv run python -m agents.documents                       # ingest data/policies and run demo queries
    uv run python -m agents.documents some.pdf --show-text  # one file, with the extracted text
    NTS_OCR=unlimited NTS_OCR_URL=http://host:8000/v1 uv run python -m agents.documents
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
import re
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .policy import BM25, Rule, load_handbook

ROOT = Path(__file__).resolve().parents[2]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUFFIXES = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", *IMAGE_SUFFIXES}
MIN_TEXT_LAYER = 40  # characters; fewer means the page is a scan


@dataclass
class Page:
    number: int
    text: str
    method: str  # "text layer", "html", "markdown", "ocr: <backend>"
    confidence: float | None = None


@dataclass
class DocumentReport:
    name: str
    kind: str
    pages: list[Page] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None

    def summary(self) -> dict:
        conf = [p.confidence for p in self.pages if p.confidence is not None]
        return {"name": self.name, "kind": self.kind, "pages": len(self.pages),
                "methods": dict(Counter(p.method for p in self.pages)),
                "ocr_confidence": sum(conf) / len(conf) if conf else None,
                "rules": [r.id for r in self.rules], "seconds": round(self.seconds, 2), "error": self.error}


# ---------------------------------------------------------------------------
# OCR backends
# ---------------------------------------------------------------------------


class OCRBackend(Protocol):
    name: str

    def read(self, image) -> tuple[str, float | None]:
        """Text of a page image (lines, blank lines between paragraphs) and a confidence if known."""
        ...


EN_REC_URL = "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv3/en_PP-OCRv3_rec_infer.onnx"


class RapidOCRBackend:
    """PP-OCR text detection + English recognition (ONNX, CPU).

    The page is read once at the detector's default size. Lines that come back
    with low confidence (the detector's box was too coarse, so the crop is
    unreadable) get a second look at a larger detection size, and only those
    lines are replaced; a larger size for the whole page merges or splits
    other lines."""

    name = "rapidocr"
    LOW = 0.5  # recognition score below which a line gets a second look

    def __init__(self, model_dir: Path | str = ROOT / "runs" / "ocr_models") -> None:
        self.model_dir = Path(model_dir)
        self._engines: dict[int | None, object] = {}
        self.model = "PP-OCRv4 det + PP-OCRv3 en rec"

    def _engine(self, side: int | None = None):
        if side not in self._engines:
            from rapidocr_onnxruntime import RapidOCR

            rec = self.model_dir / "en_PP-OCRv3_rec_infer.onnx"
            if not rec.exists():
                try:
                    self.model_dir.mkdir(parents=True, exist_ok=True)
                    urllib.request.urlretrieve(EN_REC_URL, rec)
                except OSError:
                    rec.unlink(missing_ok=True)  # offline: the bundled recogniser still works, without spaces
            opts = {"det_limit_side_len": side} if side else {}
            if rec.exists():
                self._engines[side] = RapidOCR(rec_model_path=str(rec), **opts)
            else:
                self._engines[side], self.model = RapidOCR(**opts), "PP-OCRv4 (bundled ch+en rec)"
        return self._engines[side]

    def read(self, image) -> tuple[str, float | None]:
        import numpy as np

        img = np.array(image.convert("RGB"))
        result, _ = self._engine()(img, text_score=0.0)
        result = list(result or [])
        weak = [r for r in result if float(r[2]) < self.LOW]
        if weak:
            closer, _ = self._engine(1600)(img, text_score=self.LOW)
            result = [r for r in result if float(r[2]) >= self.LOW]
            for w in weak:
                top, bottom = min(p[1] for p in w[0]), max(p[1] for p in w[0])
                match = max(closer or [], key=lambda c: _overlap(top, bottom, c[0]), default=None)
                if match is not None and _overlap(top, bottom, match[0]) > 0.5 and all(match[1] != r[1] for r in result):
                    result.append(match)
        if not result:
            return "", None
        # Deskew: a photo is rarely straight. The boxes run along their lines, so
        # their median slope is the page's angle; rotate the corners back by it.
        slopes = sorted(math.atan2(b[1][1] - b[0][1], b[1][0] - b[0][0]) for b, _, _ in result)
        a = slopes[len(slopes) // 2]
        cos, sin = math.cos(a), math.sin(a)
        boxes = []
        for box, text, score in result:
            xs = [x * cos + y * sin for x, y in box]
            ys = [-x * sin + y * cos for x, y in box]
            boxes.append((min(ys), max(ys), min(xs), max(xs), text, float(score)))
        return layout(boxes), sum(b[5] for b in boxes) / len(boxes)


def _overlap(top: float, bottom: float, box) -> float:
    """Share of the band [top, bottom] that ``box`` covers vertically."""
    t, b = min(p[1] for p in box), max(p[1] for p in box)
    return max(0.0, min(bottom, b) - max(top, t)) / max(1e-6, bottom - top)


def layout(boxes: list[tuple[float, float, float, float, str, float]]) -> str:
    """Text boxes (top, bottom, left, right, text, score) to lines in reading
    order, with a blank line where a new paragraph starts: a large vertical
    gap, or a line that starts well right of the margin (a signature, a
    centred title)."""
    boxes = sorted(boxes, key=lambda b: (b[0] + b[1]) / 2)
    heights = sorted(b[1] - b[0] for b in boxes)
    h = heights[len(heights) // 2] or 1.0
    lines: list[list] = []
    for b in boxes:
        mid = (b[0] + b[1]) / 2
        if lines and abs(mid - lines[-1][0]) < 0.5 * h:  # same line: another box to the right
            lines[-1][1].append(b)
        else:
            lines.append([mid, [b]])
    margin = min(b[2] for b in boxes)
    width = max(b[3] for b in boxes) - margin or 1.0
    out, prev, prev_indented = [], None, False
    for mid, parts in lines:
        parts = sorted(parts, key=lambda p: p[2])
        indented = parts[0][2] - margin > 0.25 * width
        if prev is not None and (mid - prev > 1.9 * h or indented != prev_indented):
            out.append("")
        out.append(" ".join(p[4] for p in parts))
        prev, prev_indented = mid, indented
    return "\n".join(out)


_REF = re.compile(r"<\|ref\|>(.*?)<\|/ref\|>", re.S)
_DET = re.compile(r"<\|det\|>.*?<\|/det\|>", re.S)
_SPECIAL = re.compile(r"<\|[^|>]{1,40}\|>")


def clean_grounding(text: str) -> str:
    """Unlimited-OCR marks regions as ``<|ref|>label<|/ref|><|det|>[[boxes]]<|/det|>``;
    keep the text, drop the boxes and any other special tokens."""
    return _SPECIAL.sub("", _DET.sub("", _REF.sub(r"\1", text))).strip()


class UnlimitedOCRBackend:
    """Baidu Unlimited-OCR on an OpenAI-compatible vLLM server
    (``vllm serve baidu/Unlimited-OCR --trust-remote-code
    --logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor``)."""

    name = "unlimited-ocr"

    def __init__(self, base_url: str | None = None, model: str = "baidu/Unlimited-OCR", timeout: float = 300) -> None:
        self.base_url = (base_url or os.environ.get("NTS_OCR_URL", "http://localhost:8000/v1")).rstrip("/")
        self.model = model
        self.timeout = timeout

    def read(self, image) -> tuple[str, float | None]:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "<image>document parsing."},
                                                      {"type": "image_url", "image_url": {"url": url}}]}],
            "max_tokens": 8192, "temperature": 0, "skip_special_tokens": False,
            "vllm_xargs": {"ngram_size": 35, "window_size": 128},  # the model card's anti-looping settings
        }
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            text = json.loads(resp.read())["choices"][0]["message"]["content"]
        return clean_grounding(text), None


class CachedOCR:
    """Any backend, with results cached by image hash."""

    def __init__(self, backend: OCRBackend, cache_dir: Path | str = ROOT / "runs" / "ocr_cache") -> None:
        self.backend = backend
        self.name = backend.name
        self.cache_dir = Path(cache_dir)

    def read(self, image) -> tuple[str, float | None]:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        key = hashlib.sha256(self.name.encode() + buf.getvalue()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d["text"], d["confidence"]
        text, conf = self.backend.read(image)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"backend": self.name, "text": text, "confidence": conf}), encoding="utf-8")
        return text, conf


def ocr_backend(name: str | None = None) -> CachedOCR:
    name = name or os.environ.get("NTS_OCR", "rapidocr")
    if name in ("unlimited", "unlimited-ocr"):
        return CachedOCR(UnlimitedOCRBackend())
    if name == "rapidocr":
        return CachedOCR(RapidOCRBackend())
    raise ValueError(f"unknown OCR backend {name!r} (rapidocr, unlimited)")


# ---------------------------------------------------------------------------
# Extraction: file -> pages of text
# ---------------------------------------------------------------------------


def kind_of(path: Path) -> str:
    s = path.suffix.lower()
    return ("pdf" if s == ".pdf" else "html" if s in (".html", ".htm") else "image" if s in IMAGE_SUFFIXES
            else "markdown")


def sidecar(path: Path) -> dict[int, str] | None:
    """Pages read elsewhere (the Unlimited-OCR notebook): ``{"model": ..., "pages": {"1": "..."}}``."""
    f = path.with_name(path.name + ".ocr.json")
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return {int(k): clean_grounding(v) for k, v in d["pages"].items()} | {0: d.get("model", "unknown model")}


def extract(path: Path, ocr: OCRBackend | None = None, dpi: int = 220) -> list[Page]:
    kind = kind_of(path)
    if kind == "markdown":
        return [Page(1, path.read_text(encoding="utf-8"), "markdown")]
    if kind == "html":
        return [Page(1, html_text(path.read_text(encoding="utf-8", errors="replace")), "html")]
    pre = sidecar(path)
    ocr = ocr or ocr_backend()

    def read(n: int, image) -> Page:
        if pre and n in pre:
            return Page(n, pre[n], f"ocr: {pre[0]} (precomputed)")
        text, conf = ocr.read(image)
        return Page(n, text, f"ocr: {ocr.name}", conf)

    if kind == "image":
        from PIL import Image, ImageOps

        return [read(1, ImageOps.exif_transpose(Image.open(path)))]
    import pypdfium2 as pdfium

    pages = []
    pdf = pdfium.PdfDocument(path)
    try:
        for i, page in enumerate(pdf, 1):
            text = page.get_textpage().get_text_range().replace("\r\n", "\n").replace("�", "·")
            if len(text.strip()) >= MIN_TEXT_LAYER:
                pages.append(Page(i, text, "text layer"))
            else:
                pages.append(read(i, page.render(scale=dpi / 72).to_pil()))
    finally:
        pdf.close()
    return pages


_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg", "iframe")
_DROP_CLASS = re.compile(r"cookie|banner|breadcrumb|menu|sidebar|share|social|skip", re.I)


def html_text(html: str) -> str:
    """The content of a web page as Markdown-ish text: headings, paragraphs,
    list items and table rows, without the site's navigation and chrome."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.attrs is not None and _DROP_CLASS.search(" ".join(tag.get("class", [])) + " " + (tag.get("id") or "")):
            tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    out = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "caption", "tr", "dt", "dd", "blockquote"]):
        if el.find_parent(["li", "tr", "blockquote"]) and el.name not in ("tr",):
            continue  # nested block: its parent already carries the text
        if el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["th", "td"])]
            text = " | ".join(c for c in cells if c)
        else:
            text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name[0] == "h":
            out += ["", "#" * int(el.name[1]) + " " + text]
        elif el.name == "li":
            out.append("- " + text)
        else:
            out += ["", text] if el.name == "p" else [text]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ---------------------------------------------------------------------------
# Segmentation: pages -> rules
# ---------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_NUMBERED = re.compile(r"^(?:§\s*)?(?P<num>\d+(?:\.\d+)+\.?|\d+[.)])(?:\s+|(?=[A-Z]))(?P<rest>\S.*)$")  # OCR: "1.Fixed"
_ID = re.compile(r"\s*\[(?P<id>[A-Z][A-Z0-9-]{1,30})\]\s*$")
_INLINE_TITLE = re.compile(r"^(?P<title>[A-Z][^.:]{2,60}?)[.:]\s+(?P<body>\S.*)$")
_PAGE_NO = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.I)
_STRAY_DOT = re.compile(r"\b([a-z]{2,})\.(?=[a-z]{2,}\b)")  # OCR: "moved.only" -> "moved only"


def ocr_clean(text: str) -> str:
    return re.sub(r"\.{2,}", ".", _STRAY_DOT.sub(r"\1 ", text))


PARA = "\u2029"  # paragraph break inside a rule's body


def _boilerplate(pages: list[Page]) -> set[str]:
    """Lines repeated on most pages (running headers and footers)."""
    if len(pages) < 2:
        return set()
    seen = Counter(line for p in pages for line in {ln.strip() for ln in p.text.splitlines() if ln.strip()})
    return {line for line, n in seen.items() if n >= max(2, len(pages) * 0.6)}


def prefix_for(name: str) -> str:
    word = re.findall(r"[a-z]+", Path(name).stem.lower()) or ["doc"]
    return word[0][:6].upper()


def _heading(line: str, markdown: bool) -> tuple[str, str, str | None, str] | None:
    """(number, title, explicit id, body on the same line), or None."""
    text = line
    if markdown and (m := _MD_HEADING.match(line)):
        text = m[1]
    elif markdown:
        return None
    rule_id = None
    if m := _ID.search(text):
        rule_id, text = m["id"], text[: m.start()]
    n = _NUMBERED.match(text)
    if not n:
        return ("", text.strip(), rule_id, "") if markdown else None
    num, rest = n["num"].rstrip(".)"), n["rest"].strip()
    if m := _INLINE_TITLE.match(rest):
        if len(m["title"].split()) <= 7:
            return num, m["title"].strip(), rule_id, m["body"]
    if len(rest.split()) <= 9 and not rest.endswith((".", ",", ";")):
        return num, rest, rule_id, ""
    if markdown:
        return num, rest, rule_id, ""
    return None  # a numbered sentence, not a heading ("30 students ..." never gets here: no dot)


def segment(name: str, pages: list[Page], method_of: dict[int, str] | None = None) -> list[Rule]:
    """Cut a document's text into rules at its numbered headings."""
    drop = _boilerplate(pages)
    prefix = prefix_for(name)
    rules: list[Rule] = []
    cur: dict | None = None

    def close(last: bool = False) -> None:
        if cur and (cur["body"] or cur["num"]):
            paras = " ".join(cur["body"]).split(PARA)
            if last and len(paras) > 1 and len(paras[-1].split()) <= 6:
                paras = paras[:-1]  # a signature under the last rule ("Registrar (Academic)")
            text = re.sub(r"\s+", " ", " ".join(paras)).strip()
            rules.append(Rule(id=cur["id"] or f"{prefix}-{cur['num'] or len(rules) + 1}", number=cur["num"],
                              title=cur["title"], text=text, source=name, pages=tuple(sorted(cur["pages"])),
                              method=cur["method"]))

    unnumbered = []  # markdown headings without a number: used only if nothing is numbered
    for p in pages:
        text = ocr_clean(p.text) if p.method.startswith("ocr") else p.text
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                if cur is not None and cur["body"] and cur["body"][-1] != PARA:
                    cur["body"].append(PARA)
                continue
            if line in drop or _PAGE_NO.match(line):
                continue
            h = _heading(line, line.startswith("#"))  # Markdown headings from any source (HTML, Unlimited-OCR)
            if h and (h[0] or h[2]):
                close()
                cur = {"num": h[0], "title": h[1], "id": h[2], "body": [h[3]] if h[3] else [], "pages": {p.number},
                       "method": p.method}
            elif h:
                unnumbered.append((h[1], p))
            elif cur is not None:
                if cur["body"] and cur["body"][-1] != PARA and cur["body"][-1].endswith("-") and line[:1].islower():
                    cur["body"][-1] = cur["body"][-1] + line  # "lab in-" + "charge"
                else:
                    cur["body"].append(line.lstrip("-• ").strip())
                cur["pages"].add(p.number)
    close(last=True)
    if not rules:
        rules = _chunks(name, pages, drop)
    return rules


def _chunks(name: str, pages: list[Page], drop: set[str], words: int = 120) -> list[Rule]:
    """No headings: paragraph chunks of about ``words`` words, each its own rule."""
    prefix, out, buf, where = prefix_for(name), [], [], set()

    def flush(method: str) -> None:
        if buf:
            text = " ".join(buf)
            out.append(Rule(id=f"{prefix}-{len(out) + 1}", number=str(len(out) + 1),
                            title=" ".join(text.split()[:8]) + "…", text=text, source=name,
                            pages=tuple(sorted(where)), method=method))
            buf.clear()
            where.clear()

    for p in pages:
        for para in re.split(r"\n\s*\n", p.text):
            lines = [ln.strip() for ln in para.splitlines() if ln.strip() and ln.strip() not in drop]
            if not lines:
                continue
            buf.append(re.sub(r"^#+\s*", "", " ".join(lines)))
            where.add(p.number)
            if sum(len(b.split()) for b in buf) >= words:
                flush(p.method)
        flush(p.method)
    return out


# ---------------------------------------------------------------------------
# The corpus the policy agent retrieves from
# ---------------------------------------------------------------------------


def ingest(path: Path, ocr: OCRBackend | None = None) -> DocumentReport:
    t = time.perf_counter()
    report = DocumentReport(name=path.name, kind=kind_of(path))
    try:
        report.pages = extract(path, ocr)
        report.rules = segment(path.name, report.pages)
    except Exception as e:  # one unreadable file must not take the handbook down
        report.error = f"{type(e).__name__}: {e}"
    report.seconds = time.perf_counter() - t
    return report


def policy_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir()
                  if f.is_file() and f.suffix.lower() in SUFFIXES and not f.name.endswith(".ocr.json")
                  and f.name.lower() != "readme.md") if folder.exists() else []


def load_corpus(handbook: Path | None, folder: Path | None, ocr: OCRBackend | None = None
                ) -> tuple[list[Rule], list[DocumentReport]]:
    """The handbook's rules followed by the rules of every document in ``folder``.
    Colliding IDs get a suffix, so every citation stays unique."""
    rules: list[Rule] = []
    reports: list[DocumentReport] = []
    if handbook is not None:
        hb = load_handbook(handbook)
        rules += hb
        reports.append(DocumentReport(handbook.name, "markdown", [Page(1, "", "markdown")], hb))
    for f in policy_files(folder) if folder else []:
        r = ingest(f, ocr)
        reports.append(r)
        rules += r.rules
    seen: Counter = Counter()
    unique = []
    for r in rules:
        seen[r.id] += 1
        unique.append(r if seen[r.id] == 1 else Rule(**{**r.__dict__, "id": f"{r.id}-{seen[r.id]}"}))
    return unique, reports


DEMO_QUERIES = [
    "Can I move my Friday lecture to week 8?",
    "I want to shift my practical to another lab tomorrow",
    "Our guest lecturer wants to come on a different day next week",
    "Can I book the auditorium for a talk next Monday?",
    "How many invigilation duties can I get?",
    "Can I teach at 1 pm?",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path, help="files or folders (default: data/policies)")
    ap.add_argument("--handbook", type=Path, default=ROOT / "data" / "handbook.md")
    ap.add_argument("--ocr", default=None, help="rapidocr (default) or unlimited")
    ap.add_argument("--show-text", action="store_true", help="print the text extracted from each page")
    ap.add_argument("--query", action="append", help="retrieval query to try (repeatable)")
    args = ap.parse_args()

    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the Windows console defaults to cp1252
    ocr = ocr_backend(args.ocr)
    targets = args.paths or [ROOT / "data" / "policies"]
    files = [f for t in targets for f in (policy_files(t) if t.is_dir() else [t])]
    reports = [ingest(f, ocr) for f in files]
    for r in reports:
        s = r.summary()
        conf = f", OCR confidence {s['ocr_confidence']:.2f}" if s["ocr_confidence"] is not None else ""
        print(f"\n{r.name}  [{r.kind}, {s['pages']} page(s), {', '.join(f'{k} ×{v}' for k, v in s['methods'].items())}"
              f"{conf}, {s['seconds']} s]")
        if r.error:
            print(f"  ERROR {r.error}")
        if args.show_text:
            for p in r.pages:
                print(f"  --- page {p.number} ({p.method})\n" + "\n".join("  | " + ln for ln in p.text.splitlines()))
        for rule in r.rules:
            print(f"  {rule.id:14s} {rule.title[:48]:48s} p.{','.join(map(str, rule.pages))}  {rule.text[:70]}…")

    rules, _ = load_corpus(args.handbook if args.handbook.exists() else None, None)
    rules += [x for r in reports for x in r.rules]
    bm = BM25(rules)
    print(f"\nRetrieval over {len(rules)} rules (handbook + documents):")
    for q in args.query or DEMO_QUERIES:
        top = bm.search(q, 3)
        print(f"\n  “{q}”")
        for r in top:
            print(f"    {r.id:14s} {r.title[:44]:44s} ← {r.source}, p.{','.join(map(str, r.pages))} ({r.method})")


if __name__ == "__main__":
    main()
