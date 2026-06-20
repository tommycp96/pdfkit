"""End-to-end tests for the correction engine + verifier, on the real fixtures."""
import sys
from pathlib import Path

import pikepdf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pdfkit.document import Document
from pdfkit.edit import (EditResult, FontUnavailable, apply_correction,
                         find_blanks, repair_fonts)
from pdfkit.metadata import ProvenanceForgery, scrub_metadata
from pdfkit.verify import verify_correction, verify_repair

import os

# Sample fixtures are intentionally NOT bundled (they are real, PII-bearing
# documents). Supply your own born-digital PDF to run these tests locally, e.g.
#   export PDFKIT_TEST_PDF=/path/to/sample.pdf
# The expected text values below are specific to that fixture; adjust to match.
SAMPLE = os.environ.get("PDFKIT_TEST_PDF", str(ROOT / "sample.pdf"))
pytestmark = pytest.mark.skipif(
    not os.path.exists(SAMPLE),
    reason="sample fixture not bundled (privacy); set PDFKIT_TEST_PDF to run")


def _apply_and_verify(src, old, new, tmp_path, occurrence=0, align="auto"):
    d = Document(src)
    run = d.find(old)[occurrence]
    res = apply_correction(d, run, new, align=align)
    out = str(tmp_path / "out.pdf")
    d.pdf.save(out); d.close()
    rep = verify_correction(src, out, res, run, packet_dir=None)
    return res, rep, out


def test_fast_path_same_length(tmp_path):
    # FNT0 has all digits; same-length numeric swap is the fast path.
    res, rep, _ = _apply_and_verify(SAMPLE, "8,948.80", "9,750.50", tmp_path)
    assert res.extended_chars == []
    assert rep.verified


def test_empty_glyph_repair_regression(tmp_path):
    """Empty-glyph bug: the bold subset embeds '3'/'9' outlines and no '1'/'7'.
    Editing must repair/add them so the value renders (and verifies)."""
    d = Document(SAMPLE)
    model = d.models(0)["/FNT1"]
    # '3' present-but-empty, '1' and '7' absent — all must be flagged.
    assert set(model.missing_chars("31,750.00")) >= {"3", "1", "7"}
    d.close()
    res, rep, _ = _apply_and_verify(SAMPLE, "38,223.96", "31,750.00", tmp_path)
    assert set(res.extended_chars) >= {"3", "1", "7"}
    assert rep.verified
    # glyph_resolution must confirm non-empty outlines for the new glyphs.
    g = {x.name: x for x in rep.gates}
    assert g["glyph_resolution"].passed
    assert g["visual_localized"].passed


def test_grow_and_shrink_alignment(tmp_path):
    for i, new in enumerate(("338,223.96", "8,223.96")):
        sub = tmp_path / f"case{i}"
        sub.mkdir()
        _, rep, _ = _apply_and_verify(SAMPLE, "38,223.96", new, sub)
        assert rep.verified, (new, [x.name for x in rep.gates if not x.passed])


def test_duplicate_value_single_change(tmp_path):
    # Two runs equal '38,223.96'; editing occurrence 0 must change exactly one.
    _, rep, _ = _apply_and_verify(SAMPLE, "38,223.96", "31,750.00", tmp_path, occurrence=0)
    g = {x.name: x for x in rep.gates}
    assert g["single_change"].passed


def test_negative_control_blank_glyph_rejected(tmp_path):
    """A deliberately broken edit (chars mapped to blank glyphs) MUST fail."""
    d = Document(SAMPLE)
    run = d.find("38,223.96")[0]
    model = d.models(0)[run.font]
    raw = bytearray()
    for c in "31,750.00":
        gid = model.uni2gid.get(c, 3)  # missing/empty -> space gid (blank)
        raw += bytes([(gid >> 8) & 0xFF, gid & 0xFF])
    page = d.pdf.pages[0]
    instrs = pikepdf.parse_content_stream(page)
    instrs[run.instr_index] = pikepdf.ContentStreamInstruction(
        [pikepdf.String(bytes(raw))], pikepdf.Operator("Tj"))
    page.Contents = d.pdf.make_stream(pikepdf.unparse_content_stream(instrs))
    out = str(tmp_path / "broken.pdf")
    d.pdf.save(out); d.close()
    er = EditResult(0, run.font, "38,223.96", "31,750.00", [], 41.0, 41.0, "left", 0.0)
    rep = verify_correction(SAMPLE, out, er, run, packet_dir=None)
    assert not rep.verified


def test_never_overwrites_input(tmp_path):
    before = Path(SAMPLE).read_bytes()
    _apply_and_verify(SAMPLE, "8,948.80", "9,750.50", tmp_path)
    assert Path(SAMPLE).read_bytes() == before


def test_repair_fills_blank_glyphs_doc_wide(tmp_path):
    """Repairing fills the empty-outline glyphs for both occurrences, changes no
    text, and leaves no repairable blanks."""
    d = Document(SAMPLE)
    assert find_blanks(d), "fixture should have repairable blanks (bold 3/9)"
    before_runs = [(r.page_index, r.font, r.text) for r in d.runs]
    res = repair_fonts(d)
    out = str(tmp_path / "repaired.pdf")
    d.pdf.save(out); d.close()
    assert any("3" in chars and "9" in chars for _, chars in res.filled)

    d2 = Document(out)
    after_runs = [(r.page_index, r.font, r.text) for r in d2.runs]
    assert find_blanks(d2) == []      # nothing left blank
    d2.close()
    assert before_runs == after_runs  # repair never alters text
    rep = verify_repair(SAMPLE, out, res.filled, packet_dir=None)
    assert rep.verified


def test_metadata_scrub_and_backdate_refusal(tmp_path):
    out = str(tmp_path / "scrubbed.pdf")
    res = scrub_metadata(SAMPLE, out, {"Author": "Acme HR"})
    with pikepdf.open(out) as p:
        assert "/Producer" not in p.docinfo
        assert str(p.docinfo.get("/Author")) == "Acme HR"
    with pytest.raises(ProvenanceForgery):
        scrub_metadata(SAMPLE, str(tmp_path / "x.pdf"), {"ModDate": "D:20200101000000"})
