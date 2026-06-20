# Extend the embedded font subset on demand, not re-embed the full font

A correction can introduce a character whose glyph is absent from the page's
embedded font subset, which breaks rendering, spacing, and copy/search. When
every needed character is already in the subset we do the cheap in-place edit;
when it is not, we extend the existing subset (glyph outline + `/W` width +
`/ToUnicode`) from the original font program using fontTools.

We deliberately do **not** simply swap in the complete font. Re-embedding the
full font always "works" but bloats the file and visibly changes the document's
font structure from the original — at odds with keeping a corrected document
faithful to its untouched form. Extending the subset is more work to implement
(it is the part that previously required hand-editing qpdf JSON) but is the only
option that preserves both correct rendering and structural fidelity. It depends
on having access to the original font program; when that is unavailable the tool
fails loudly rather than guessing.
