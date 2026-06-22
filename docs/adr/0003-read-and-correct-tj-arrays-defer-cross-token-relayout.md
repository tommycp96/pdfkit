# Read and correct TJ-array text; defer cross-token re-layout

Born-digital PDFs draw text with either the `Tj` (single string) or the `TJ`
(array of strings + inter-glyph spacing numbers) show-text operator. Some
authoring engines — notably Chromium/Skia print, which produced the résumé
fixture that motivated this — emit **only** `TJ`. The reader originally walked
just `Tj`, so such a document yielded zero runs and nothing was correctable,
while an independent extractor (mutool) read it fine.

We now emit one `Run` per `TJ`, concatenating the array's string elements and
ignoring the numeric spacing adjustments (they carry no text). On write-back the
correction engine re-emits a corrected `TJ` as a single-string array. This reuses
the entire existing data spine — `find`, `find_phrase`, every verify gate, the
subset-extension path — unchanged; the only operator-aware code is the
read branch and the write-back branch.

A second, more insidious bug surfaced alongside: the same fixture's `/ToUnicode`
used the **array form** of `bfrange` (`<lo> <hi> [<v0> <v1> …]`), which the parser
mis-read, silently decoding every glyph to the wrong character. For an
honesty-focused tool, a silent wrong decode is worse than a loud failure, so the
parser now handles both `bfrange` forms.

We deliberately scope correction to the **single-token** case: the corrected text
must live within one `TJ` token. The motivating request was a word *reorder*
across three separately, absolutely-positioned (`Tm`) tokens, which would require
recomputing each word's absolute origin — a layout engine, not a text edit, and
fragile (inter-word gaps are `Tm` offsets, not space glyphs). That cross-token
re-layout, and preserving interior `TJ` kerning numbers across a length change,
are left for a future decision; the engine fails or simply doesn't match rather
than guessing a layout.
