"""Font-level helpers: parse/build /W and /ToUnicode, resolve original font programs.

A born-digital PDF's Type0 fonts use Identity-H + CIDFontType2 with
CIDToGIDMap=Identity, so the 2-byte codes in a Tj string ARE glyph ids (GIDs).
The subset font program usually has no cmap, so the only unicode<->GID mapping
lives in the PDF's /ToUnicode, and the authoritative per-glyph widths in /W.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

# ---------------------------------------------------------------------------
# /ToUnicode  (GID -> unicode string)
# ---------------------------------------------------------------------------

_BFCHAR = re.compile(r"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(r"beginbfrange(.*?)endbfrange", re.S)
_PAIR = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_TRIPLE = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")


def parse_tounicode(stream_bytes: bytes) -> dict[int, str]:
    text = stream_bytes.decode("latin-1")
    mapping: dict[int, str] = {}
    for block in _BFCHAR.findall(text):
        for src, dst in _PAIR.findall(block):
            mapping[int(src, 16)] = bytes.fromhex(_pad(dst)).decode("utf-16-be")
    for block in _BFRANGE.findall(text):
        for lo, hi, dst in _TRIPLE.findall(block):
            base = int(dst, 16)
            for i, gid in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                mapping[gid] = chr(base + i)
    return mapping


def _pad(hexstr: str) -> str:
    return hexstr if len(hexstr) % 2 == 0 else "0" + hexstr


def build_tounicode(gid2uni: dict[int, str]) -> bytes:
    """Render a minimal but valid ToUnicode CMap from a GID->unicode map."""
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    items = sorted(gid2uni.items())
    for chunk_start in range(0, len(items), 100):
        chunk = items[chunk_start:chunk_start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for gid, uni in chunk:
            dst = uni.encode("utf-16-be").hex().upper()
            lines.append(f"<{gid:04X}> <{dst}>")
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return ("\n".join(lines) + "\n").encode("latin-1")


# ---------------------------------------------------------------------------
# /W  (GID -> width in glyph-space/1000 units)
# ---------------------------------------------------------------------------

def parse_w(w_array: pikepdf.Array) -> dict[int, float]:
    widths: dict[int, float] = {}
    items = list(w_array)
    i = 0
    while i < len(items):
        c = int(items[i])
        nxt = items[i + 1] if i + 1 < len(items) else None
        if isinstance(nxt, pikepdf.Array):
            for j, w in enumerate(nxt):
                widths[c + j] = float(w)
            i += 2
        else:
            c_last = int(items[i + 1])
            w = float(items[i + 2])
            for gid in range(c, c_last + 1):
                widths[gid] = w
            i += 3
    return widths


def build_w(widths: dict[int, float]) -> list:
    """Build a compact /W array (groups runs of consecutive GIDs)."""
    out: list = []
    for gid in sorted(widths):
        if out and isinstance(out[-1], list) and out[-2] == gid - len(out[-1]):
            out[-1].append(widths[gid])
        else:
            out.append(gid)
            out.append([widths[gid]])
    return out


# ---------------------------------------------------------------------------
# Original font-program resolver (for the subset-extension path)
# ---------------------------------------------------------------------------

# Maps a normalized PostScript base-font name to candidate local filenames.
_FONT_ALIASES: dict[str, list[str]] = {
    "segoeui": ["segoeui.ttf"],
    "segoeui,bold": ["segoeuib.ttf", "seguisb.ttf"],
    "segoeui,italic": ["segoeuii.ttf"],
    "segoeui,bolditalic": ["segoeuiz.ttf"],
}


@dataclass
class FontResolver:
    """Locates an original (non-subset) font program by base-font name."""

    search_dirs: list[Path] = field(default_factory=list)

    @classmethod
    def default(cls) -> "FontResolver":
        dirs = []
        env = os.environ.get("PDFKIT_FONT_DIR")
        if env:
            dirs += [Path(p) for p in env.split(os.pathsep)]
        # Bundled / project-local font dirs commonly seen in this workspace.
        for d in ("fonts", "segoeui"):
            p = Path.cwd() / d
            if p.is_dir():
                dirs.append(p)
        return cls(search_dirs=dirs)

    def resolve(self, base_font: str) -> Path | None:
        """base_font like 'DEVEXP+SegoeUI,Bold' -> Path to a full TTF, or None."""
        name = base_font.split("+", 1)[-1].strip().lower()
        candidates = _FONT_ALIASES.get(name, [])
        # Always also try '<family>.ttf' style fallbacks.
        family = name.split(",", 1)[0]
        candidates = candidates + [f"{family}.ttf", f"{name.replace(',', '')}.ttf"]
        for d in self.search_dirs:
            for cand in candidates:
                p = d / cand
                if p.is_file():
                    return p
        return None
