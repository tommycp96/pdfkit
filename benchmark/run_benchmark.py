"""Acceptance benchmark: generate realistic corrections, measure VERIFIED rate.

For each fixture PDF we take every editable, value-looking run and synthesize
several plausible corrections (same-length digit swap, grow, shrink, and a
forced subset-extension case). Each is applied to a fresh copy, fully verified,
and counted. The headline metric is the fraction of scenarios that come back
VERIFIED with all critical gates passing.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdfkit.document import Document
from pdfkit.edit import FontUnavailable, apply_correction
from pdfkit.verify import verify_correction

VALUE_RE = re.compile(r"^[\$S]*[\d][\d,\.\-/]{2,}$")
WORD_RE = re.compile(r"^[A-Za-z]{4,}$")


def variants(text: str) -> list[tuple[str, str]]:
    """Return (kind, new_text) corrections for a value string."""
    digits = [c for c in text if c.isdigit()]
    if not digits:
        return []
    out: list[tuple[str, str]] = []

    swap = "".join(str((int(c) + 5) % 10) if c.isdigit() else c for c in text)
    if swap != text:
        out.append(("same_len", swap))

    # grow: duplicate the first digit
    i = next((k for k, c in enumerate(text) if c.isdigit()), None)
    if i is not None:
        out.append(("grow", text[:i] + text[i] + text[i:]))

    # shrink: drop the last digit
    j = max((k for k, c in enumerate(text) if c.isdigit()), default=None)
    if j is not None and sum(c.isdigit() for c in text) > 2:
        out.append(("shrink", text[:j] + text[j + 1:]))

    # force extension: push 1s and 7s through (often absent from bold subsets)
    forced = "".join("17"[k % 2] if c.isdigit() else c for k, c in enumerate(text))
    if forced != text:
        out.append(("force_ext", forced))
    return out


def word_variants(text: str) -> list[tuple[str, str]]:
    """Corrections for an alphabetic word: typo-fix style edits with proportional
    (non-tabular) glyphs that stress alignment and may need subset extension."""
    out: list[tuple[str, str]] = []
    # change one letter (mid-word) -> different glyph, same length
    if len(text) >= 5:
        mid = len(text) // 2
        repl = "x" if text[mid].lower() != "x" else "q"
        repl = repl.upper() if text[mid].isupper() else repl
        out.append(("word_same", text[:mid] + repl + text[mid + 1:]))
    # transpose two adjacent letters (very common typo)
    if len(text) >= 4 and text[1] != text[2]:
        out.append(("word_swap", text[0] + text[2] + text[1] + text[3:]))
    # grow / shrink
    out.append(("word_grow", text + text[-1]))
    if len(text) >= 5:
        out.append(("word_shrink", text[:-1]))
    return [(k, v) for k, v in out if v != text]


def run(fixtures: list[str], per_run_limit: int, sample: int | None) -> None:
    scenarios = []
    for fx in fixtures:
        d = Document(fx)
        seen = Counter()
        for r in d.runs:
            model = d.models(r.page_index).get(r.font)
            if not (model and model.editable):
                continue
            if VALUE_RE.match(r.text):
                vs = variants(r.text)
            elif WORD_RE.match(r.text):
                vs = word_variants(r.text)
            else:
                continue
            seen[r.text] += 1
            for kind, new in vs[:per_run_limit]:
                scenarios.append((fx, r.page_index, r.text, seen[r.text] - 1, kind, new))
        d.close()
    if sample:
        step = max(1, len(scenarios) // sample)
        scenarios = scenarios[::step][:sample]

    results = []
    by_kind: dict[str, list[bool]] = {}
    fail_reasons: Counter = Counter()
    for n, (fx, page, old, occ, kind, new) in enumerate(scenarios, 1):
        d = Document(fx)
        hits = [r for r in d.find(old, page=page)]
        if occ >= len(hits):
            d.close(); continue
        run_obj = hits[occ]
        try:
            res = apply_correction(d, run_obj, new)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                out = tf.name
            d.pdf.save(out); d.close()
            rep = verify_correction(fx, out, res, run_obj, packet_dir=None)
            ok = rep.verified
            if not ok:
                for g in rep.gates:
                    if g.critical and not g.passed:
                        fail_reasons[g.name] += 1
        except FontUnavailable as e:
            d.close(); ok = False; fail_reasons["font_unavailable"] += 1
        except Exception as e:  # noqa
            d.close(); ok = False; fail_reasons[f"exc:{type(e).__name__}"] += 1
        results.append(ok)
        by_kind.setdefault(kind, []).append(ok)
        if n % 25 == 0:
            print(f"  ...{n}/{len(scenarios)} so far {sum(results)}/{len(results)}", file=sys.stderr)

    total = len(results)
    passed = sum(results)
    print("\n==================== ACCEPTANCE BENCHMARK ====================")
    print(f"scenarios: {total}   VERIFIED: {passed}   rate: {passed/total*100:.1f}%"
          if total else "no scenarios")
    print("\nby kind:")
    for kind, vals in sorted(by_kind.items()):
        print(f"  {kind:10s} {sum(vals):3d}/{len(vals):3d}  {sum(vals)/len(vals)*100:5.1f}%")
    if fail_reasons:
        print("\nfailure gates:")
        for name, c in fail_reasons.most_common():
            print(f"  {name:22s} {c}")
    print("==============================================================")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures", nargs="*", default=None)
    ap.add_argument("--per-run", type=int, default=4)
    ap.add_argument("--sample", type=int, default=None)
    args = ap.parse_args()
    # Pass your own born-digital PDFs as arguments; none are bundled (privacy).
    fx = [f for f in (args.fixtures or []) if Path(f).is_file()]
    if not fx:
        ap.error("supply one or more born-digital PDF paths to benchmark, e.g.\n"
                 "  python benchmark/run_benchmark.py sample-a.pdf sample-b.pdf")
    print("fixtures:", fx)
    run(fx, args.per_run, args.sample)
