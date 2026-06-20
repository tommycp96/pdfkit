# pdfkit

Deterministic, **verifiable** in-place text correction for born-digital PDFs.

Built for an Issuer to fix a human-error value or typo in a document they
authored — before it is delivered — while keeping the result visually faithful
to the original. Every correction produces a **review packet** you inspect once
and trust. See `CONTEXT.md` for terminology and `docs/adr/` for the two
load-bearing design decisions.

> Scope & boundary: corrects documents you author, before delivery. It does not
> exist to alter someone else's issued document or to fabricate provenance —
> metadata is normalized honestly, never backdated.

## Install

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
```

Requires the `qpdf` and `mutool` CLIs on PATH (used by verification).

> **Sample data & fonts are not bundled.** The development fixtures are real,
> PII-bearing documents and are git-ignored, as are licensed font files (see
> [`fonts/README.md`](fonts/README.md)). Point at your own born-digital PDFs and
> original fonts to try the examples below; the test suite skips automatically
> when a fixture is absent.

## Use

```sh
# 1. See what's in the file (text, page, coords, font, size)
pdfkit inspect document.pdf --grep 1,000.00

# 2. Dry-run a correction (default). Ambiguous matches are listed for you to pick.
pdfkit correct document.pdf --replace "1,000.00=1,200.00"

# 3. Apply a specific match; writes *.fixed.pdf + a *.review/ packet, then verifies.
#    Add --repair to also fix any pre-existing blank glyphs document-wide.
pdfkit correct document.pdf --replace "1,000.00=1,200.00" \
    --occurrence 0 -o out.pdf --apply

# 4. Repair blank-rendering glyphs (valid text, missing outline) document-wide,
#    filling them from the original font. Changes no text/layout.
pdfkit repair document.pdf -o repaired.pdf

# 5. Normalize metadata for an outgoing file (honest; refuses backdating)
pdfkit scrub-metadata out.pdf --set "Author=Acme HR"

# 6. Re-verify an edited file against the original at any time
pdfkit verify document.pdf out.pdf --expect "1,000.00=1,200.00"
```

`correct --apply` exits non-zero unless the output is **VERIFIED**.

## How it works

- **Read** (`document.py`): walks the content stream, models each Type0/Identity-H
  subset font from `/ToUnicode` + `/W` + the embedded TrueType outlines.
- **Correct** (`edit.py`): re-encodes the target run. If a needed character is
  absent from the subset **or has an empty glyph outline** (the classic "renders
  blank" bug), it extends the subset from the original font program (fontTools)
  — glyph + width + ToUnicode. Tabular digits keep alignment exact; right-aligned
  values are repositioned.
- **Repair** (`edit.py:repair_fonts`): some born-digital PDFs embed glyphs with a
  valid width + ToUnicode but **no outline** — text extracts fine yet renders
  blank (e.g. blank bold digits in the sample PDF). Repair fills those
  outlines in place from the original font, document-wide, with no text/layout
  change — so every affected run renders. Honest restoration, not alteration.
- **Verify** (`verify.py`): eight gates (replacement present, single-change diff,
  glyph resolution incl. non-empty outlines, independent copy/search round-trip,
  qpdf structural check, structural invariants, provenance, and pixel-level
  visual localization). Output is VERIFIED only if every critical gate passes.

## Verification confidence

`benchmark/run_benchmark.py` synthesizes realistic corrections (numbers and
words; same-length, grow, shrink, and forced subset-extension) across the sample
fixtures and reports the VERIFIED rate. A negative control (a deliberately
blank-glyph edit) is rejected by four independent gates — see
`tests/test_correction.py::test_negative_control_blank_glyph_rejected`.

```sh
python benchmark/run_benchmark.py     # current corpus: 1333/1333 = 100% VERIFIED
pytest -q
```
