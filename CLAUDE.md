# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`pdfkit` is a CLI for an **Issuer** to make **pre-delivery corrections** to
**born-digital** PDFs they author — fixing a wrong figure or typo before the
document is sent, while keeping the result visually faithful and producing a
**review packet** that proves the change is safe. The defining constraint is
honesty: it corrects your own not-yet-sent document, normalizes metadata
truthfully, and actively refuses to backdate or forge provenance. Read
`CONTEXT.md` for the project's controlled vocabulary (Issuer, Recipient,
Correction, etc.) and use those terms; the two load-bearing design decisions are
in `docs/adr/`.

Scope boundaries that are enforced in code, not just documented:
- Only born-digital PDFs (real embedded text). Scanned/image PDFs are out of
  scope (ADR 0001 — text-layer extraction, never OCR/vision).
- Only Identity-H / CIDFontType2 Type0 fonts are *editable*; others are shown
  but flagged non-editable.
- Metadata normalization never fabricates dates — `scrub-metadata` raises
  `ProvenanceForgery` if you try to set CreationDate/ModDate.

## Commands

```sh
# Setup (editable install into a venv)
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

# Requires these CLIs on PATH (used by the verifier, invoked via subprocess):
#   qpdf    — structural --check
#   mutool  — independent text extraction (unicode round-trip gate)

# Tests (skip automatically unless a fixture is provided — see below)
pytest -q
pytest -q tests/test_correction.py::test_empty_glyph_repair_regression   # single test

# Acceptance benchmark (VERIFIED rate across synthesized corrections)
python benchmark/run_benchmark.py
```

### Running the tool

```sh
pdfkit inspect doc.pdf --grep 1,000.00                       # list positioned runs
pdfkit correct doc.pdf --replace "1,000.00=1,200.00"         # dry-run (default)
pdfkit correct doc.pdf --replace "OLD=NEW" --occurrence 0 -o out.pdf --apply
pdfkit repair doc.pdf -o repaired.pdf                        # fill blank-outline glyphs doc-wide
pdfkit scrub-metadata out.pdf --set "Author=Acme HR"
pdfkit verify doc.pdf out.pdf --expect "OLD=NEW"             # re-run gates anytime
```

`correct --apply` and `repair` **exit non-zero unless the output is VERIFIED**
(exit 5 on gate failure). Both refuse to overwrite the input — always write to a
separate `-o` path.

## Fixtures, fonts, and why tests skip

Nothing binary is bundled — by design, not omission:
- **Sample PDFs** are real, PII-bearing documents and are git-ignored (`*.pdf`).
  Tests are gated on a fixture: set `PDFKIT_TEST_PDF=/path/to/sample.pdf` (else
  the whole suite `skipif`s). The expected text values in `tests/` are specific
  to the original fixture; adjust them for your own PDF.
- **Original font programs** are needed by the subset-extension and repair paths
  (to copy real outlines/widths/Unicode). Resolve them via `PDFKIT_FONT_DIR` (or
  drop `.ttf`/`.otf` into `fonts/` or `segoeui/`). Resolution is by base-font
  name through `_FONT_ALIASES` in `pdfkit/fonts.py`. Fonts are git-ignored; when
  the original can't be resolved the tool fails loudly (`FontUnavailable`) rather
  than guessing (ADR 0002).

## Architecture: the read → correct → verify pipeline

Three layers, each its own module, plus font/render helpers. The data spine is
`Document` → `FontModel` → `Run`.

**Read — `document.py`.** `Document` opens the PDF with pikepdf, and per page
builds a `FontModel` for each font and extracts a `Run` per `Tj` operator by
walking the content stream (`extract_runs` tracks `Tf`/`Td`/`TD`/`Tm` to recover
font, size, x, y). Key insight encoded in `FontModel`: in an Identity-H subset,
the 2-byte codes in a `Tj` string **are glyph IDs (GIDs)**, so unicode↔GID lives
only in `/ToUnicode` and widths in `/W`. `empty_gids` tracks GIDs whose embedded
TrueType glyph has zero contours — present text that **renders blank** (a real
bug found in a fixture). `find()` locates target runs; `find_phrase()` handles
per-glyph layouts (Chrome/Skia print where each char is its own `Tj`+`Td`).

**Correct — `edit.py`.** Two paths, chosen by `FontModel.missing_chars`:
- *Fast path*: every needed char already has a usable GID → just re-encode the
  `Tj` string. Right-aligned values are detected (`_infer_alignment`) and shifted
  (`_shift_preceding_td`) so the right edge stays put; tabular digits keep
  alignment exact.
- *Extend path* (`_extend_subset`): a needed char is absent **or has an empty
  outline** → copy its glyph from the original font program into the embedded
  subset and update `/W` + `/ToUnicode`. The `_SubsetMutator` does composite-aware
  outline copying with em-unit scaling, under fresh collision-free glyph names.
  This is the part ADR 0002 is about: extend the subset, never re-embed the whole
  font.

  `repair_fonts()` shares the same mutator to *fill* (not append) empty outlines
  document-wide — text/widths/positions untouched, only the blank glyph shapes
  restored. `apply_phrase_correction` / `_apply_phrase_multifont` handle the
  per-glyph and mixed-font phrase cases.

**Verify — `verify.py`.** The trust boundary. `verify_correction` runs gates and,
if `packet_dir` is set, writes a review packet (`report.md`, `report.json`,
before/after/diff PNGs). Output is VERIFIED only if **every critical gate
passes** (`VerifyReport.verified`). The gates deliberately cross-check with
*independent* tools so the engine can't grade its own homework:
- `replacement_present` / `single_change`: ordered run-list diff (content-stream
  order is stable, so a duplicated value's changed instance is pinpointed).
- `glyph_resolution`: new glyphs have GID + width + **non-empty outline**.
- `unicode_roundtrip`: new text is found by **mutool** (not pdfkit's decoder).
- `structural_valid`: **qpdf --check** (rc 0 clean, 3 warnings-only = pass).
- `structure_unchanged`: page count, MediaBoxes, and font sets invariant.
- `provenance_ok` (advisory): CreationDate not altered.
- `visual_localized`: pypdfium2 pixel diff lands inside the old word's bbox.

`--repair` verifies the two transforms **independently** (correction against a
correction-only intermediate, repair on top), so each keeps its own guarantee.

**Helpers.** `fonts.py` — `parse_*`/`build_*` for `/ToUnicode` and `/W`, plus the
`FontResolver`. `render.py` — pypdfium2 rasterization + numpy pixel diff (DPI
150). `metadata.py` — honest metadata normalization (strips tool/identity keys
and XMP, sets ModDate to now, removes macOS "Where from" xattr).

## Conventions specific to this repo

- The verifier is the product, not a test harness — when changing the edit
  engine, assume the bar is **VERIFIED on real fixtures + benchmark**, and add a
  negative control if you add a way to break an edit (see
  `test_negative_control_blank_glyph_rejected`).
- Use the `CONTEXT.md` vocabulary in code, comments, and messages (e.g.
  "correction" not "edit/patch"; "normalize metadata" not "scrub/sanitize").
- New architectural decisions go in `docs/adr/` as numbered ADRs.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
