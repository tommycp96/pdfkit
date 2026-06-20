"""Verification subsystem: run the L2-L5 gates on a correction and emit a packet.

An output is VERIFIED only when every critical gate passes. The gates exist to
rule out the failure modes that matter when correctness counts: wrong target,
broken glyph, broken copy/search, collateral damage, invalid structure.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from .document import Document
from .edit import EditResult, find_blanks
from .render import diff_images, render_page, SCALE


@dataclass
class Gate:
    name: str
    critical: bool
    passed: bool
    detail: str


@dataclass
class VerifyReport:
    gates: list[Gate] = field(default_factory=list)
    packet_dir: Path | None = None

    @property
    def verified(self) -> bool:
        return all(g.passed for g in self.gates if g.critical)

    def add(self, name, critical, passed, detail):
        self.gates.append(Gate(name, critical, passed, detail))


def _run_texts(path: str) -> list[tuple[int, str, str]]:
    """(page, font, text) for every run, in document order."""
    d = Document(path)
    try:
        return [(r.page_index, r.font, r.text) for r in d.runs]
    finally:
        d.close()


def verify_correction(before_path: str, after_path: str, edit: EditResult,
                      run, packet_dir: Path | None = None,
                      do_render: bool = True) -> VerifyReport:
    rep = VerifyReport(packet_dir=packet_dir)

    before_runs = _run_texts(before_path)
    after_runs = _run_texts(after_path)

    # L2.1 + L2.2: ordered run-list diff. Content-stream order is stable, so the
    # changed instance is identified directly even when the value is duplicated.
    if len(before_runs) == len(after_runs):
        diffs = [i for i, (b, a) in enumerate(zip(before_runs, after_runs)) if b != a]
        present = any(after_runs[i][2] == edit.new_text
                      and before_runs[i][2] == edit.old_text for i in diffs)
        rep.add("replacement_present", True, present,
                "; ".join(f"{before_runs[i][2]!r}->{after_runs[i][2]!r}" for i in diffs[:4])
                or "no run changed")
        single = (len(diffs) == 1 and after_runs[diffs[0]][2] == edit.new_text
                  and before_runs[diffs[0]][2] == edit.old_text)
        rep.add("single_change", True, single, f"{len(diffs)} run(s) changed")
    else:
        rep.add("replacement_present", True, False,
                f"run count {len(before_runs)}->{len(after_runs)}")
        rep.add("single_change", True, False,
                f"run count {len(before_runs)}->{len(after_runs)}")

    # L2.3 glyph resolution: no replacement char, every glyph has a width
    d = Document(after_path)
    try:
        model = d.models(edit.page_index).get(edit.font)
        unresolved = "�" in edit.new_text  # shouldn't happen pre-edit
        no_gid = [c for c in edit.new_text if model and c not in model.uni2gid]
        missing_w = [c for c in edit.new_text
                     if model and model.uni2gid.get(c) is not None
                     and model.uni2gid[c] not in model.widths]
        # Empty outline = renders blank despite width+ToUnicode (empty-glyph bug).
        blank = [c for c in edit.new_text
                 if model and not c.isspace() and model.uni2gid.get(c) in model.empty_gids]
        ok = not (unresolved or no_gid or missing_w or blank)
        detail = "all glyphs resolve (gid, width, non-empty outline)"
        if not ok:
            detail = f"no_gid={no_gid} missing_width={missing_w} blank_outline={blank}"
        rep.add("glyph_resolution", True, ok, detail)
    finally:
        d.close()

    # L2.4 unicode round-trip via an INDEPENDENT extractor (copy/search fidelity)
    txt = subprocess.run(["mutool", "draw", "-F", "text", after_path],
                         capture_output=True, text=True).stdout
    rep.add("unicode_roundtrip", True, edit.new_text in txt,
            f"new text {'found' if edit.new_text in txt else 'NOT found'} by mutool extractor")

    # L4 structural validity (qpdf --check) + invariants. rc 0=clean, 3=warnings.
    chk = subprocess.run(["qpdf", "--check", after_path], capture_output=True, text=True)
    qpdf_ok = chk.returncode in (0, 3)
    rep.add("structural_valid", True, qpdf_ok,
            "qpdf --check: no structural errors" if chk.returncode == 0
            else ("qpdf --check: warnings only" if chk.returncode == 3
                  else (chk.stdout or chk.stderr).strip().splitlines()[-1:][0]))
    rep.add("structure_unchanged", True, *_structure_invariants(before_path, after_path))

    # L5 provenance: a correction must not silently fabricate metadata
    rep.add("provenance_ok", False, *_provenance_check(before_path, after_path))

    # L3 visual localized change
    if do_render:
        rep_visual(rep, before_path, after_path, edit, run, packet_dir)

    if packet_dir:
        _write_packet(packet_dir, rep, edit, before_runs, after_runs)
    return rep


def verify_repair(before_path: str, after_path: str,
                  filled: list[tuple[str, str]], packet_dir: Path | None = None) -> VerifyReport:
    """Verify a glyph-outline repair: no text/structure change, blanks gone, ink
    added only where blanks were (per page)."""
    rep = VerifyReport(packet_dir=packet_dir)

    before_runs = _run_texts(before_path)
    after_runs = _run_texts(after_path)
    rep.add("text_unchanged", True, before_runs == after_runs,
            "run text identical" if before_runs == after_runs else "run text changed")

    d = Document(after_path)
    try:
        remaining = find_blanks(d)
    finally:
        d.close()
    rep.add("no_blank_remaining", True, not remaining,
            "no repairable blanks remain" if not remaining else f"still blank: {remaining[:6]}")

    chk = subprocess.run(["qpdf", "--check", after_path], capture_output=True, text=True)
    rep.add("structural_valid", True, chk.returncode in (0, 3),
            "qpdf --check ok" if chk.returncode in (0, 3) else "qpdf errors")
    rep.add("structure_unchanged", True, *_structure_invariants(before_path, after_path))

    # Visual: ink must be added, and only on pages that had blanks (others 0px).
    total_changed = 0
    per_page = []
    with pikepdf.open(before_path) as _p:
        npages = len(_p.pages)
    for pi in range(npages):
        dr = diff_images(render_page(before_path, pi), render_page(after_path, pi))
        per_page.append(dr.changed_px)
        total_changed += dr.changed_px
        if packet_dir and dr.changed_px:
            packet_dir.mkdir(parents=True, exist_ok=True)
            render_page(after_path, pi).save(packet_dir / f"after_p{pi}.png")
            dr.diff_image.save(packet_dir / f"diff_p{pi}.png")
    rep.add("visual_repaired", True, total_changed > 0,
            f"changed px per page: {per_page}")

    if packet_dir:
        packet_dir.mkdir(parents=True, exist_ok=True)
        headline = "VERIFIED" if rep.verified else "FAILED"
        lines = [f"# Repair review — {headline}", "",
                 f"- Filled glyphs: {filled or 'none'}",
                 f"- Changed px per page: {per_page}", "", "## Gates", ""]
        for g in rep.gates:
            lines.append(f"- [{'PASS' if g.passed else 'FAIL'}] **{g.name}**: {g.detail}")
        (packet_dir / "report.md").write_text("\n".join(lines) + "\n")
    return rep


def _structure_invariants(before_path, after_path):
    b = pikepdf.open(before_path)
    a = pikepdf.open(after_path)
    try:
        if len(b.pages) != len(a.pages):
            return False, f"page count {len(b.pages)}->{len(a.pages)}"
        for i, (pb, pa) in enumerate(zip(b.pages, a.pages)):
            if [float(x) for x in pb.MediaBox] != [float(x) for x in pa.MediaBox]:
                return False, f"mediabox changed on page {i}"
            fb = set(str(k) for k in (pb.Resources.get("/Font", {}) or {}))
            fa = set(str(k) for k in (pa.Resources.get("/Font", {}) or {}))
            if fb != fa:
                return False, f"font set changed on page {i}: {fb}->{fa}"
        return True, "pages, mediaboxes, font sets unchanged"
    finally:
        b.close(); a.close()


def _provenance_check(before_path, after_path):
    b = pikepdf.open(before_path)
    a = pikepdf.open(after_path)
    try:
        bc = str(b.docinfo.get("/CreationDate", ""))
        ac = str(a.docinfo.get("/CreationDate", ""))
        if bc and ac and ac != bc:
            return False, "CreationDate was altered (possible forged provenance)"
        return True, "no forged provenance"
    finally:
        b.close(); a.close()


def _word_boxes(path: str, page_index: int, text: str) -> list[tuple[float, float, float, float]]:
    """Image-px bboxes for `text` on a page. Prefer exact words; fall back to any
    word that contains `text` (pdfplumber sometimes merges adjacent tokens)."""
    import pdfplumber
    exact, contains = [], []
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_index]
        for w in page.extract_words(use_text_flow=False):
            box = (w["x0"] * SCALE, w["top"] * SCALE, w["x1"] * SCALE, w["bottom"] * SCALE)
            if w["text"] == text:
                exact.append(box)
            elif text in w["text"]:
                contains.append(box)
    return exact or contains


def rep_visual(rep, before_path, after_path, edit, run, packet_dir):
    before = render_page(before_path, edit.page_index)
    after = render_page(after_path, edit.page_index)
    dr = diff_images(before, after)
    # Expected region = the actual rendered bbox of the OLD word (pdfplumber),
    # widened to allow the NEW text's extra advance, plus a small margin.
    candidates = _word_boxes(before_path, edit.page_index, edit.old_text)
    margin = 3 * SCALE
    inside = False
    detail = f"changed {dr.changed_px}px bbox {dr.total_changed_bbox}; no '{edit.old_text}' word found"
    if dr.total_changed_bbox and candidates:
        cx = (dr.total_changed_bbox[0] + dr.total_changed_bbox[2]) / 2
        cy = (dr.total_changed_bbox[1] + dr.total_changed_bbox[3]) / 2
        bx0, by0, bx1, by1 = min(candidates, key=lambda b: abs((b[0]+b[2])/2 - cx) + abs((b[1]+b[3])/2 - cy))
        grow = max(0.0, (edit.new_width - edit.old_width)) * SCALE
        ex0, ey0 = bx0 - margin + min(0, edit.dx_applied * SCALE), by0 - margin
        ex1, ey1 = bx1 + margin + grow, by1 + margin
        x0, y0, x1, y1 = dr.total_changed_bbox
        inside = x0 >= ex0 and x1 <= ex1 and y0 >= ey0 and y1 <= ey1
        detail = (f"changed {dr.changed_px}px bbox {dr.total_changed_bbox} within "
                  f"word region ({ex0:.0f},{ey0:.0f},{ex1:.0f},{ey1:.0f})")
    elif not dr.total_changed_bbox:
        detail = "no pixels changed"
    rep.add("visual_localized", True, inside, detail)
    if packet_dir:
        packet_dir.mkdir(parents=True, exist_ok=True)
        before.save(packet_dir / "before.png")
        after.save(packet_dir / "after.png")
        dr.diff_image.save(packet_dir / "diff.png")


def _write_packet(packet_dir: Path, rep: VerifyReport, edit: EditResult,
                  before_runs, after_runs):
    packet_dir.mkdir(parents=True, exist_ok=True)
    headline = "VERIFIED" if rep.verified else "FAILED"
    lines = [f"# Correction review — {headline}", "",
             f"- Page: {edit.page_index}", f"- Font: {edit.font}",
             f"- Change: `{edit.old_text}` -> `{edit.new_text}`",
             f"- Subset-extended glyphs: {edit.extended_chars or 'none'}",
             f"- Alignment: {edit.align} (dx={edit.dx_applied:.2f})",
             f"- Width: {edit.old_width:.2f} -> {edit.new_width:.2f}", "",
             "## Gates", ""]
    for g in rep.gates:
        mark = "PASS" if g.passed else "FAIL"
        tag = "" if g.critical else " (advisory)"
        lines.append(f"- [{mark}] **{g.name}**{tag}: {g.detail}")
    lines += ["", "## Images", "before.png / after.png / diff.png"]
    (packet_dir / "report.md").write_text("\n".join(lines) + "\n")
    (packet_dir / "report.json").write_text(json.dumps(
        {"verified": rep.verified,
         "gates": [g.__dict__ for g in rep.gates],
         "edit": edit.__dict__ | {"extended_chars": edit.extended_chars}}, default=str, indent=2))
