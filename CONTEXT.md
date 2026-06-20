# pdfkit

A CLI (with an optional Claude Code skill layer) for an Issuer to make
pre-delivery corrections to born-digital PDF documents they author, fixing
human-error typos and figures while keeping the result visually faithful to the
original.

## Language

**Issuer**:
The person or organization that authors a document and sends it to a recipient.
In this project the user is the Issuer: their team produces documents (across
mixed tools) and the user is the review gate that corrects and standardizes them
before they are sent. Correcting one's own not-yet-sent document is in scope;
altering a document issued by someone else is not.
_Avoid_: editor, user, client

**Recipient**:
The party a document is sent to (the Issuer's client).
_Avoid_: customer, end user

**Pre-delivery correction**:
An edit the Issuer makes to a document they authored before it has been sent, to
fix a human error. The intent is accuracy, not disguise.
_Avoid_: alteration, modification, tampering

**Correction**:
The core operation: replacing a piece of in-place text (a wrong figure or typo)
with the right text, including when the replacement is shorter or longer.
_Avoid_: edit, patch

**Born-digital document**:
A PDF whose text is real, embedded, selectable objects (produced by software such
as word processors, reporting engines, browser print, or LaTeX), so every string
carries its exact font, size, colour, and position. The only kind of document in
scope.
_Avoid_: digital PDF, native PDF

**Scanned document**:
A PDF whose page is an image with no real text layer, requiring OCR and pixel
work to change. Out of scope.
_Avoid_: image PDF, raster PDF

**Font subset**:
The embedded fonts in a born-digital PDF contain only the glyphs actually used on
its pages. A Correction that needs a character not already present has no glyph,
width, or Unicode entry — breaking rendering, spacing, and copy/search until the
subset is extended from the original font program.
_Avoid_: embedded font, font set

**Metadata normalization**:
Producing uniform, valid document metadata before sending, regardless of which
tool generated the input (a reporting engine, a design tool, etc.) — removing tool-specific
cruft, internal author names, macOS "Where from", and file paths, and setting
consistent honest values. Removal and standardization only; fabricating false
provenance (e.g. backdating the modification date to hide that the document was
edited) is out of scope.
_Avoid_: scrub, clean, sanitize, wipe

**Source of truth**:
The upstream system that generated the document (e.g. the report/generation engine).
The most robust correction is made here, with regeneration; Pre-delivery
correction via PDF editing is the pragmatic urgent-path alternative.
_Avoid_: original, master, the source
