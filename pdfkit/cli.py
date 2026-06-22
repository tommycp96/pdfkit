"""pdfkit command-line interface."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from .document import Document
from .edit import (FontUnavailable, PhraseSpanError, apply_correction,
                   apply_phrase_correction, repair_fonts)
from .metadata import ProvenanceForgery, scrub_metadata
from .verify import verify_correction, verify_phrase_correction, verify_repair

app = typer.Typer(add_completion=False, help="Verifiable in-place PDF text correction.")


def _default_out(in_path: str, suffix: str) -> str:
    p = Path(in_path)
    return str(p.with_name(f"{p.stem}{suffix}{p.suffix}"))


@app.command()
def inspect(pdf: str, grep: str = typer.Option(None, help="only show runs containing this text")):
    """List positioned text runs (text, page, coords, font, size)."""
    d = Document(pdf)
    try:
        for r in d.runs:
            if grep and grep not in r.text:
                continue
            m = d.models(r.page_index).get(r.font)
            tag = "" if (m and m.editable) else "  [non-editable]"
            typer.echo(f"p{r.page_index} {r.font:8s} {r.size:5.1f}pt "
                       f"({r.x:7.1f},{r.y:7.1f})  {r.text!r}{tag}")
    finally:
        d.close()


@app.command()
def correct(
    pdf: str,
    replace: str = typer.Option(..., "--replace", help='OLD=NEW text to correct'),
    occurrence: int = typer.Option(None, help="0-based index when OLD matches several runs"),
    page: int = typer.Option(None, help="restrict to this page index"),
    near: str = typer.Option(None, help="restrict to runs near this label text"),
    out: str = typer.Option(None, "-o", "--out", help="output path (default *.fixed.pdf)"),
    align: str = typer.Option("auto", help="auto|left|right alignment handling"),
    apply: bool = typer.Option(False, "--apply", help="actually write + verify (default: dry-run)"),
    repair: bool = typer.Option(False, "--repair", help="also repair pre-existing blank glyphs document-wide"),
    phrase: bool = typer.Option(False, "--phrase", help="force per-glyph phrase mode (Chrome/Skia PDFs)"),
):
    """Correct a piece of text in place; dry-run previews, --apply writes + verifies."""
    if "=" not in replace:
        typer.echo("error: --replace must be OLD=NEW", err=True); raise typer.Exit(2)
    old, new = replace.split("=", 1)
    d = Document(pdf)
    matches = d.find(old, page=page, near=near)
    if not d.runs:
        # No extractable text at all: a scanned/image PDF, or a show-text
        # operator pdfkit can't read yet. Say so plainly rather than implying
        # the target string is simply absent.
        typer.echo("error: this PDF has no extractable text runs — it is either "
                   "scanned/image-only (out of scope) or uses a show-text "
                   "operator pdfkit cannot read yet.", err=True)
        d.close(); raise typer.Exit(1)
    # Auto-fallback: when OLD isn't a single run (per-glyph PDFs draw one glyph
    # per Tj), correct the consecutive run span instead. --phrase forces it.
    if phrase or not matches:
        _correct_phrase(d, pdf, old, new, page, near, occurrence, out, apply, repair)
        return
    if len(matches) > 1 and occurrence is None:
        typer.echo(f"{len(matches)} matches for {old!r} — choose with --occurrence N:")
        for i, r in enumerate(matches):
            typer.echo(f"  [{i}] page {r.page_index} {r.font} ({r.x:.0f},{r.y:.0f})  {r.text!r}")
        d.close(); raise typer.Exit(3)
    run = matches[occurrence or 0]
    model = d.models(run.page_index)[run.font]
    extend = model.missing_chars(new)

    if not apply:
        typer.echo("DRY RUN — no file written. Planned correction:")
        typer.echo(f"  page {run.page_index}, font {run.font} "
                   f"({model.base_font}), {run.size:.1f}pt")
        typer.echo(f"  {old!r}  ->  {new!r}")
        typer.echo(f"  subset extension needed for: {extend or 'none'}")
        typer.echo("  re-run with --apply to write and verify.")
        d.close(); raise typer.Exit(0)

    out = out or _default_out(pdf, ".fixed")
    if Path(out).resolve() == Path(pdf).resolve():
        typer.echo("error: refusing to overwrite the original; choose -o", err=True)
        d.close(); raise typer.Exit(2)
    try:
        res = apply_correction(d, run, new, align=align)
    except FontUnavailable as e:
        typer.echo(f"cannot apply: {e}", err=True); d.close(); raise typer.Exit(4)

    packet = Path(out).with_suffix(".review")
    if not repair:
        d.pdf.save(out); d.close()
        rep = verify_correction(pdf, out, res, run, packet_dir=packet)
        _print_report(f"{old!r} -> {new!r}, extended {res.extended_chars or 'none'}", rep, out, packet)
        raise typer.Exit(0 if rep.verified else 5)

    # --repair: verify the two transforms independently. The correction is
    # checked against a correction-only intermediate (so its localized/single-
    # change guarantee still holds); the repair is checked on top of that.
    rep_c, rep_r, filled = _repair_and_verify(
        d, pdf, out, packet,
        lambda interim: verify_correction(pdf, interim, res, run, packet_dir=None))
    verified = _print_repair_report(f"{old!r} -> {new!r}", rep_c, rep_r, filled, out, packet)
    raise typer.Exit(0 if verified else 5)


def _print_report(summary, rep, out, packet):
    typer.echo(f"\n{'VERIFIED' if rep.verified else 'FAILED'}  ({summary})")
    for g in rep.gates:
        adv = "" if g.critical else " (advisory)"
        typer.echo(f"  [{'PASS' if g.passed else 'FAIL'}] {g.name}{adv}: {g.detail}")
    typer.echo(f"\noutput : {out}\nreview : {packet}/report.md")


def _repair_and_verify(d, pdf, out, packet, verify_fn):
    """Apply font repair on top of an already-applied correction, then verify the
    two transforms independently: the correction against a correction-only
    interim, the repair on top of it. `verify_fn(interim)` runs the correction
    verifier (single-run or phrase). Returns (rep_c, rep_r, filled) and always
    removes the interim file."""
    import os
    import tempfile
    interim = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
    try:
        d.pdf.save(interim)
        filled = repair_fonts(d).filled
        d.pdf.save(out); d.close()
        rep_c = verify_fn(interim)
        rep_r = verify_repair(interim, out, filled, packet_dir=packet)
        return rep_c, rep_r, filled
    finally:
        try:
            os.unlink(interim)
        except OSError:
            pass


def _print_repair_report(headline, rep_c, rep_r, filled, out, packet):
    verified = rep_c.verified and rep_r.verified
    typer.echo(f"\n{'VERIFIED' if verified else 'FAILED'}  "
               f"({headline}); also repaired {filled or 'none'}")
    typer.echo("  correction gates:")
    for g in rep_c.gates:
        typer.echo(f"    [{'PASS' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    typer.echo("  repair gates:")
    for g in rep_r.gates:
        typer.echo(f"    [{'PASS' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    typer.echo(f"\noutput : {out}\nreview : {packet}/report.md")
    return verified


def _correct_phrase(d, pdf, old, new, page, near, occurrence, out, apply, repair):
    """Per-glyph phrase correction: locate the consecutive run span spelling
    OLD, then rewrite it. Same dry-run / --apply / --repair contract as the
    single-run path, verified by verify_phrase_correction."""
    if near is not None:
        # In per-glyph PDFs the label is itself split into one run per glyph, so
        # label-proximity matching can't work; say so instead of silently
        # ignoring it, and point at the mechanism that does work here.
        typer.echo("note: --near is not supported in per-glyph phrase mode; "
                   "use --occurrence to pick among matches.", err=True)
    spans = d.find_phrase(old, page=page)
    if not spans:
        typer.echo(f"no run or phrase span contains {old!r}", err=True)
        d.close(); raise typer.Exit(1)
    if len(spans) > 1 and occurrence is None:
        typer.echo(f"{len(spans)} phrase matches for {old!r} — choose with --occurrence N:")
        for i, span in enumerate(spans):
            r = span[0]
            typer.echo(f"  [{i}] page {r.page_index} ({r.x:.0f},{r.y:.0f})  "
                       f"{''.join(s.text for s in span)!r}")
        d.close(); raise typer.Exit(3)
    span = spans[occurrence or 0]
    pi = span[0].page_index
    fonts = sorted({r.font for r in span})
    extend = set()
    for f in fonts:
        extend |= set(d.models(pi)[f].missing_chars(new))

    if not apply:
        typer.echo("DRY RUN — no file written. Planned phrase correction:")
        typer.echo(f"  page {pi}, fonts {fonts}, {len(span)} glyph run(s), {span[0].size:.1f}pt")
        typer.echo(f"  {old!r}  ->  {new!r}")
        typer.echo(f"  subset extension needed for: {sorted(extend) or 'none'}")
        typer.echo("  re-run with --apply to write and verify.")
        d.close(); raise typer.Exit(0)

    out = out or _default_out(pdf, ".fixed")
    if Path(out).resolve() == Path(pdf).resolve():
        typer.echo("error: refusing to overwrite the original; choose -o", err=True)
        d.close(); raise typer.Exit(2)
    try:
        res = apply_phrase_correction(d, span, new)
    except (FontUnavailable, PhraseSpanError) as e:
        typer.echo(f"cannot apply: {e}", err=True); d.close(); raise typer.Exit(4)

    packet = Path(out).with_suffix(".review")
    if not repair:
        d.pdf.save(out); d.close()
        rep = verify_phrase_correction(pdf, out, res, span, packet_dir=packet)
        _print_report(f"{old!r} -> {new!r}, extended {res.extended_chars or 'none'}", rep, out, packet)
        raise typer.Exit(0 if rep.verified else 5)

    # --repair: verify the two transforms independently (see single-run path).
    rep_c, rep_r, filled = _repair_and_verify(
        d, pdf, out, packet,
        lambda interim: verify_phrase_correction(pdf, interim, res, span, packet_dir=None))
    verified = _print_repair_report(f"{old!r} -> {new!r}", rep_c, rep_r, filled, out, packet)
    raise typer.Exit(0 if verified else 5)


@app.command()
def repair(
    pdf: str,
    out: str = typer.Option(None, "-o", "--out", help="output path (default *.repaired.pdf)"),
):
    """Fill empty/blank glyph outlines document-wide from the original font.

    Changes no text, widths, or positions — only restores missing glyph shapes so
    blank-rendering values (valid text, no outline) render correctly everywhere.
    """
    out = out or _default_out(pdf, ".repaired")
    if Path(out).resolve() == Path(pdf).resolve():
        typer.echo("error: refusing to overwrite the original; choose -o", err=True)
        raise typer.Exit(2)
    d = Document(pdf)
    res = repair_fonts(d)
    d.pdf.save(out); d.close()
    if not res.filled and not res.unresolved:
        typer.echo("no blank glyphs found — nothing to repair.")
        typer.echo(f"output: {out}")
        raise typer.Exit(0)

    packet = Path(out).with_suffix(".review")
    rep = verify_repair(pdf, out, res.filled, packet_dir=packet)
    headline = "VERIFIED" if rep.verified else "FAILED"
    typer.echo(f"\n{headline}  filled {res.filled or 'none'}")
    if res.unresolved:
        typer.echo(f"  could not repair (original font missing): {res.unresolved}")
    for g in rep.gates:
        typer.echo(f"  [{'PASS' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    typer.echo(f"\noutput : {out}\nreview : {packet}/report.md")
    raise typer.Exit(0 if rep.verified else 5)


@app.command(name="scrub-metadata")
def scrub_metadata_cmd(
    pdf: str,
    out: str = typer.Option(None, "-o", "--out", help="output path (default *.scrubbed.pdf)"),
    set_: list[str] = typer.Option(None, "--set", help="key=value honest metadata to set"),
):
    """Remove tool/identity metadata and normalize to honest values."""
    out = out or _default_out(pdf, ".scrubbed")
    values = {}
    for kv in (set_ or []):
        if "=" in kv:
            k, v = kv.split("=", 1); values[k] = v
    try:
        res = scrub_metadata(pdf, out, values)
    except ProvenanceForgery as e:
        typer.echo(f"refused: {e}", err=True); raise typer.Exit(2)
    typer.echo(f"removed: {res.removed_keys}")
    typer.echo(f"XMP removed: {res.xmp_removed}; set: {res.set_keys}")
    typer.echo(f"output: {out}")


@app.command()
def verify(original: str, edited: str, expect: str = typer.Option(..., help="OLD=NEW")):
    """Re-run verification gates comparing an edited file to the original."""
    old, new = expect.split("=", 1)
    d = Document(original)
    runs = d.find(old)
    d.close()
    if not runs:
        typer.echo(f"original has no run {old!r}", err=True); raise typer.Exit(1)
    from .edit import EditResult
    run = runs[0]
    er = EditResult(run.page_index, run.font, old, new, [], 0.0, 0.0, "left", 0.0)
    rep = verify_correction(original, edited, er, run, packet_dir=None)
    for g in rep.gates:
        typer.echo(f"  [{'PASS' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    typer.echo("VERIFIED" if rep.verified else "FAILED")
    raise typer.Exit(0 if rep.verified else 5)


if __name__ == "__main__":
    app()
