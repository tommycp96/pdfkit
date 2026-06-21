# Graph Report - pdfkit  (2026-06-21)

## Corpus Check
- 20 files · ~13,875 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 246 nodes · 542 edges · 17 communities (11 shown, 6 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 63 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1d9d2f81`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Phrase Edit & Subset Mutation|Phrase Edit & Subset Mutation]]
- [[_COMMUNITY_CLI Commands & Verification|CLI Commands & Verification]]
- [[_COMMUNITY_Document Model & Font Parsing|Document Model & Font Parsing]]
- [[_COMMUNITY_Metadata & Test Suite|Metadata & Test Suite]]
- [[_COMMUNITY_Benchmark & Correction Alignment|Benchmark & Correction Alignment]]
- [[_COMMUNITY_PDF Rendering & Visual Diff|PDF Rendering & Visual Diff]]
- [[_COMMUNITY_Architecture Decisions & Core Concepts|Architecture Decisions & Core Concepts]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Domain Glossary|Domain Glossary]]
- [[_COMMUNITY_Package Root|Package Root]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]

## God Nodes (most connected - your core abstractions)
1. `Document` - 49 edges
2. `FontModel` - 23 edges
3. `verify_correction()` - 22 edges
4. `verify_phrase_correction()` - 22 edges
5. `Run` - 18 edges
6. `repair_fonts()` - 17 edges
7. `apply_correction()` - 17 edges
8. `verify_repair()` - 17 edges
9. `_extend_subset()` - 16 edges
10. `EditResult` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Born-Digital PDF` --conceptually_related_to--> `Document`  [INFERRED]
  CONTEXT.md → pdfkit/document.py
- `Empty-Outline Glyph Bug` --conceptually_related_to--> `_extend_subset()`  [INFERRED]
  pdfkit-handoff-20260620-222149.md → pdfkit/edit.py
- `Pre-Delivery Correction` --conceptually_related_to--> `apply_correction()`  [INFERRED]
  CONTEXT.md → pdfkit/edit.py
- `FontResolver` --conceptually_related_to--> `Subset Extension`  [INFERRED]
  pdfkit/fonts.py → docs/adr/0002-extend-font-subset-not-reembed-full-font.md
- `ProvenanceForgery` --conceptually_related_to--> `Metadata Normalization`  [INFERRED]
  pdfkit/metadata.py → CONTEXT.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **End-to-end correction pipeline: Document -> apply_correction -> verify_correction** — pdfkit_document_document, pdfkit_edit_apply_correction, pdfkit_verify_verify_correction, pdfkit_edit_editresult, pdfkit_verify_verifyreport [EXTRACTED 0.95]
- **Subset extension flow: FontResolver -> _SubsetMutator -> _extend_subset** — pdfkit_fonts_fontresolver, pdfkit_edit_resolve_original, pdfkit_edit_subsetmutator, pdfkit_edit_extend_subset, concept_subset_extension [INFERRED 0.95]
- **Visual verification: render_page -> diff_images -> rep_visual -> visual_localized gate** — pdfkit_render_render_page, pdfkit_render_diff_images, pdfkit_verify_rep_visual, pdfkit_verify_word_boxes, concept_verification_gates [EXTRACTED 0.90]

## Communities (17 total, 6 thin omitted)

### Community 0 - "Phrase Edit & Subset Mutation"
Cohesion: 0.09
Nodes (44): _clean_phrase_span(), phrase_targets(), phrase_variants(), Document, Acceptance benchmark: generate realistic corrections, measure VERIFIED rate.  Fo, First per-glyph span on `page` whose runs spell exactly `word`., Return (kind, new_text) corrections for a value string., Corrections for an alphabetic word: typo-fix style edits with proportional     ( (+36 more)

### Community 1 - "CLI Commands & Verification"
Cohesion: 0.09
Nodes (38): Review Packet, Verification Gates (L2-L5), EditResult, Image, Re-run verification gates comparing an edited file to the original., verify(), EditResult, diff_images() (+30 more)

### Community 2 - "Document Model & Font Parsing"
Cohesion: 0.08
Nodes (27): Array, Object, Page, build_font_models(), Document, _empty_outline_gids(), extract_runs(), FontModel (+19 more)

### Community 3 - "Metadata & Test Suite"
Cohesion: 0.11
Nodes (28): Metadata Normalization, datetime, _pdf_date(), ProvenanceForgery, Metadata normalization: produce uniform, honest metadata for outgoing files.  Re, Raised on an attempt to backdate or fabricate provenance metadata., scrub_metadata(), ScrubResult (+20 more)

### Community 4 - "Benchmark & Correction Alignment"
Cohesion: 0.67
Nodes (3): run (benchmark), variants, word_variants

### Community 5 - "PDF Rendering & Visual Diff"
Cohesion: 0.19
Nodes (20): correct(), _correct_phrase(), _default_out(), inspect(), _print_report(), pdfkit command-line interface., Per-glyph phrase correction: locate the consecutive run span spelling     OLD, t, Fill empty/blank glyph outlines document-wide from the original font.      Chang (+12 more)

### Community 6 - "Architecture Decisions & Core Concepts"
Cohesion: 0.15
Nodes (11): ADR-0001: Text-layer extraction, not computer vision, ADR-0002: Extend font subset, not re-embed full font, Born-Digital PDF, Font Subset, Subset Extension, Original font programs (user-supplied), How it works, Install (+3 more)

### Community 10 - "Community 10"
Cohesion: 0.24
Nodes (5): Empty-Outline Glyph Bug, Phrase Span (per-glyph Tj+Td chain), Handoff document, Copies glyph outlines from an original font into an embedded subset.      Two op, _SubsetMutator

### Community 11 - "Community 11"
Cohesion: 0.18
Nodes (10): Artifacts to reference (do not duplicate), Constraints & rules (from the user's global CLAUDE.md + this project), Current state (done), Handoff: pdfkit — verifiable in-place PDF text correction, Key technical context / gotchas, Pending work / likely next focus, Redaction note, Suggested skills (+2 more)

### Community 12 - "Community 12"
Cohesion: 0.22
Nodes (7): Architecture: the read → correct → verify pipeline, Commands, Conventions specific to this repo, Fixtures, fonts, and why tests skip, graphify, Running the tool, What this is

### Community 13 - "Community 13"
Cohesion: 0.33
Nodes (5): Acceptance benchmark, Known limitations (honest), Method, Result, Why 100% is trustworthy, not trivial

## Knowledge Gaps
- **36 isolated node(s):** `Array`, `pdfkit`, `Method`, `Result`, `Why 100% is trustworthy, not trivial` (+31 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Document` connect `Document Model & Font Parsing` to `Phrase Edit & Subset Mutation`, `CLI Commands & Verification`, `Metadata & Test Suite`, `Benchmark & Correction Alignment`, `PDF Rendering & Visual Diff`, `Architecture Decisions & Core Concepts`, `Community 10`?**
  _High betweenness centrality (0.226) - this node is a cross-community bridge._
- **Why does `FontResolver` connect `Document Model & Font Parsing` to `Phrase Edit & Subset Mutation`, `Architecture Decisions & Core Concepts`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `FontModel` connect `Document Model & Font Parsing` to `Phrase Edit & Subset Mutation`, `CLI Commands & Verification`, `Community 10`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Document` (e.g. with `Document` and `Born-Digital PDF`) actually correct?**
  _`Document` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `FontModel` (e.g. with `FontModel` and `Run`) actually correct?**
  _`FontModel` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `Run` (e.g. with `FontModel` and `FontModel`) actually correct?**
  _`Run` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Acceptance benchmark: generate realistic corrections, measure VERIFIED rate.  Fo`, `Return (kind, new_text) corrections for a value string.`, `Corrections for an alphabetic word: typo-fix style edits with proportional     (` to the rest of the system?**
  _94 weakly-connected nodes found - possible documentation gaps or missing edges._