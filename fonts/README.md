# Original font programs (user-supplied)

The subset-extension and repair features need the **original** (non-subset) font
program for any font they touch — to copy real glyph outlines, widths, and
Unicode mappings into the embedded subset.

Place your original `.ttf` / `.otf` files here, or point the tool at another
directory:

```sh
export PDFKIT_FONT_DIR=/path/to/your/fonts
# or per-run: pdfkit ... --font-dir /path/to/your/fonts   (where supported)
```

Fonts are resolved by base-font name (see `pdfkit/fonts.py`). For example, a PDF
embedding `SegoeUI,Bold` resolves to `segoeuib.ttf` in a search directory.

**Font files are intentionally git-ignored.** Do not commit licensed fonts (e.g.
Microsoft's Segoe UI) — ship/keep them locally and supply your own copies.
