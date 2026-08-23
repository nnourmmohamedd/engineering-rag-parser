"""Visual review artifacts for pages that text metrics cannot judge.

For every flagged page this builds a self-contained HTML review card showing the
source-page rendering next to the parsed regions, with the Docling bounding
boxes drawn as an SVG overlay. Everything is produced locally with PDFium and
Pillow; nothing is uploaded.

The design principle: a page whose content is a diagram must be reviewed by a
human looking at the page, not signed off by a number. These artifacts exist to
make that review cheap enough to actually happen.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument

from ..artifacts import RunDirectory
from ..config import ParserConfig
from ..domain import CheckResult, PageCoverage, Severity, SourceManifest
from ..preflight import render_page_png

__all__ = ["build_visual_reviews", "visual_checks"]

logger = logging.getLogger(__name__)

#: Colour per Docling label family, so the overlay is readable at a glance.
_LABEL_COLOURS = {
    "picture": "#d9480f",
    "table": "#5f3dc4",
    "section_header": "#1864ab",
    "title": "#1864ab",
    "list_item": "#2b8a3e",
    "caption": "#a61e4d",
    "page_header": "#868e96",
    "page_footer": "#868e96",
}
_DEFAULT_COLOUR = "#495057"


def _page_regions(document: DoclingDocument, page_no: int) -> list[dict[str, Any]]:
    """Bounding boxes for every provenance-bearing item on a page.

    Coordinates are converted from PDF space (origin bottom-left) to image space
    (origin top-left) so they can be drawn directly over the rendering.
    """
    page = document.pages.get(page_no)
    if page is None or page.size is None:
        return []
    height = float(page.size.height)
    regions: list[dict[str, Any]] = []
    layers = {ContentLayer.BODY, ContentLayer.FURNITURE, ContentLayer.BACKGROUND}
    for item, _lvl in document.iterate_items(
        with_groups=False, page_no=page_no, included_content_layers=layers
    ):
        for prov in getattr(item, "prov", []) or []:
            if int(prov.page_no) != page_no:
                continue
            bbox = prov.bbox
            label = getattr(getattr(item, "label", None), "value", "unknown")
            regions.append(
                {
                    "label": label,
                    "x": float(bbox.l),
                    "y": height - float(bbox.t),  # flip to top-left origin
                    "w": float(bbox.r - bbox.l),
                    "h": float(bbox.t - bbox.b),
                    "text": (getattr(item, "text", "") or "")[:80],
                    "colour": _LABEL_COLOURS.get(label, _DEFAULT_COLOUR),
                }
            )
    return regions


def _render_card(
    page_no: int,
    coverage: PageCoverage,
    source_page: Any,
    regions: list[dict[str, Any]],
    page_image_rel: str,
    page_width: float,
    page_height: float,
) -> str:
    """Build one self-contained HTML review card."""
    overlay = "\n".join(
        f'      <rect x="{r["x"]:.1f}" y="{r["y"]:.1f}" width="{r["w"]:.1f}" height="{r["h"]:.1f}" '
        f'fill="none" stroke="{r["colour"]}" stroke-width="2" vector-effect="non-scaling-stroke">'
        f"<title>{html.escape(r['label'])}: {html.escape(r['text'])}</title></rect>"
        for r in regions
    )
    legend = "".join(
        f'<span class="chip" style="border-color:{colour}">{html.escape(label)}</span>'
        for label, colour in sorted(
            {r["label"]: r["colour"] for r in regions}.items()
        )
    )
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in coverage.notes) or "<li>No automated notes.</li>"
    missing = (
        "".join(f"<code>{html.escape(t)}</code> " for t in coverage.missing_critical_tokens[:20])
        or "<em>none</em>"
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Page {page_no} — visual review</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 1.5rem;
         background: #f8f9fa; color: #212529; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#16181c; color:#e9ecef; }}
    .panel {{ background:#212529 !important; border-color:#343a40 !important; }}
    table td, table th {{ border-color:#343a40 !important; }} }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
  .wrap {{ display: grid; grid-template-columns: minmax(320px, 1fr) minmax(280px, 420px);
           gap: 1.25rem; align-items: start; }}
  @media (max-width: 900px) {{ .wrap {{ grid-template-columns: 1fr; }} }}
  .panel {{ background:#fff; border:1px solid #dee2e6; border-radius:8px; padding:1rem; }}
  svg {{ width:100%; height:auto; display:block; }}
  table {{ border-collapse: collapse; width:100%; font-size:0.85rem; }}
  td, th {{ border:1px solid #dee2e6; padding:0.3rem 0.5rem; text-align:left; }}
  th {{ width: 55%; font-weight:600; }}
  .chip {{ display:inline-block; border:2px solid; border-radius:4px; padding:0.05rem 0.4rem;
           margin:0 0.25rem 0.25rem 0; font-size:0.75rem; }}
  code {{ background:rgba(128,128,128,.18); padding:0.05rem 0.3rem; border-radius:3px; font-size:0.8rem; }}
  ul {{ margin:0.4rem 0 0; padding-left:1.1rem; font-size:0.85rem; }}
</style></head>
<body>
<h1>Page {page_no} — source rendering with parsed regions</h1>
<div class="wrap">
  <div class="panel">
    <svg viewBox="0 0 {page_width:.0f} {page_height:.0f}" xmlns="http://www.w3.org/2000/svg">
      <image href="../../{html.escape(page_image_rel)}" x="0" y="0"
             width="{page_width:.0f}" height="{page_height:.0f}" />
{overlay}
    </svg>
    <div style="margin-top:.6rem">{legend}</div>
  </div>
  <div class="panel">
    <table>
      <tr><th>Native characters</th><td>{coverage.source_chars}</td></tr>
      <tr><th>Parsed characters</th><td>{coverage.parsed_chars}</td></tr>
      <tr><th>Character coverage</th><td>{coverage.char_coverage:.1%}</td></tr>
      <tr><th>Token recall</th><td>{coverage.token_recall:.1%}</td></tr>
      <tr><th>Critical-token recall</th><td>{coverage.critical_token_recall:.1%}</td></tr>
      <tr><th>Substantive figures (source)</th><td>{source_page.substantive_image_count}</td></tr>
      <tr><th>Figure area of page</th><td>{source_page.substantive_image_area_fraction:.1%}</td></tr>
      <tr><th>Docling regions on page</th><td>{len(regions)}</td></tr>
      <tr><th>Sparse text</th><td>{coverage.is_sparse_text}</td></tr>
      <tr><th>Severity</th><td><strong>{coverage.severity.value}</strong></td></tr>
    </table>
    <p style="font-size:.85rem;margin:.8rem 0 .2rem"><strong>Automated notes</strong></p>
    <ul>{notes}</ul>
    <p style="font-size:.85rem;margin:.8rem 0 .2rem"><strong>Missing critical tokens</strong></p>
    <p style="font-size:.8rem">{missing}</p>
    <p style="font-size:.8rem;color:#868e96;margin-top:1rem">
      Machine metrics cannot confirm that diagram labels, symbols or connections were recovered.
      This page requires human confirmation.</p>
  </div>
</div>
</body></html>
"""


def build_visual_reviews(
    document: DoclingDocument,
    manifest: SourceManifest,
    coverage_rows: list[PageCoverage],
    run: RunDirectory,
    config: ParserConfig,
    pdf_path: Path,
    page_images: dict[int, str],
) -> dict[int, str]:
    """Create a review artifact for every page preflight flagged.

    Returns ``{page_no: relative_path_to_review_html}``.
    """
    by_page = {p.page_no: p for p in coverage_rows}
    source_by_page = {p.page_no: p for p in manifest.pages}
    targets = sorted(set(manifest.visual_review_pages) | {
        p.page_no for p in coverage_rows if p.severity is not Severity.INFO
    })

    produced: dict[int, str] = {}
    rendered = 0
    for page_no in targets:
        coverage = by_page.get(page_no)
        source_page = source_by_page.get(page_no)
        if coverage is None or source_page is None:
            continue

        page_image_rel = page_images.get(page_no)
        if page_image_rel is None:
            # Docling did not retain a page image; render it ourselves so the
            # reviewer still gets the page, rather than an empty card.
            if rendered >= config.limits.max_render_pages:
                logger.warning("Render budget exhausted; page %d review has no image.", page_no)
                continue
            rel = f"{config.export.page_image_subdir}/page{page_no:03d}.png"
            try:
                render_page_png(pdf_path, page_no, run.path_for(rel), scale=1.5)
                page_image_rel = rel
                rendered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not render page %d: %s", page_no, exc)
                continue

        regions = _page_regions(document, page_no)
        card = _render_card(
            page_no, coverage, source_page, regions, page_image_rel,
            source_page.width_pt, source_page.height_pt,
        )
        rel = f"validation/review/page{page_no:03d}.html"
        run.write_text(rel, card)
        coverage.review_artifact = rel
        produced[page_no] = rel

    logger.info("Visual review artifacts: %d page(s)", len(produced))
    return produced


def visual_checks(
    manifest: SourceManifest, coverage_rows: list[PageCoverage], reviews: dict[int, str]
) -> list[CheckResult]:
    """Confirm every page needing visual review actually received an artifact."""
    required = set(manifest.visual_review_pages)
    missing = sorted(required - set(reviews))

    checks = [
        CheckResult(
            check_id="visual_review_coverage",
            title="Every sparse or figure-bearing page has a visual review artifact",
            passed=not missing,
            severity=Severity.CRITICAL,
            gate=True,
            summary=(
                f"{len(reviews)} review artifact(s) produced for {len(required)} flagged page(s)."
                if not missing
                else f"Pages flagged but not reviewed: {missing}"
            ),
            evidence={
                "flagged_pages": sorted(required),
                "reviewed_pages": sorted(reviews),
                "missing": missing,
                "selection_rule": "a page is flagged when it carries any non-repeated image, is sparse, "
                "or is empty — presence-based, not area-based",
            },
            threshold={"required": "one artifact per flagged page"},
            remediation="Re-run with page rendering enabled.",
        ),
        CheckResult(
            check_id="visual_content_not_text_verified",
            title="Figure-bearing pages are not signed off on text metrics alone",
            passed=True,
            severity=Severity.INFO,
            gate=False,
            summary=(
                f"{len(manifest.pages_with_substantive_images)} page(s) carry a substantive figure "
                f"({manifest.substantive_image_count} figures total). Their diagram content is preserved as "
                "image assets; no machine check confirms that labels, symbols or connections were recovered."
            ),
            evidence={
                "figure_pages": manifest.pages_with_substantive_images,
                "substantive_figures": manifest.substantive_image_count,
                "decorative_images": manifest.decorative_image_count,
            },
            threshold={"rule": "informational — requires human confirmation"},
            remediation="Open each artifact under validation/review/ and confirm the figure content.",
        ),
    ]
    return checks
