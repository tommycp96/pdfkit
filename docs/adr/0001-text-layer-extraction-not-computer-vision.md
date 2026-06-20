# Use text-layer extraction, not computer vision, to read documents

All documents in scope are born-digital, so their text, fonts, and coordinates
can be read deterministically from the PDF itself (pdfplumber / pikepdf). We
therefore locate and target text via the text layer rather than rendering pages
and running OCR/vision. This is simpler and far more precise than a vision
pipeline; the trade-off is that scanned/image-only PDFs are explicitly
unsupported. If image PDFs ever come into scope, an OCR fallback would be added
as a separate path rather than replacing the text-layer core.
