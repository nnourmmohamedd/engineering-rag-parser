"""Human-readable ``chunking_summary.md`` rendering."""

from __future__ import annotations

from .config import ChunkerConfig
from .models import ChunkManifest, ChunkValidationReport

__all__ = ["render_summary_markdown"]


def render_summary_markdown(
    *, manifest: ChunkManifest, report: ChunkValidationReport, config: ChunkerConfig
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Chunking run summary")
    add("")
    add(f"**Status: `{report.status.value}`**" + (" (strict mode: warnings fail)" if report.strict else ""))
    add("")
    add(f"- Source: `{manifest.source['filename']}` (sha256 `{manifest.source['sha256'][:16]}…`)")
    add(f"- Run ID: `{manifest.run_id}`")
    add(f"- Generated: {manifest.generated_at_utc.isoformat()}")
    add("")

    add("## Configuration")
    add("")
    add(f"- Profile: `{config.profile}`")
    add(f"- Tokenizer: `{config.tokenizer.name}`")
    add(
        f"- max_tokens={config.max_tokens}, target_tokens={config.target_tokens}, "
        f"min_chunk_tokens={config.min_chunk_tokens}, text_overlap_tokens={config.text_overlap_tokens}"
    )
    add(
        f"- merge_small_chunks={config.merge_small_chunks}, repeat_table_headers={config.repeat_table_headers}, "
        f"include_heading_context={config.include_heading_context}, "
        f"allowed_atomic_overflow={config.allowed_atomic_overflow}"
    )
    add("")

    add("## Statistics")
    add("")
    add(f"- Total chunks: **{manifest.chunk_count}**")
    add(
        f"- Recursively split (hierarchical chunks that needed splitting): {manifest.recursively_split_count}"
    )
    add(f"- Merged (small-sibling merges applied): {manifest.merged_count}")
    add("")
    add("| Content type | Count |")
    add("|---|---:|")
    for content_type, count in sorted(manifest.content_type_counts.items()):
        add(f"| `{content_type}` | {count} |")
    add("")
    stats = manifest.token_stats
    add(
        f"- Token count — min {stats.get('min', 0):.0f}, median {stats.get('median', 0):.0f}, "
        f"mean {stats.get('mean', 0):.1f}, p95 {stats.get('p95', 0):.0f}, max {stats.get('max', 0):.0f}"
    )
    add("")

    add("## Validation")
    add("")
    add("| Check | Gate | Severity | Result | Summary |")
    add("|---|---|---|---|---|")
    for check in report.checks:
        result = "PASS" if check.passed else "**FAIL**"
        gate = "yes" if check.gate else "—"
        add(
            f"| `{check.check_id}` | {gate} | {check.severity.value} | {result} | {check.summary.replace('|', chr(92) + '|')} |"
        )
    add("")

    if report.human_review_items:
        add("## Human review required")
        add("")
        for item in report.human_review_items:
            add(f"- {item}")
        add("")

    if manifest.warnings:
        add("## Chunk-level warnings")
        add("")
        for warning in sorted(set(manifest.warnings))[:50]:
            add(f"- {warning}")
        add("")

    add("## Timings (s)")
    add("")
    for stage, seconds in manifest.timings_s.items():
        add(f"- {stage}: {seconds:.2f}")
    add("")

    return "\n".join(lines) + "\n"
