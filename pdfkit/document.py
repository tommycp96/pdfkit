"""Read layer: open a PDF, model its Type0 fonts, extract positioned text runs.

Only Identity-H / CIDFontType2 Type0 fonts (the born-digital, subsetted kind
produced by report engines and design tools) are modelled for editing. Other
font types are still extracted for display but flagged non-editable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pikepdf

from .fonts import FontResolver, parse_tounicode, parse_w


@dataclass
class FontModel:
    name: str                      # resource name, e.g. "/FNT1"
    base_font: str                 # e.g. "DEVEXP+SegoeUI,Bold"
    obj: pikepdf.Object            # the /Type0 font dict
    editable: bool
    gid2uni: dict[int, str] = field(default_factory=dict)
    uni2gid: dict[str, int] = field(default_factory=dict)
    widths: dict[int, float] = field(default_factory=dict)
    empty_gids: set[int] = field(default_factory=set)  # gids with no glyph outline
    default_width: float = 1000.0

    def decode(self, raw: bytes) -> str:
        out = []
        for i in range(0, len(raw) - 1, 2):
            gid = (raw[i] << 8) | raw[i + 1]
            out.append(self.gid2uni.get(gid, "�"))
        return "".join(out)

    def needs_glyph(self, c: str) -> bool:
        """A char needs a subset fix if absent, or present but with an empty
        outline (a width+ToUnicode entry that renders as nothing)."""
        gid = self.uni2gid.get(c)
        if gid is None:
            return True
        if c.isspace():
            return False
        return gid in self.empty_gids

    def missing_chars(self, text: str) -> list[str]:
        # Deduplicate while preserving order.
        seen, out = set(), []
        for c in text:
            if c not in seen and self.needs_glyph(c):
                seen.add(c); out.append(c)
        return out

    def encode(self, text: str) -> bytes:
        """Encode text to 2-byte GID string. Caller must ensure no missing chars."""
        out = bytearray()
        for c in text:
            gid = self.uni2gid[c]
            out += bytes([(gid >> 8) & 0xFF, gid & 0xFF])
        return bytes(out)

    def width_of(self, text: str) -> float:
        """Advance width of text in text-space units per 1 em (sum of /1000 * size)."""
        total = 0.0
        for c in text:
            gid = self.uni2gid.get(c)
            total += self.widths.get(gid, self.default_width) if gid is not None else self.default_width
        return total / 1000.0


@dataclass
class Run:
    page_index: int
    instr_index: int               # index into the parsed content stream
    text: str
    font: str                      # resource name
    size: float
    x: float
    y: float
    raw: bytes                     # original Tj operand bytes


def build_font_models(page: pikepdf.Page) -> dict[str, FontModel]:
    models: dict[str, FontModel] = {}
    res = page.obj.get("/Resources", {})
    fonts = res.get("/Font", {}) if res else {}
    for name, fobj in (fonts.items() if fonts else []):
        name = str(name)
        subtype = str(fobj.get("/Subtype", ""))
        base = str(fobj.get("/BaseFont", "")).lstrip("/")
        editable = False
        gid2uni: dict[int, str] = {}
        widths: dict[int, float] = {}
        dw = 1000.0
        if subtype == "/Type0" and "/ToUnicode" in fobj and "/DescendantFonts" in fobj:
            enc = str(fobj.get("/Encoding", ""))
            df = fobj["/DescendantFonts"][0]
            if enc == "/Identity-H" and str(df.get("/Subtype")) == "/CIDFontType2":
                gid2uni = parse_tounicode(bytes(fobj["/ToUnicode"].read_bytes()))
                if "/W" in df:
                    widths = parse_w(df["/W"])
                dw = float(df.get("/DW", 1000))
                editable = True
        uni2gid = {v: k for k, v in gid2uni.items() if len(v) == 1}
        empty_gids = _empty_outline_gids(fobj, uni2gid.values()) if editable else set()
        models[name] = FontModel(
            name=name, base_font=base, obj=fobj, editable=editable,
            gid2uni=gid2uni, uni2gid=uni2gid, widths=widths,
            empty_gids=empty_gids, default_width=dw,
        )
    return models


def _empty_outline_gids(fobj: pikepdf.Object, gids) -> set[int]:
    """GIDs whose embedded TrueType glyph has no contours (renders blank)."""
    import io
    from fontTools.ttLib import TTFont
    try:
        df = fobj["/DescendantFonts"][0]
        ff = df["/FontDescriptor"]["/FontFile2"]
    except (KeyError, IndexError):
        return set()
    tt = TTFont(io.BytesIO(bytes(ff.read_bytes())))
    if "glyf" not in tt:
        return set()
    glyf = tt["glyf"]
    order = tt.getGlyphOrder()
    empty = set()
    for gid in gids:
        if 0 <= gid < len(order):
            name = order[gid]
            if name in glyf.glyphs and glyf[name].numberOfContours == 0:
                empty.add(gid)
    return empty


def extract_runs(page: pikepdf.Page, page_index: int,
                 models: dict[str, FontModel]) -> list[Run]:
    """Walk the content stream, tracking font + position, emitting one Run per
    show-text operator (Tj, or TJ array). A TJ run concatenates the array's
    string elements; the interleaved numbers are inter-glyph spacing only."""
    runs: list[Run] = []
    instrs = pikepdf.parse_content_stream(page)
    cur_font = None
    cur_size = 0.0
    x = y = 0.0
    for idx, instr in enumerate(instrs):
        op = str(instr.operator)
        ops = instr.operands
        if op == "BT":
            x = y = 0.0
        elif op == "Tf":
            cur_font = str(ops[0])
            cur_size = float(ops[1])
        elif op in ("Td", "TD"):
            x += float(ops[0])
            y += float(ops[1])
        elif op == "Tm":
            x = float(ops[4])
            y = float(ops[5])
        elif op in ("Tj", "TJ"):
            model = models.get(cur_font)
            if op == "Tj":
                raw = bytes(ops[0])
            else:
                # TJ array mixes string operands (pikepdf.Object) with numeric
                # spacing adjustments (native int / decimal.Decimal); keep only
                # the strings.
                raw = b"".join(bytes(el) for el in ops[0]
                               if isinstance(el, pikepdf.Object))
            text = model.decode(raw) if model else ""
            runs.append(Run(page_index, idx, text, cur_font or "", cur_size, x, y, raw))
    return runs


@dataclass
class Match:
    run: Run

    @property
    def context(self) -> str:
        return self.run.text


class Document:
    def __init__(self, path: str):
        self.path = path
        self.pdf = pikepdf.open(path)
        self.resolver = FontResolver.default()
        self._page_models: list[dict[str, FontModel]] = []
        self.runs: list[Run] = []
        for i, page in enumerate(self.pdf.pages):
            models = build_font_models(page)
            self._page_models.append(models)
            self.runs.extend(extract_runs(page, i, models))

    def models(self, page_index: int) -> dict[str, FontModel]:
        return self._page_models[page_index]

    def find(self, target: str, page: int | None = None,
             near: str | None = None) -> list[Run]:
        hits = [r for r in self.runs if target in r.text]
        if page is not None:
            hits = [r for r in hits if r.page_index == page]
        if near is not None:
            hits = [r for r in hits if self._has_label(r, near)]
        return hits

    def find_phrase(self, phrase: str, page: int | None = None) -> list[list[Run]]:
        """Find consecutive run spans spelling `phrase` (per-glyph PDFs, e.g.
        Chrome/Skia print). Returns one run-list per occurrence.

        Runs are not always one char each (some pages mix multi-char runs), so
        we map character offsets to run boundaries and only return spans that
        align exactly to run edges — a match that starts or ends mid-run isn't a
        clean per-glyph span and is skipped."""
        spans: list[list[Run]] = []
        for pi in range(len(self.pdf.pages)):
            if page is not None and pi != page:
                continue
            runs = [r for r in self.runs if r.page_index == pi]
            bounds, pos = [], 0
            for idx, r in enumerate(runs):
                bounds.append((pos, pos + len(r.text), idx))
                pos += len(r.text)
            text = "".join(r.text for r in runs)
            start = 0
            while True:
                i = text.find(phrase, start)
                if i < 0:
                    break
                j = i + len(phrase)
                covered = [idx for (s, e, idx) in bounds if s >= i and e <= j]
                if covered and bounds[covered[0]][0] == i and bounds[covered[-1]][1] == j:
                    spans.append([runs[k] for k in covered])
                    start = j        # non-overlapping: a self-overlapping phrase
                                     # (e.g. "00" in "000") shouldn't double-count
                else:
                    start = i + 1    # not run-aligned; keep scanning for one that is
        return spans

    def _has_label(self, run: Run, label: str) -> bool:
        """True if `label` text appears on the same page to the left/above run."""
        for r in self.runs:
            if r.page_index != run.page_index or r is run:
                continue
            if label.lower() in r.text.lower():
                same_row = abs(r.y - run.y) <= run.size * 1.5
                above = 0 < (r.y - run.y) <= run.size * 3
                if (same_row and r.x < run.x) or above:
                    return True
        return False

    def close(self):
        self.pdf.close()
