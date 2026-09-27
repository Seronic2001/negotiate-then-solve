"""The course offering document: what is taught this semester, by whom, to whom.

An institute publishes its offerings as a table (PDF, sometimes a scan or a
web page): one row per course with its code, name, L-T-P-C credits and
faculty, grouped under programme headings ("B.Tech II year I Semester –
CSE/CSD") and elective pools ("Robotics Stream", "Humanities Electives ...
Max. no of students for each course is 40").

    uv run python -m semester.offerings course-offering/CourseOfferings-M26-V7.pdf

Reading a table from a PDF's text layer in stream order interleaves wrapped
cells (a three-line faculty list starts above its row's code), so a PDF is
read by position: text runs are grouped into rows around the runs that
carry a course code, an L-T-P-C or a heading, and each wrapped run joins the
nearest such row. Scans and web pages go through ``agents.documents`` and the
same row parser.

From each row:

* ``L-T-P-C``: lecture, tutorial and practical hours per week, and credits;
* ``(H1)``/``(H2)``: taught in the first or second half of the semester;
  ``(H)``: one class a week for the whole semester;
* ``(40)`` after a name, or "Max. no of students ... is 40" on a pool: a cap;
* faculty separated by ``+``; "(Coordinator)" and centres are kept as names.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

CODE = re.compile(r"\b([A-Z]{2}\d\.\d{3}[a-z]?)(?![\w.])")
LTPC = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})\b")
CD = re.compile(r"^(Pr|PR|In|IN|OT|Ot)\b\s*")
AD = re.compile(r"^([A-Z]{2})\s+(?=[A-Z]{2}\d\.\d{3}|[A-Z][a-z])")
HALF = re.compile(r"\((H1|H2|H)\)")
CAP = re.compile(r"\((\d{2,3})\)")
COHORT = re.compile(r"^(B\.?\s?Tech|M\.?\s?Tech|M\.?\s?S\b|MS\b|Ph\.?\s?D|LE-|Dual|Integrated|M\.?\s?Sc|MBA|PG|UG)\b.*"
                    r"(Semester|year)", re.I)
POOL = re.compile(r"(Stream|Electives?\b|Bouquet)", re.I)
POOL_CAP = re.compile(r"(?:Max\.?\s*no\.?\s*of\s*students.*?|Registration\s+Limit:?\s*)(\d{2,3})", re.I)
SKIP = re.compile(r"^(CD AD|Code\b|Course No|Total\b|\d+ of \d+|Sd/-|Date:|Dean|CD -|AD -|L-T-P-C:|H1-1st|"
                  r"Course offerings in|UG Programmes|PG Programmes|\*)", re.I)


class Offering(BaseModel):
    code: str
    name: str
    L: int
    T: int
    P: int
    C: int
    faculty: list[str] = Field(default_factory=list)
    half: str = "full"  # full | H1 | H2 | H (one class a week, whole semester)
    cap: int | None = None
    cohorts: list[str] = Field(default_factory=list)  # programmes that require it (Pr/In)
    pools: list[str] = Field(default_factory=list)  # elective pools that list it
    category: str = ""  # the AD column (MA, CS, EC, HS, ...) or the code's letters
    scheduled: bool = True
    note: str = ""  # why it is not timetabled, if it is not

    @property
    def area(self) -> str:
        return self.code[:2]


class Cohort(BaseModel):
    """Students who take the same required courses (a programme and year)."""

    id: str
    name: str
    courses: list[str] = Field(default_factory=list)
    electives: list[str] = Field(default_factory=list)  # placeholders: "Open Elective-1", ...
    size: int = 0


class Pool(BaseModel):
    id: str
    name: str
    courses: list[str] = Field(default_factory=list)
    cap: int | None = None


class OfferingDoc(BaseModel):
    source: str
    semester: str = ""
    courses: dict[str, Offering] = Field(default_factory=dict)
    cohorts: list[Cohort] = Field(default_factory=list)
    pools: list[Pool] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def pdf_rows(path: Path) -> list[str]:
    """The PDF's table rows in reading order, with wrapped cells joined to their row."""
    import pypdfium2 as pdfium

    rows: list[str] = []
    pdf = pdfium.PdfDocument(path)
    try:
        for page in pdf:
            tp = page.get_textpage()
            runs = []
            for i in range(tp.count_rects()):
                left, bottom, right, top = tp.get_rect(i)
                text = tp.get_text_bounded(left, bottom, right, top).replace("￾", "-").strip()
                if text:
                    runs.append(((top + bottom) / 2, left, text))
            rows += _rows_from_runs(runs)
    finally:
        pdf.close()
    return rows


def _rows_from_runs(runs: list[tuple[float, float, str]]) -> list[str]:
    # Lines: runs within 4 pt of each other vertically.
    runs.sort(key=lambda r: (-r[0], r[1]))
    lines: list[list] = []
    for r in runs:
        if lines and abs(lines[-1][0] - r[0]) <= 4:
            lines[-1][1].append(r)
        else:
            lines.append([r[0], [r]])
    # Runs of one printed line sit a point or so apart: give them the line's position.
    lines = [[y, [(y, x, t) for _, x, t in runs_]] for y, runs_ in lines]
    credits_x = [x for _, runs_ in lines for _, x, t in runs_ if LTPC.match(t)]
    split_x = (sorted(credits_x)[len(credits_x) // 2] - 8) if credits_x else 330.0

    def anchor(line) -> bool:
        text = " ".join(t for _, _, t in line[1])
        return bool(CODE.search(text) or LTPC.search(text) or COHORT.search(text) or
                    (POOL.search(text) and not LTPC.search(text)) or SKIP.search(text))

    anchors = [i for i, ln in enumerate(lines) if anchor(ln)]
    members: dict[int, list] = {i: list(lines[i][1]) for i in anchors}
    offsets: dict[int, float] = {i: 0.0 for i in anchors}  # sum of attached lines' offsets from the anchor
    ties = []
    for i, ln in enumerate(lines):
        if i in members:
            continue
        near = sorted(anchors, key=lambda a: abs(lines[a][0] - ln[0]))[:2]
        near = [a for a in near if abs(lines[a][0] - ln[0]) <= 16]
        if not near:
            continue
        if len(near) == 2 and abs(abs(lines[near[0]][0] - ln[0]) - abs(lines[near[1]][0] - ln[0])) < 2:
            ties.append((i, near))  # equally close to two rows: decide after the clear cases
            continue
        members[near[0]] += ln[1]
        offsets[near[0]] += ln[0] - lines[near[0]][0]
    for i, near in ties:
        # A cell's lines are centred on its row: join the row this line balances.
        best = min(near, key=lambda a: abs(offsets[a] + lines[i][0] - lines[a][0]))
        members[best] += lines[i][1]
        offsets[best] += lines[i][0] - lines[best][0]
    # Codes stacked in one cell ("HS0.203a / &HS0.203b") become code-only rows:
    # fold them into the neighbouring row that has the credits but no code.
    code_only = re.compile(r"^[\s&/,]*(?:[A-Z]{2}\d\.\d{3}[a-z]?[\s&/,]*)+$")
    def text_of(a: int) -> str:
        return " ".join(t for _, _, t in members[a])

    stacked = [i for i in anchors if code_only.match(text_of(i))]
    hosts = [a for a in anchors if LTPC.search(text_of(a)) and not CODE.search(text_of(a))]
    moves = {}
    for i in stacked:  # decide every move before merging, so one host can take several codes
        near = [a for a in hosts if abs(lines[a][0] - lines[i][0]) <= 16]
        if near:
            moves[i] = min(near, key=lambda a: abs(lines[a][0] - lines[i][0]))
    for i, host in moves.items():
        members[host] = members[host] + [(lines[host][0], -1.0, t) for _, _, t in members[i]]  # codes first
        anchors.remove(i)
    out = []
    for i in anchors:
        parts = members[i]

        def key(r):
            _, x, t = r
            group = 0 if (CODE.search(t) or CD.match(t)) else (1 if x < split_x else 2)
            first = 0 if (group == 2 and LTPC.match(t)) else 1  # credits before the wrapped faculty lines
            return (group, first, -r[0], x)

        out.append(" ".join(t for _, _, t in sorted(parts, key=key)))
    return out


def text_rows(text: str) -> list[str]:
    """Rows from plain text (OCR or HTML): a row starts at a code, a heading or a CD tag."""
    rows: list[str] = []
    for line in (re.sub(r"\s*\|\s*", " ", ln).strip() for ln in text.splitlines()):  # HTML table cells
        if not line:
            continue
        starts = CODE.search(line[:24]) or CD.match(line) or COHORT.search(line) or SKIP.search(line) or (
            POOL.search(line) and not LTPC.search(line) and len(line) < 150)
        if starts or not rows:
            rows.append(line)
        else:
            rows[-1] += " " + line
    return rows


# ---------------------------------------------------------------------------
# Parsing rows
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper()[:40]


def _faculty(text: str) -> list[str]:
    names = [re.sub(r"\s+", " ", n).strip(" ,;") for n in text.split("+")]
    return [n for n in names if n and not LTPC.fullmatch(n)]


def parse_rows(rows: list[str], source: str = "") -> OfferingDoc:
    doc = OfferingDoc(source=source)
    section: Cohort | Pool | None = None
    skipped_credit_only = 0
    for row in rows:
        row = re.sub(r"\s+", " ", row.replace("–", "-").replace("—", "-")).strip()
        codes = CODE.findall(row)
        if len(codes) > 1 or (codes and not row.lstrip().startswith(codes[0]) and not CD.match(row)):
            # stacked codes ("HS0.203a &HS0.203b"): one course under the first code, after the CD/AD tags
            rest = re.sub(r"\s*[&/]?\s*(?:" + "|".join(map(re.escape, codes)) + r")\s*[&/]?", " ", row).strip()
            cd = CD.match(rest)
            tags = rest[: cd.end()] if cd else ""
            rest = rest[cd.end():] if cd else rest
            ad = AD.match(rest)
            tags += rest[: ad.end()] if ad else ""
            rest = rest[ad.end():] if ad else rest
            row = f"{tags}{codes[0]} {rest}".strip()
        if m := re.search(r"Semester\s+I+\s*\((Monsoon|Spring)\)|(Monsoon|Spring)\s+20\d\d", row):
            doc.semester = doc.semester or row[:80]
        if SKIP.search(row) and not CODE.search(row):
            continue
        code = CODE.search(row)
        ltpc = LTPC.search(row)
        if not code and not ltpc:
            if COHORT.search(row):
                section = Cohort(id=_slug(row), name=row)
                doc.cohorts.append(section)
            elif POOL.search(row) and len(row) < 160:
                if isinstance(section, Pool) and (m := POOL_CAP.search(row)) and section.name in row:
                    section.cap = int(m[1])
                    continue
                section = Pool(id=_slug(row.split("(")[0]), name=row.split("(Random")[0].strip(),
                               cap=int(m[1]) if (m := POOL_CAP.search(row)) else None)
                doc.pools.append(section)
            elif isinstance(section, Pool) and (m := POOL_CAP.search(row)):
                section.cap = int(m[1])
            continue
        if not ltpc:
            if re.search(r"\b\d{1,2}\s*Cr\b", row):
                skipped_credit_only += 1  # thesis, seminar, project: no class meetings
            else:
                doc.warnings.append(f"no L-T-P-C in row: {row[:90]}")
            continue
        L, T, P, C = (int(g) for g in ltpc.groups())
        head, tail = row[: ltpc.start()], row[ltpc.end():]
        cd = CD.match(head)
        kind = cd[1].lower() if cd else ""
        head = head[cd.end():] if cd else head
        category = ""
        if (a := AD.match(head)) and not CODE.match(head):
            category, head = a[1], head[a.end():]
        if not code or code.start() > ltpc.start():
            # a placeholder the cohort fills from a pool ("Open Elective-1", "Bouquet Core")
            if isinstance(section, Cohort):
                section.electives.append(re.sub(r"\s+", " ", head).strip())
            continue
        name = head.replace(code[1], "", 1)
        half = (m[1] if (m := HALF.search(name + " " + tail)) else "full")
        cap = int(m[1]) if (m := CAP.search(name)) else None
        name = re.sub(r"\s+", " ", CAP.sub("", HALF.sub("", name))).strip(" -")
        faculty = _faculty(HALF.sub("", tail))
        c = doc.courses.get(code[1])
        if c is None:
            c = Offering(code=code[1], name=name, L=L, T=T, P=P, C=C, faculty=faculty, half=half, cap=cap,
                         category=category or code[1][:2])
            doc.courses[c.code] = c
        else:
            if (L, T, P) != (c.L, c.T, c.P):
                doc.warnings.append(f"{c.code}: L-T-P {L}-{T}-{P} here, {c.L}-{c.T}-{c.P} earlier; keeping the first")
            c.faculty = c.faculty or faculty
            c.cap = c.cap or cap
        if isinstance(section, Cohort) and kind != "ot":
            if c.code not in section.courses:
                section.courses.append(c.code)
            if section.id not in c.cohorts:
                c.cohorts.append(section.id)
        elif isinstance(section, Pool):
            section.courses.append(c.code)
            c.pools.append(section.id)
            if section.cap and not c.cap:
                c.cap = section.cap
        elif section is None:
            doc.warnings.append(f"{c.code} appears before any programme or pool heading")
    if skipped_credit_only:
        doc.warnings.append(f"{skipped_credit_only} thesis/seminar/project rows have credits but no L-T-P: not timetabled")
    for c in doc.courses.values():
        if any("physical education" in f.lower() for f in c.faculty):
            c.scheduled, c.note = False, "run by the Physical Education Centre"
        elif not c.faculty and (c.P >= 6 or re.search(r"honou?rs|project|BTP", c.name, re.I)):
            c.scheduled, c.note = False, "project work, no class meetings"
    doc.cohorts = [c for c in doc.cohorts if c.courses or c.electives]
    doc.pools = [p for p in doc.pools if p.courses]
    return doc


def parse_offerings(path: Path) -> OfferingDoc:
    """Any readable file: PDFs by position; scans, images and web pages through agents.documents."""
    if path.suffix.lower() == ".pdf":
        rows = pdf_rows(path)
        if sum(bool(CODE.search(r)) for r in rows) >= 3:
            return parse_rows(rows, path.name)
    from agents.documents import extract

    text = "\n".join(p.text for p in extract(path))
    return parse_rows(text_rows(text), path.name)


def main() -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--all", action="store_true", help="list every course")
    args = ap.parse_args()
    doc = parse_offerings(args.path)
    print(f"{doc.source}: {len(doc.courses)} courses, {len(doc.cohorts)} cohorts, {len(doc.pools)} pools")
    for c in doc.cohorts:
        print(f"  cohort {c.name}: {', '.join(c.courses)}" + (f"  + {', '.join(c.electives)}" if c.electives else ""))
    for p in doc.pools:
        print(f"  pool {p.name} (cap {p.cap}): {len(p.courses)} courses")
    print("L-T-P patterns:", dict(Counter(f"{c.L}-{c.T}-{c.P}" for c in doc.courses.values()).most_common(8)))
    print("halves:", dict(Counter(c.half for c in doc.courses.values())))
    if args.all:
        for c in doc.courses.values():
            print(f"  {c.code} {c.name[:44]:44s} {c.L}-{c.T}-{c.P}-{c.C} {c.half:4s} cap={c.cap} "
                  f"fac={' + '.join(c.faculty)[:40]} cohorts={len(c.cohorts)} pools={len(c.pools)}")
    for w in doc.warnings:
        print("  warning:", w)


if __name__ == "__main__":
    main()
