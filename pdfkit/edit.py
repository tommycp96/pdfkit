"""The correction engine: replace the text of one run, fast path or subset-extend.

Fast path  : every new char already has a GID in the run's font subset -> just
             re-encode the Tj string. Tabular digits keep alignment exact.
Extend path: a new char is absent from the subset -> copy its glyph (+ width +
             ToUnicode) from the original font program into the embedded subset,
             then re-encode. Fails loudly if the original font is unavailable.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pikepdf
from fontTools.ttLib import TTFont

from .document import Document, FontModel, Run


class FontUnavailable(RuntimeError):
    """Raised when a glyph must be added but the original font program is missing."""


@dataclass
class EditResult:
    page_index: int
    font: str
    old_text: str
    new_text: str
    extended_chars: list[str]
    old_width: float               # text-space units (per em)
    new_width: float
    align: str                     # "left" | "right"
    dx_applied: float              # horizontal shift applied to preserve alignment


class _SubsetMutator:
    """Copies glyph outlines from an original font into an embedded subset.

    Two operations share the same composite-aware copy machinery:
      - `append_glyph`  : add an outline under a fresh gid (subset extension).
      - `fill_glyph`    : overwrite an existing empty gid's outline (repair).
    Composite components are always copied under fresh, collision-free names.
    """

    def __init__(self, sub: TTFont, orig: TTFont):
        from copy import deepcopy
        self._deepcopy = deepcopy
        self.sub, self.orig = sub, orig
        self.scale = sub["head"].unitsPerEm / orig["head"].unitsPerEm
        self.sub_glyf = sub["glyf"]
        self.sub_hmtx = sub["hmtx"]
        self.orig_glyf = orig["glyf"]
        self.orig_hmtx = orig["hmtx"]
        self.order = list(sub.getGlyphOrder())
        self._name_map: dict[str, str] = {}
        self._counter = 0

    def _materialize(self, orig_name: str):
        glyph = self._deepcopy(self.orig_glyf[orig_name])
        if glyph.isComposite():
            for comp in glyph.components:
                comp.glyphName = self._append(comp.glyphName)
        elif self.scale != 1.0 and hasattr(glyph, "coordinates"):
            glyph.coordinates.scale((self.scale, self.scale))
        return glyph

    def _append(self, orig_name: str) -> str:
        if orig_name in self._name_map:
            return self._name_map[orig_name]
        glyph = self._materialize(orig_name)
        self._counter += 1
        new_name = f"pk{self._counter:04d}_{orig_name}"
        self._name_map[orig_name] = new_name
        self.sub_glyf.glyphs[new_name] = glyph
        adv, lsb = self.orig_hmtx[orig_name]
        self.sub_hmtx.metrics[new_name] = (round(adv * self.scale), round(lsb * self.scale))
        self.order.append(new_name)
        return new_name

    def append_glyph(self, orig_name: str) -> int:
        return self.order.index(self._append(orig_name))

    def fill_glyph(self, gid: int, orig_name: str) -> None:
        glyph = self._materialize(orig_name)
        target = self.order[gid]
        self.sub_glyf.glyphs[target] = glyph
        adv, lsb = self.orig_hmtx[orig_name]
        self.sub_hmtx.metrics[target] = (round(adv * self.scale), round(lsb * self.scale))

    def finalize(self) -> bytes:
        self.sub.setGlyphOrder(self.order)
        self.sub_glyf.glyphOrder = self.order
        self.sub["maxp"].numGlyphs = len(self.order)
        buf = io.BytesIO()
        self.sub.save(buf)
        return buf.getvalue()


def _resolve_original(doc: Document, model: FontModel, fd) -> tuple:
    """Return (original TTFont, its best cmap, FontFile2 stream) or raise/None."""
    if "/FontFile2" not in fd:
        raise FontUnavailable(f"{model.base_font}: no embedded TrueType")
    orig_path = doc.resolver.resolve(model.base_font)
    if orig_path is None:
        raise FontUnavailable(
            f"cannot resolve original font for {model.base_font} (searched "
            f"{[str(d) for d in doc.resolver.search_dirs]}). Add it to a "
            f"--font-dir / PDFKIT_FONT_DIR directory.")
    orig = TTFont(str(orig_path))
    return orig, orig.getBestCmap(), fd["/FontFile2"]


def _extend_subset(doc: Document, model: FontModel, chars: list[str]) -> None:
    """Append glyphs for `chars` to the embedded subset; update /W, /ToUnicode, model."""
    df = model.obj["/DescendantFonts"][0]
    fd = df["/FontDescriptor"]
    orig, orig_cmap, ff = _resolve_original(doc, model, fd)
    sub = TTFont(io.BytesIO(bytes(ff.read_bytes())))
    mut = _SubsetMutator(sub, orig)
    sub_upem = sub["head"].unitsPerEm

    new_gids: dict[str, int] = {}
    for c in chars:
        if ord(c) not in orig_cmap:
            raise FontUnavailable(f"{model.base_font}: original font lacks glyph for {c!r}")
        new_gids[c] = mut.append_glyph(orig_cmap[ord(c)])

    new_ff = mut.finalize()
    ff.write(new_ff)
    ff["/Length1"] = len(new_ff)

    # Update widths + ToUnicode (PDF objects) and the in-memory model.
    from .fonts import build_tounicode, build_w
    for c, gid in new_gids.items():
        adv = mut.orig_hmtx[orig_cmap[ord(c)]][0]
        model.widths[gid] = adv * mut.scale * 1000.0 / sub_upem
        model.gid2uni[gid] = c
        model.uni2gid[c] = gid
    df["/W"] = doc.pdf.make_indirect(pikepdf.Array(build_w(model.widths)))
    model.obj["/ToUnicode"].write(build_tounicode(model.gid2uni))


@dataclass
class RepairResult:
    filled: list[tuple[str, str]]      # (base_font, chars filled)
    unresolved: list[str]              # base_fonts with blanks but no original


def repair_fonts(doc: Document) -> RepairResult:
    """Fill empty-outline glyphs in place from the original font program.

    Document-wide and content-stream-free: only the embedded TrueType outlines
    change, so every run that uses a repaired gid renders, while text, widths,
    and positions are untouched. Skips glyphs whose original is also blank
    (e.g. space) and fonts whose original program can't be resolved.
    """
    filled: list[tuple[str, str]] = []
    unresolved: list[str] = []
    processed: set = set()
    for pi in range(len(doc.pdf.pages)):
        for model in doc.models(pi).values():
            if not model.editable:
                continue
            df = model.obj["/DescendantFonts"][0]
            fd = df["/FontDescriptor"]
            if "/FontFile2" not in fd:
                continue
            key = fd["/FontFile2"].objgen
            if key in processed:
                continue
            processed.add(key)
            try:
                orig, orig_cmap, ff = _resolve_original(doc, model, fd)
            except FontUnavailable:
                if _has_blanks(model):
                    unresolved.append(model.base_font)
                continue
            sub = TTFont(io.BytesIO(bytes(ff.read_bytes())))
            mut = _SubsetMutator(sub, orig)
            glyf = sub["glyf"]
            chars_fixed: list[str] = []
            for gid in range(len(mut.order)):
                name = mut.order[gid]
                if name not in glyf.glyphs or glyf[name].numberOfContours != 0:
                    continue
                c = model.gid2uni.get(gid)
                if not c or len(c) != 1 or c.isspace() or ord(c) not in orig_cmap:
                    continue
                oname = orig_cmap[ord(c)]
                if orig["glyf"][oname].numberOfContours == 0:
                    continue
                mut.fill_glyph(gid, oname)
                chars_fixed.append(c)
            if chars_fixed:
                new_ff = mut.finalize()
                ff.write(new_ff)
                ff["/Length1"] = len(new_ff)
                filled.append((model.base_font, "".join(sorted(set(chars_fixed)))))
    return RepairResult(filled=filled, unresolved=unresolved)


def _has_blanks(model: FontModel) -> bool:
    return any(g in model.empty_gids and not (model.gid2uni.get(g) or " ").isspace()
               for g in model.gid2uni)


def find_blanks(doc: Document) -> list[tuple[str, str]]:
    """List (base_font, char) for empty-outline glyphs that COULD be repaired
    (original font resolvable with a non-empty glyph). Used by verification."""
    out: list[tuple[str, str]] = []
    processed: set = set()
    for pi in range(len(doc.pdf.pages)):
        for model in doc.models(pi).values():
            if not model.editable or "/DescendantFonts" not in model.obj:
                continue
            fd = model.obj["/DescendantFonts"][0]["/FontDescriptor"]
            if "/FontFile2" not in fd:
                continue
            key = fd["/FontFile2"].objgen
            if key in processed:
                continue
            processed.add(key)
            orig_path = doc.resolver.resolve(model.base_font)
            if orig_path is None:
                continue
            orig = TTFont(str(orig_path))
            orig_cmap = orig.getBestCmap()
            sub = TTFont(io.BytesIO(bytes(fd["/FontFile2"].read_bytes())))
            glyf = sub["glyf"]
            order = sub.getGlyphOrder()
            for gid in range(len(order)):
                name = order[gid]
                if name not in glyf.glyphs or glyf[name].numberOfContours != 0:
                    continue
                c = model.gid2uni.get(gid)
                if not c or len(c) != 1 or c.isspace() or ord(c) not in orig_cmap:
                    continue
                if orig["glyf"][orig_cmap[ord(c)]].numberOfContours != 0:
                    out.append((model.base_font, c))
    return out


def apply_correction(doc: Document, run: Run, new_text: str,
                     align: str = "auto") -> EditResult:
    page = doc.pdf.pages[run.page_index]
    model = doc.models(run.page_index)[run.font]
    if not model.editable:
        raise RuntimeError(f"font {run.font} ({model.base_font}) is not editable")

    missing = model.missing_chars(new_text)
    extended = list(missing)
    if missing:
        _extend_subset(doc, model, missing)

    old_w = model.width_of(run.text)
    new_w = model.width_of(new_text)

    if align == "auto":
        align = _infer_alignment(doc, run)

    dx = 0.0
    if align == "right":
        dx = old_w * run.size - new_w * run.size  # shift so right edge is preserved

    instrs = pikepdf.parse_content_stream(page)
    new_raw = model.encode(new_text)
    instrs[run.instr_index] = pikepdf.ContentStreamInstruction(
        [pikepdf.String(new_raw)], pikepdf.Operator("Tj")
    )
    if dx:
        # Insert a relative Td before this Tj's preceding Td by adjusting the
        # nearest preceding Td operand on x.
        _shift_preceding_td(instrs, run.instr_index, dx)

    page.Contents = doc.pdf.make_stream(pikepdf.unparse_content_stream(instrs))

    return EditResult(
        page_index=run.page_index, font=run.font, old_text=run.text,
        new_text=new_text, extended_chars=extended,
        old_width=old_w * run.size, new_width=new_w * run.size,
        align=align, dx_applied=dx,
    )


class PhraseSpanError(RuntimeError):
    """Raised when a phrase span isn't a clean per-glyph Tj+Td chain."""


@dataclass
class PhraseResult:
    page_index: int
    old_text: str
    new_text: str
    fonts: list[str]
    extended_chars: list[str]


def apply_phrase_correction(doc: Document, span: list, new_text: str) -> PhraseResult:
    """Rewrite a per-glyph run span (Chrome/Skia layout) to spell `new_text`.

    Each glyph in the span is `Tj <glyph>` immediately followed by `Td <adv> 0`.
    We rewrite the (glyph, advance) pairs. Advances reuse each character's exact
    original value when available (pixel-faithful, no kerning drift) and fall
    back to the font's /W width otherwise. Requires a single editable font across
    the span; same-length edits preserve total width so nothing downstream moves.
    """
    pi = span[0].page_index
    page = doc.pdf.pages[pi]
    fonts = sorted({r.font for r in span})
    if len(fonts) > 1:
        # Mixed-font phrase: rebuild as one block, each char keeping its own
        # original font + advance (preserves per-token styling on a reorder).
        return _apply_phrase_multifont(doc, span, new_text)
    model = doc.models(pi)[fonts[0]]
    if not model.editable:
        raise PhraseSpanError(f"font {fonts[0]} is not editable")
    size = span[0].size

    instrs = pikepdf.parse_content_stream(page)
    slots = []  # (tj_index, td_index) per original glyph
    orig_adv: dict[str, float] = {}
    for r in span:
        ti = r.instr_index
        if ti + 1 >= len(instrs) or str(instrs[ti + 1].operator) not in ("Td", "TD"):
            raise PhraseSpanError("span is not a clean per-glyph Tj+Td chain")
        slots.append((ti, ti + 1))
        orig_adv.setdefault(r.text, float(instrs[ti + 1].operands[0]))

    extended = model.missing_chars(new_text)
    if extended:
        _extend_subset(doc, model, extended)

    def advance(c: str) -> float:
        if c in orig_adv:
            return orig_adv[c]
        gid = model.uni2gid[c]
        return model.widths.get(gid, model.default_width) / 1000.0 * size

    def tj(c: str):
        return pikepdf.ContentStreamInstruction(
            [pikepdf.String(model.encode(c))], pikepdf.Operator("Tj"))

    def td(c: str):
        return pikepdf.ContentStreamInstruction(
            [pikepdf.Object.parse(repr(advance(c)).encode()), pikepdf.Object.parse(b"0")],
            pikepdf.Operator("Td"))

    if len(new_text) == len(span):
        for k, c in enumerate(new_text):
            ti, tdi = slots[k]
            instrs[ti] = tj(c)
            instrs[tdi] = td(c)
    else:
        first, last = slots[0][0], slots[-1][1]
        rebuilt = []
        for c in new_text:
            rebuilt.append(tj(c)); rebuilt.append(td(c))
        instrs[first:last + 1] = rebuilt

    page.Contents = doc.pdf.make_stream(pikepdf.unparse_content_stream(instrs))
    return PhraseResult(pi, "".join(r.text for r in span), new_text, fonts, extended)


def _apply_phrase_multifont(doc: Document, span: list, new_text: str) -> PhraseResult:
    """Rebuild a multi-font / multi-block phrase as one continuous text block,
    giving each new character the font + advance the same character had in the
    original (so a token reorder keeps each token's weight)."""
    pi = span[0].page_index
    page = doc.pdf.pages[pi]
    size = span[0].size
    instrs = pikepdf.parse_content_stream(page)

    # Per-character original font + advance (last occurrence wins; consistent for
    # a reorder). Block-final glyphs lack a trailing Td -> width comes from /W.
    char_font: dict[str, str] = {}
    char_adv: dict[str, float] = {}
    for r in span:
        char_font[r.text] = r.font
        ti = r.instr_index
        if ti + 1 < len(instrs) and str(instrs[ti + 1].operator) in ("Td", "TD"):
            char_adv[r.text] = float(instrs[ti + 1].operands[0])

    # Resolve start block bounds, its Tm and BDC, to anchor and wrap the rebuild.
    first_tj = min(r.instr_index for r in span)
    last_tj = max(r.instr_index for r in span)
    b = first_tj
    while b >= 0 and str(instrs[b].operator) != "BT":
        b -= 1
    e = last_tj
    while e < len(instrs) and str(instrs[e].operator) != "ET":
        e += 1
    tm = next((instrs[i] for i in range(b, first_tj) if str(instrs[i].operator) == "Tm"), None)
    bdc = next((instrs[i] for i in range(b, first_tj) if str(instrs[i].operator) == "BDC"), None)
    if tm is None:
        raise PhraseSpanError("multi-font phrase block has no Tm anchor")

    extended: list[str] = []
    default_font = char_font[new_text[0]]

    def model_for(c: str):
        return doc.models(pi)[char_font.get(c, default_font)]

    def advance(c: str) -> float:
        if c in char_adv:
            return char_adv[c]
        m = model_for(c)
        return m.widths.get(m.uni2gid.get(c, -1), m.default_width) / 1000.0 * size

    # Ensure every glyph is available in its assigned font (extend if needed).
    for c in set(new_text):
        m = model_for(c)
        miss = m.missing_chars(c)
        if miss:
            _extend_subset(doc, m, miss)
            extended += miss

    op = pikepdf.Operator
    new_block = [pikepdf.ContentStreamInstruction([], op("BT"))]
    if bdc is not None:
        new_block.append(bdc)
    new_block.append(pikepdf.ContentStreamInstruction(
        [pikepdf.Name(default_font), pikepdf.Object.parse(repr(size).encode())], op("Tf")))
    new_block.append(tm)
    prev = default_font
    for c in new_text:
        f = char_font.get(c, default_font)
        if f != prev:
            new_block.append(pikepdf.ContentStreamInstruction(
                [pikepdf.Name(f), pikepdf.Object.parse(repr(size).encode())], op("Tf")))
            prev = f
        m = doc.models(pi)[f]
        new_block.append(pikepdf.ContentStreamInstruction(
            [pikepdf.String(m.encode(c))], op("Tj")))
        new_block.append(pikepdf.ContentStreamInstruction(
            [pikepdf.Object.parse(repr(advance(c)).encode()), pikepdf.Object.parse(b"0")],
            op("Td")))
    new_block.append(pikepdf.ContentStreamInstruction([], op("EMC")))
    new_block.append(pikepdf.ContentStreamInstruction([], op("ET")))

    instrs[b:e + 1] = new_block
    page.Contents = doc.pdf.make_stream(pikepdf.unparse_content_stream(instrs))
    return PhraseResult(pi, "".join(r.text for r in span), new_text,
                        sorted(set(char_font.values())), extended)


def _shift_preceding_td(instrs, tj_index: int, dx: float) -> None:
    for i in range(tj_index, -1, -1):
        if str(instrs[i].operator) in ("Td", "TD"):
            ops = list(instrs[i].operands)
            ops[0] = pikepdf.Object.parse(str(float(ops[0]) + dx).encode())
            instrs[i] = pikepdf.ContentStreamInstruction(ops, instrs[i].operator)
            return


def _infer_alignment(doc: Document, run: Run) -> str:
    """Right-aligned if another run on the page shares this run's right edge."""
    model = doc.models(run.page_index)[run.font]
    right = run.x + model.width_of(run.text) * run.size
    for r in doc.runs:
        if r is run or r.page_index != run.page_index:
            continue
        m2 = doc.models(r.page_index).get(r.font)
        if not m2:
            continue
        r_right = r.x + m2.width_of(r.text) * r.size
        if abs(r_right - right) < 1.0 and abs(r.x - run.x) > 1.0:
            return "right"
    return "left"
