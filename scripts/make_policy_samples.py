"""Build the sample policy documents in data/policies/ (one per input type).

    uv run python scripts/make_policy_samples.py

* exam-regulations.pdf        a digital PDF with a text layer (2 pages, header/footer, a table)
* guest-faculty-circular.pdf  a scanned PDF: page images only, no text layer
* lab-notice.jpg              a photo of a notice board (tilted, uneven light, noise)
* room-bookings.html          a web page with navigation, a cookie banner and a footer around the rules

The PDF and the images are rendered from HTML with headless Chrome, then the
scan and the photo are degraded with Pillow. Needs Chrome (or Edge).
"""

from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "data" / "policies"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "google-chrome", "chromium", "chrome"]

PAGE_CSS = """
body { font-family: 'Times New Roman', serif; font-size: 12.5pt; line-height: 1.45; color: #111; margin: 0; }
.page { padding: 24mm 22mm; }
h1 { font-size: 17pt; margin: 0 0 4pt; } h2 { font-size: 13pt; margin: 16pt 0 4pt; }
.meta { color: #444; font-size: 10.5pt; margin-bottom: 14pt; }
table { border-collapse: collapse; margin: 6pt 0; } td, th { border: 1px solid #555; padding: 3pt 8pt; }
"""

EXAM = f"""<html><head><style>{PAGE_CSS}
@page {{ size: A4; margin: 0; }}
.hdr {{ font-size: 9pt; color: #555; border-bottom: 1px solid #999; padding-bottom: 3pt; margin-bottom: 14pt; }}
.ftr {{ font-size: 9pt; color: #555; margin-top: 30pt; text-align: center; }}
.break {{ page-break-after: always; }}
</style></head><body>
<div class="page break">
<div class="hdr">Office of the Controller of Examinations · Regulations 2026-27</div>
<h1>Regulations for the Conduct of Examinations</h1>
<div class="meta">Approved by the Academic Council on 12 June 2026. Applies to all undergraduate programmes.</div>
<h2>3.1 Examination weeks</h2>
<p>Mid-semester examinations are held in week 8 and end-semester examinations in week 16 of the teaching
calendar. No regular classes are scheduled in these weeks.</p>
<h2>3.2 Timetable changes around examinations</h2>
<p>No change to the teaching timetable may take effect in weeks 7, 8, 15 or 16 without the written
approval of the Controller of Examinations. Requests for these weeks are forwarded to the examination cell.</p>
<h2>3.3 Invigilation duties</h2>
<p>Every faculty member is assigned at most two invigilation duties per examination week. A faculty member
on invigilation duty may not be scheduled to teach in the same slot.</p>
<table><tr><th>Session</th><th>Time</th></tr><tr><td>Morning</td><td>9:30 to 12:30</td></tr>
<tr><td>Afternoon</td><td>14:00 to 17:00</td></tr></table>
<div class="ftr">Page 1 of 2</div>
</div>
<div class="page">
<div class="hdr">Office of the Controller of Examinations · Regulations 2026-27</div>
<h2>3.4 Make-up tests</h2>
<p>A student who misses a mid-semester examination for a documented medical reason may take a make-up
test within ten working days. The make-up test is scheduled by the examination cell, not by the course
teacher.</p>
<h2>3.5 Extra classes before examinations</h2>
<p>Extra revision classes in week 7 or week 15 are allowed only outside the regular timetable, must not
exceed two hours per course, and must be announced to students at least three working days in advance.</p>
<div class="ftr">Page 2 of 2</div>
</div></body></html>"""

CIRCULAR = f"""<html><head><style>{PAGE_CSS} body {{ width: 794px; }} .page {{ padding: 60px 70px; }}</style></head><body><div class="page">
<p style="text-align:right">Circular No. AO/2026/14<br>Date: 3 August 2026</p>
<h1>Guest and Visiting Faculty</h1>
<div class="meta">From the Academic Office to all Heads of Department and the timetable coordinator.</div>
<p><b>1. Fixed windows.</b> Guest faculty teach only in the availability windows agreed in their
appointment letter. These windows are fixed institutional commitments and may not be negotiated away
by other faculty members.</p>
<p><b>2. Notice period.</b> A guest lecture may be moved only with at least one week's notice and the
written agreement of the guest faculty member.</p>
<p><b>3. Teaching load.</b> A guest faculty member teaches at most eight contact hours per week, and
never more than three hours on a single day.</p>
<p><b>4. Rooms.</b> Guest lectures are held in lecture rooms with a projector; the Head of Department
confirms the room when the window is fixed.</p>
<p style="margin-top:40px">Registrar (Academic)</p>
</div></body></html>"""

NOTICE = """<html><head><style>
body { margin: 0; background: #f4efe2; font-family: Arial, sans-serif; width: 900px; }
.n { margin: 40px; padding: 36px 44px; background: #fffdf5; border: 3px solid #2a2a2a; }
h1 { text-align: center; font-size: 34px; margin: 0 0 6px; letter-spacing: 2px; }
h2 { text-align: center; font-size: 22px; margin: 0 0 22px; font-weight: normal; }
p { font-size: 20px; line-height: 1.45; margin: 0 0 16px; }
.s { text-align: right; font-size: 18px; margin-top: 26px; }
</style></head><body><div class="n">
<h1>NOTICE</h1><h2>Computing Laboratories: Lab 1, Lab 2, Lab 3</h2>
<p><b>1. Advance notice.</b> A practical may be moved into a different laboratory only if the change is
requested at least 48 hours in advance.</p>
<p><b>2. Capacity.</b> No more than 30 students may be present in a laboratory during a practical. Larger
sections must be split into batches.</p>
<p><b>3. Supervision.</b> A practical may run only when a faculty member or the lab in-charge is present.</p>
<p><b>4. Maintenance.</b> Laboratories are closed for maintenance on the first Saturday of every month.</p>
<p class="s">Lab in-charge, Department of CSE</p>
</div></body></html>"""

BOOKINGS = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Room and event bookings | Academic Office</title>
<script>window.analytics = { track: function () {} }; analytics.track("page");</script>
<style>nav a { margin-right: 12px } .cookie { background: #eee; padding: 8px }</style></head>
<body>
<div class="cookie">We use cookies to improve this site. <button>Accept</button></div>
<header><nav><a href="/">Home</a><a href="/academics">Academics</a><a href="/notices">Notices</a><a href="/contact">Contact</a></nav></header>
<main>
<article>
<h1>Room and event bookings</h1>
<p class="lead">Last updated 20 July 2026 by the Academic Office.</p>
<h2>4.1 Auditorium bookings</h2>
<p>The auditorium is booked through the academic office at least five working days in advance.
During working hours, timetabled teaching takes priority over events.</p>
<h2>4.2 Seminar rooms for extra classes</h2>
<p>Seminar rooms may be booked for extra classes only outside timetabled hours. A booking made by a
faculty member for an extra class must name the course and the section.</p>
<h2>4.3 Cancelling a booking</h2>
<p>A booking that is no longer needed must be cancelled at least one working day in advance, so the
room can be offered to others.</p>
<table>
<caption>Bookable rooms</caption>
<tr><th>Room</th><th>Capacity</th><th>Equipment</th></tr>
<tr><td>Auditorium</td><td>300</td><td>Projector, audio</td></tr>
<tr><td>Seminar Room 1</td><td>40</td><td>Projector</td></tr>
<tr><td>Seminar Room 2</td><td>25</td><td>Whiteboard</td></tr>
</table>
</article>
<aside><h3>Related links</h3><ul><li><a href="/timetable">Timetable</a></li><li><a href="/exams">Examinations</a></li></ul></aside>
</main>
<footer>© 2026 Institute of Technology · <a href="/privacy">Privacy</a> · <a href="/accessibility">Accessibility</a></footer>
</body></html>"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    raise SystemExit("needs Chrome or Edge to render the samples")


def render(html: str, tmp: Path, name: str, *, pdf: bool = False, size: tuple[int, int] = (900, 1100)) -> Path:
    src = tmp / f"{name}.html"
    src.write_text(html, encoding="utf-8")
    out = tmp / (f"{name}.pdf" if pdf else f"{name}.png")
    args = [browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp / 'profile'}"]
    args += [f"--print-to-pdf={out}", "--no-pdf-header-footer"] if pdf else [f"--window-size={size[0]},{size[1]}", f"--screenshot={out}"]
    subprocess.run([*args, src.as_uri()], check=True, capture_output=True, timeout=120)
    return out


def scan(img: Image.Image, rng: random.Random) -> Image.Image:
    """A flatbed scan: greyscale, slightly skewed, speckled, soft."""
    g = img.convert("L").rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, expand=True, fillcolor=250)
    px = g.load()
    for _ in range(g.width * g.height // 180):
        x, y = rng.randrange(g.width), rng.randrange(g.height)
        px[x, y] = rng.choice((70, 120, 200))
    return ImageEnhance.Contrast(g.filter(ImageFilter.GaussianBlur(0.6))).enhance(1.25)


def photo(img: Image.Image, rng: random.Random) -> Image.Image:
    """A phone photo of a notice: tilted, with a light falloff across the page and sensor noise."""
    img = img.convert("RGB").rotate(rng.uniform(3, 5), resample=Image.BICUBIC, expand=True, fillcolor=(118, 104, 84))
    shade = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(shade)
    for i in range(img.width):
        d.line([(i, 0), (i, img.height)], fill=int(70 * i / img.width))
    img = Image.composite(Image.new("RGB", img.size, (40, 34, 26)), img, shade)
    noise = Image.effect_noise(img.size, 18).convert("RGB")
    return Image.blend(img, noise, 0.07).filter(ImageFilter.GaussianBlur(0.8))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        shutil.copy(render(EXAM, tmp, "exam", pdf=True), OUT / "exam-regulations.pdf")
        page = Image.open(render(CIRCULAR, tmp, "circular", size=(794, 1123)))
        scan(page, rng).save(OUT / "guest-faculty-circular.pdf", "PDF", resolution=120)
        notice = Image.open(render(NOTICE, tmp, "notice", size=(900, 760)))
        photo(notice, rng).save(OUT / "lab-notice.jpg", quality=82)
    (OUT / "room-bookings.html").write_text(BOOKINGS, encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:32s} {f.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
