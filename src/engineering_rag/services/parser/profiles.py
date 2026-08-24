"""Profile selection: deciding *which* conversion strategy to use, and why.

Split out of what used to be ``pipeline_factory.py`` because "which profile"
and "how to build the Docling objects for a profile" are two different
responsibilities — this module never imports Docling itself; it only reasons
over the independent preflight evidence and :class:`~engineering_rag.services.parser.config.ParserConfig`.
See :mod:`engineering_rag.services.parser.converter` for the Docling-facing half.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import ParserConfig, Profile
from .models import SourceManifest

__all__ = ["ProfileDecision", "choose_profile", "resolve_profile_config"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileDecision:
    """A profile choice plus the evidence that justified it.

    Auditability is the point: a run manifest that says "profile: scanned" is
    useless six months later without the measurement that caused it.
    """

    profile: Profile
    reason: str
    evidence: dict[str, Any]


def choose_profile(manifest: SourceManifest, config: ParserConfig) -> ProfileDecision:
    """Decide the effective profile for ``auto``, or confirm an explicit choice.

    The rule is deliberately conservative. OCR is enabled only when the document
    genuinely lacks an extractable text layer, because running OCR over good
    embedded text duplicates and degrades it — the exact failure this project
    must avoid.
    """
    pages = manifest.page_count or 1
    empty_or_sparse = len(set(manifest.sparse_pages) | set(manifest.empty_pages))
    sparse_fraction = empty_or_sparse / pages
    chars_per_page = manifest.total_char_count / pages
    evidence = {
        "page_count": pages,
        "total_char_count": manifest.total_char_count,
        "chars_per_page": round(chars_per_page, 1),
        "sparse_or_empty_pages": sorted(set(manifest.sparse_pages) | set(manifest.empty_pages)),
        "sparse_fraction": round(sparse_fraction, 4),
        "substantive_image_count": manifest.substantive_image_count,
    }

    if config.profile is not Profile.AUTO:
        return ProfileDecision(
            profile=config.profile,
            reason=f"Profile '{config.profile.value}' was requested explicitly; preflight evidence recorded for audit.",
            evidence=evidence,
        )

    # A genuinely scanned document has almost no extractable text anywhere.
    if sparse_fraction >= 0.8 or chars_per_page < 50:
        return ProfileDecision(
            profile=Profile.SCANNED,
            reason=(
                f"{empty_or_sparse}/{pages} pages carry little or no extractable text "
                f"({chars_per_page:.0f} chars/page): the document behaves as image-only, so OCR is required."
            ),
            evidence=evidence,
        )
    if manifest.substantive_image_count > 0:
        return ProfileDecision(
            profile=Profile.HIGH_FIDELITY,
            reason=(
                f"Native text is present ({chars_per_page:.0f} chars/page) and {manifest.substantive_image_count} "
                "non-repeated figure(s) were found: use accurate tables and referenced picture assets, without OCR."
            ),
            evidence=evidence,
        )
    return ProfileDecision(
        profile=Profile.DEFAULT,
        reason=f"Uniform digital text ({chars_per_page:.0f} chars/page) with no substantive figures; CPU-safe defaults suffice.",
        evidence=evidence,
    )


def resolve_profile_config(config: ParserConfig, profile: Profile) -> ParserConfig:
    """Apply a named profile's option overrides onto ``config``.

    Only Docling-facing options are touched; user-set thresholds, limits and
    export settings are preserved so a profile cannot silently relax a gate.
    """
    docling_opts = config.docling
    if profile is Profile.HIGH_FIDELITY:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": False,
                "do_table_structure": True,
                "table_mode": "accurate",
                "table_cell_matching": True,
                "generate_page_images": True,
                "generate_picture_images": True,
                "images_scale": max(docling_opts.images_scale, 2.0),
                "enable_heading_hierarchy": True,
            }
        )
    elif profile is Profile.SCANNED:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": True,
                "ocr_force_full_page": True,
                "ocr_mode": "full_page",
                "do_table_structure": True,
                "table_mode": "accurate",
                "generate_page_images": True,
                "generate_picture_images": True,
            }
        )
    elif profile is Profile.DEFAULT:
        docling_opts = docling_opts.model_copy(
            update={
                "do_ocr": False,
                "table_mode": "fast",
                "images_scale": min(docling_opts.images_scale, 1.5),
            }
        )
    return config.model_copy(update={"profile": profile, "docling": docling_opts})
