"""Rendering + pixel-diff helpers (pypdfium2), used by visual verification."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

DPI = 150
SCALE = DPI / 72.0


def render_page(path: str, page_index: int, scale: float = SCALE) -> Image.Image:
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        return bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()


@dataclass
class DiffResult:
    changed_px: int
    total_changed_bbox: tuple[int, int, int, int] | None  # x0,y0,x1,y1 of changed area
    diff_image: Image.Image


def diff_images(before: Image.Image, after: Image.Image,
                threshold: int = 16) -> DiffResult:
    a = np.asarray(before, dtype=np.int16)
    b = np.asarray(after, dtype=np.int16)
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a, b = a[:h, :w], b[:h, :w]
    delta = np.abs(a - b).max(axis=2)
    mask = delta > threshold
    changed = int(mask.sum())
    bbox = None
    if changed:
        ys, xs = np.where(mask)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    heat = np.zeros((*mask.shape, 3), dtype=np.uint8)
    heat[..., 0] = (mask * 255).astype(np.uint8)  # red where changed
    base = (np.asarray(after.convert("L"))[:mask.shape[0], :mask.shape[1]] // 2).astype(np.uint8)
    heat[..., 1] = np.where(mask, 0, base)
    heat[..., 2] = np.where(mask, 0, base)
    return DiffResult(changed, bbox, Image.fromarray(heat))


def pdf_to_text_rect_box(x: float, y: float, w: float, h: float,
                         page_height: float, scale: float = SCALE) -> tuple[int, int, int, int]:
    """Convert a PDF-space rect (origin bottom-left) to image px (origin top-left)."""
    x0 = int(x * scale)
    x1 = int((x + w) * scale)
    y1 = int((page_height - y) * scale)
    y0 = int((page_height - (y + h)) * scale)
    return (x0, y0, x1, y1)
