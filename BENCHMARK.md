# Acceptance benchmark

Goal: before trusting the tool, measure the fraction of realistic corrections
that pass **all** critical verification gates (VERIFIED), and prove the verifier
actually rejects broken edits.

## Method

For each fixture PDF, every editable, value- or word-looking run is taken and
several plausible corrections are synthesized:

| Kind | What it stresses |
|------|------------------|
| `same_len` | digit swap, same length — fast path, tabular alignment |
| `grow` / `shrink` | length change — right-edge alignment handling |
| `force_ext` | introduces `1`/`7` (absent from bold subsets) — extension path |
| `word_same` / `word_swap` | letter change/transpose — proportional glyphs |
| `word_grow` / `word_shrink` | word length change — alignment with proportional glyphs |

Each scenario is applied to a fresh copy and run through the full verifier
(`verify_correction`). The headline metric is `VERIFIED / total`.

## Result

```
fixtures: five single-page born-digital PDFs (not bundled)
scenarios: 1333   VERIFIED: 1333   rate: 100.0%
  force_ext   74/74   100%
  grow        74/74   100%
  same_len    74/74   100%
  shrink      74/74   100%
  word_grow  303/303  100%
  word_same  228/228  100%
  word_shrink 228/228 100%
  word_swap  278/278  100%
```

Target was 90–95%; the engine reaches 100% on this corpus. Reproduce with
`python benchmark/run_benchmark.py`.

## Why 100% is trustworthy, not trivial

- **Negative control.** A deliberately broken edit (needed chars mapped to blank
  glyphs, no subset extension) is **rejected** — caught independently by
  `replacement_present`, `single_change`, `glyph_resolution`, and an external
  `unicode_roundtrip` (mutool). See the test of the same name.
- **The verifier surfaced a real defect.** During development it caught that a
  sample PDF had bold digits `3`/`9` embedded with empty outlines (they render
  blank). The engine was changed to repair empty-outline glyphs, not just add
  missing ones — so editing a value now *fixes* pre-existing breakage.
- **Independent cross-checks.** Text fidelity is confirmed by mutool (not the
  tool's own decoder); structure by qpdf; rendering by pypdfium2 pixel diff.

## Known limitations (honest)

- `--near LABEL` disambiguation needs label-geometry tuning; `--occurrence` and
  `--page` are reliable today.
- Corpus is single-page documents from two PDF generators. Multi-page documents
  and other generators are untested and should be added before relying on the
  rate for them.
- The visual gate proves the change is *localized*; it does not OCR the result,
  so it relies on `glyph_resolution` (outline non-empty) to catch blank glyphs.
