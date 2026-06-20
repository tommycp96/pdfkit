"""Metadata normalization: produce uniform, honest metadata for outgoing files.

Removal and standardization only. Fabricating false provenance (e.g. backdating
the modification date to hide that a document was edited) is out of scope and
actively refused.
"""
from __future__ import annotations

import datetime as _dt
import subprocess
from dataclasses import dataclass

import pikepdf

# docinfo keys carrying tool/author/identity cruft we strip by default.
_STRIP_KEYS = ["/Author", "/Creator", "/Producer", "/Keywords", "/Subject",
               "/Company", "/Comments", "/SourceModified"]


class ProvenanceForgery(ValueError):
    """Raised on an attempt to backdate or fabricate provenance metadata."""


@dataclass
class ScrubResult:
    removed_keys: list[str]
    set_keys: dict[str, str]
    xmp_removed: bool


def _pdf_date(dt: _dt.datetime) -> str:
    off = dt.strftime("%z") or "+0000"
    return f"D:{dt.strftime('%Y%m%d%H%M%S')}{off[:3]}'{off[3:]}'"


def scrub_metadata(in_path: str, out_path: str,
                   set_values: dict[str, str] | None = None) -> ScrubResult:
    set_values = set_values or {}
    for k in set_values:
        if k.lstrip("/") in ("CreationDate", "ModDate"):
            raise ProvenanceForgery(
                f"refusing to set {k}: dates are normalized honestly, not forged")

    pdf = pikepdf.open(in_path, allow_overwriting_input=False)
    removed = []
    try:
        info = pdf.docinfo
        for key in list(_STRIP_KEYS):
            if key in info:
                del info[key]
                removed.append(key)
        for k, v in set_values.items():
            info[pikepdf.Name(k if k.startswith("/") else f"/{k}")] = v
        # Honest modification date = now (the file IS being modified now).
        info[pikepdf.Name("/ModDate")] = _pdf_date(_dt.datetime.now().astimezone())
        xmp_removed = False
        if "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]
            xmp_removed = True
        pdf.save(out_path)
    finally:
        pdf.close()

    # Strip macOS "Where from" provenance xattr on the output file.
    subprocess.run(["xattr", "-d", "com.apple.metadata:kMDItemWhereFroms", out_path],
                   capture_output=True)
    return ScrubResult(removed_keys=removed,
                       set_keys={k: v for k, v in set_values.items()},
                       xmp_removed=xmp_removed)
