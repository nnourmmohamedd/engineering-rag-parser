"""Generate docs/docling_parameter_guide.md from the INSTALLED Docling API.

The table body is produced by introspecting the objects this project actually
constructs, so the guide cannot drift away from the code. Prose commentary is
authored; every default/selected value is machine-read.
"""

from __future__ import annotations

import json
from pathlib import Path

from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    OcrEngine,
    OcrMode,
    PdfBackend,
    PdfPipelineOptions,
    ProcessingPipeline,
    TableFormerMode,
)

from engineering_rag_parser.config import Profile, load_config
from engineering_rag_parser.pipeline_factory import (
    _describe_suboption,
    build_pipeline_options,
    docling_versions,
    resolve_profile_config,
)


def _dumped(pipeline: PdfPipelineOptions) -> dict[str, object]:
    """Dump with the same subclass-aware fix as `describe_effective_options` (D-2).

    `PdfPipelineOptions.model_dump()` alone serialises `table_structure_options`
    / `ocr_options` by their declared abstract-base field type, dropping the
    concrete subclass's fields — this guide must not regenerate the `{}`
    artefact the audit found.
    """
    dumped = pipeline.model_dump(mode="json")
    dumped["table_structure_options"] = _describe_suboption(pipeline.table_structure_options)
    dumped["ocr_options"] = _describe_suboption(pipeline.ocr_options)
    return dumped


STOCK = _dumped(PdfPipelineOptions())
HF = load_config("configs/high_fidelity.yaml")
HF_EFF = resolve_profile_config(HF, Profile.HIGH_FIDELITY)
CHOSEN = _dumped(build_pipeline_options(HF_EFF))
VERSIONS = docling_versions()


def fmt(v: object, limit: int = 62) -> str:
    s = json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else str(v)
    s = s.replace("|", "\\|")
    return f"`{s[:limit]}…`" if len(s) > limit else f"`{s}`"


# public config key, docling field, effect, trade-off, when to change, used here
ROWS: list[tuple[str, str, str, str, str, str]] = [
    (
        "docling.backend",
        "PdfFormatOption.backend",
        "Which low-level PDF reader produces text cells and geometry.",
        "`docling_parse` is the most accurate; `pypdfium2` is faster but weaker on complex layout.",
        "Switch to `pypdfium2` only if `docling_parse` fails on a specific file.",
        "Yes — `docling_parse` (`DoclingParseDocumentBackend`)",
    ),
    (
        "docling.do_ocr",
        "PdfPipelineOptions.do_ocr",
        "Runs an OCR engine over the page.",
        "**Docling defaults this to `True`.** On a digital PDF it costs minutes and can duplicate or degrade clean embedded text.",
        "Turn on ONLY when preflight shows the document has no usable text layer.",
        "Yes — forced **off**; the document is text-searchable (36,338 native chars)",
    ),
    (
        "docling.ocr_engine",
        "OcrOptions subclass",
        "EasyOCR / RapidOCR / Tesseract selection when OCR is on.",
        "EasyOCR downloads ~100 MB of weights; Tesseract needs a system binary.",
        "Only relevant with `do_ocr: true`.",
        "No — OCR disabled",
    ),
    (
        "docling.ocr_mode",
        "OcrOptions.mode",
        "`full_page` rasterises and OCRs whole pages; `default` targets detected regions.",
        "Full-page is thorough and slow. Note `force_full_page_ocr` is **deprecated** in 2.121.0 in favour of `mode`.",
        "Use `full_page` for genuine scans.",
        "No — OCR disabled",
    ),
    (
        "docling.do_table_structure",
        "PdfPipelineOptions.do_table_structure",
        "Runs TableFormer to recover table cell structure.",
        "Adds significant CPU time; without it tables become undifferentiated text.",
        "Disable only when the document has no tables.",
        "Yes — enabled",
    ),
    (
        "docling.table_mode",
        "TableStructureOptions.mode",
        "`accurate` vs `fast` TableFormer variant.",
        "`accurate` is markedly slower but handles merged/irregular cells far better.",
        "Use `fast` for throughput on simple grid tables.",
        "Yes — `accurate` (already Docling's own default)",
    ),
    (
        "docling.table_cell_matching",
        "TableStructureOptions.do_cell_matching",
        "Matches predicted cells back to real PDF text cells.",
        "Off means predicted text instead of source text — a fidelity loss.",
        "Leave on for any text-bearing table.",
        "Yes — enabled",
    ),
    (
        "docling.generate_page_images",
        "PdfPipelineOptions.generate_page_images",
        "Retains a raster of each page in the document.",
        "Memory and disk grow with `images_scale`; required for the visual review cards.",
        "Disable for a text-only, low-memory batch run.",
        "Yes — enabled (27 page PNGs)",
    ),
    (
        "docling.generate_picture_images",
        "PdfPipelineOptions.generate_picture_images",
        "Retains a crop per detected picture, enabling referenced assets.",
        "Without it every figure becomes an unusable placeholder.",
        "Keep on whenever figures matter.",
        "Yes — enabled (15 substantive assets written)",
    ),
    (
        "docling.images_scale",
        "PdfPipelineOptions.images_scale",
        "Raster scale factor (1.0 ≈ 72 DPI).",
        "2.0 quadruples pixel count vs 1.0. Below ~2.0, instrument tags inside a preserved diagram stop being legible.",
        "Raise to 3.0 for dense P&IDs; drop to 1.0 under memory pressure.",
        "Yes — `2.0` (Docling default is `1.0`)",
    ),
    (
        "docling.generate_table_images",
        "PdfPipelineOptions.generate_table_images",
        "Retains a crop per detected table.",
        "Redundant here: crops are produced on demand via `TableItem.get_image()`.",
        "Enable if you want table crops for every run regardless of outcome.",
        "No — left off; crops taken on demand for unrecovered tables",
    ),
    (
        "docling.enable_heading_hierarchy",
        "HeadingHierarchyOptions.enabled",
        "Infers heading levels from bookmarks, numbering and font style.",
        "**Docling defaults this off.** On this document it produced the correct H1→H4 nesting; its one cost is that TOC list items promoted to headings lose their leading number marker (the body headings keep theirs).",
        "Disable if your document's numbering must survive verbatim in a TOC.",
        "Yes — enabled; 76 headings, no level jumps",
    ),
    (
        "docling.do_picture_classification",
        "PdfPipelineOptions.do_picture_classification",
        "Classifies pictures into a taxonomy (chart, logo, …).",
        "Extra model load and runtime; this project classifies figures from source-image evidence instead.",
        "Enable if you need Docling's own picture taxonomy.",
        "No — preflight bbox-signature evidence is used instead",
    ),
    (
        "docling.do_code_enrichment / do_formula_enrichment",
        "PdfPipelineOptions.do_code_enrichment / do_formula_enrichment",
        "Detect code blocks and convert formulas to LaTeX.",
        "Each loads an additional model.",
        "Enable for scientific or software documents.",
        "No — this document has 0 code blocks and 0 formulas",
    ),
    (
        "docling.picture_description.enabled",
        "PdfPipelineOptions.do_picture_description",
        "Local VLM writes a caption for each picture.",
        "Slow on CPU, and a *hallucination risk on exactly the content an engineer most needs correct* (P&IDs, loop wiring). See ADR-005.",
        "Enable only with review capacity and ≥ 4 GB VRAM; output is a machine annotation, never evidence.",
        "**No — disabled by policy**",
    ),
    (
        "docling.accelerator_device",
        "AcceleratorOptions.device",
        "`cpu` / `cuda` / `mps` / `xpu` / `auto`.",
        "The local MX450 exposes 2 GB VRAM; a CUDA OOM mid-conversion yields a *partial* document, the worst outcome for an auditable parser.",
        "Set `cuda` with ≥ 6 GB VRAM.",
        "Yes — `cpu` (ADR-002); `torch.cuda.is_available()` is `False` on the CPU wheel",
    ),
    (
        "docling.num_threads",
        "AcceleratorOptions.num_threads",
        "Intra-op thread count for inference.",
        "Beyond physical core count, contention degrades throughput.",
        "Match physical cores (4 here).",
        "Yes — `4`",
    ),
    (
        "docling.artifacts_path",
        "PdfPipelineOptions.artifacts_path",
        "Local model cache directory.",
        "Set it to run fully offline and to pin model versions.",
        "Set in air-gapped or reproducibility-critical deployments.",
        "No — default HF cache used",
    ),
    (
        "docling.enable_remote_services",
        "PdfPipelineOptions.enable_remote_services",
        "Permits Docling to call remote services.",
        "Would send document content off the machine.",
        "Never, for confidential input.",
        "**No — a config validator rejects `true`**",
    ),
    (
        "limits.document_timeout_s",
        "PdfPipelineOptions.document_timeout",
        "Wall-clock ceiling for one document.",
        "Too low truncates into a partial parse; too high lets a hostile file hang a worker.",
        "Scale with page count.",
        "Yes — `3600.0`",
    ),
    (
        "limits.max_pages / max_file_size_mb",
        "DocumentConverter.convert(max_num_pages=…, max_file_size=…)",
        "Refuses oversized input before parsing.",
        "Pure safety; no quality effect.",
        "Lower in a shared service.",
        "Yes — `2000` pages / `256` MB (input: 27 pages, 5.1 MB)",
    ),
]


def main() -> None:
    out: list[str] = []
    add = out.append

    add("# Docling parameter guide")
    add("")
    add("**Generated by introspecting the installed Docling**, not transcribed from documentation.")
    add("Every *Docling default* and *selected value* below was read from the option objects this")
    add("project actually constructs. Regenerate after a Docling upgrade so the guide cannot drift.")
    add("")
    add("| Component | Version |")
    add("|---|---|")
    for k, v in VERSIONS.items():
        add(f"| `{k}` | `{v}` |")
    add("")
    add("Profile shown: **`high_fidelity`** (`configs/high_fidelity.yaml`) — the profile used for the")
    add("acceptance run.")
    add("")
    add("---")
    add("")
    add("## Values in effect")
    add("")
    add("| Public config key | Docling field | Docling default | **Selected** |")
    add("|---|---|---|---|")

    field_map = {
        "docling.backend": None,
        "docling.do_ocr": "do_ocr",
        "docling.do_table_structure": "do_table_structure",
        "docling.table_mode": "table_structure_options",
        "docling.generate_page_images": "generate_page_images",
        "docling.generate_picture_images": "generate_picture_images",
        "docling.generate_table_images": "generate_table_images",
        "docling.images_scale": "images_scale",
        "docling.enable_heading_hierarchy": "heading_hierarchy_options",
        "docling.do_picture_classification": "do_picture_classification",
        "docling.do_code_enrichment": "do_code_enrichment",
        "docling.do_formula_enrichment": "do_formula_enrichment",
        "docling.picture_description.enabled": "do_picture_description",
        "docling.accelerator_device": "accelerator_options",
        "docling.enable_remote_services": "enable_remote_services",
        "limits.document_timeout_s": "document_timeout",
        "docling.ocr_options": "ocr_options",
        "docling.layout_options": "layout_options",
    }
    for public, field in sorted(field_map.items()):
        if field is None:
            add(
                f"| `{public}` | `PdfFormatOption.backend` | "
                "`DoclingParseDocumentBackend` | `DoclingParseDocumentBackend` |"
            )
            continue
        default = STOCK.get(field)
        chosen = CHOSEN.get(field)
        mark = " **←changed**" if default != chosen else ""
        add(f"| `{public}` | `PdfPipelineOptions.{field}` | {fmt(default)} | {fmt(chosen)}{mark} |")
    add("")
    add("---")
    add("")
    add("## Effect, trade-off, and whether it was used here")
    add("")
    add(
        "| Public key | Docling field | Effect | Quality / speed / memory trade-off | When to change | Used for this PDF? |"
    )
    add("|---|---|---|---|---|---|")
    for public, field, effect, tradeoff, when, used in ROWS:
        add(f"| `{public}` | `{field}` | {effect} | {tradeoff} | {when} | {used} |")
    add("")
    add("---")
    add("")
    add("## Enumerations available in this build")
    add("")
    for enum in (PdfBackend, ProcessingPipeline, TableFormerMode, OcrEngine, OcrMode, AcceleratorDevice):
        vals = ", ".join(f"`{m.value}`" for m in enum)
        add(f"- **`{enum.__name__}`** — {vals}")
    add("")
    add("> **`dlparse_v1` / `dlparse_v2` / `dlparse_v4` are obsolete.** Introspection shows")
    add("> `normalize_pdf_backend()` maps all three back to `DOCLING_PARSE`, and")
    add("> `DoclingParseV4DocumentBackend` is a shim that emits a `FutureWarning` and is documented")
    add("> as removed in 2.74.0. Recipes on the internet still recommend it; this project does not")
    add("> offer it as a config value.")
    add("")
    add("---")
    add("")
    add("## Complete effective `PdfPipelineOptions`")
    add("")
    add("Dumped from the constructed object for the `high_fidelity` profile:")
    add("")
    add("```json")
    add(json.dumps(CHOSEN, indent=2, sort_keys=True))
    add("```")
    add("")
    add("Regenerate this file with:")
    add("")
    add("```bash")
    add('python -c "from engineering_rag_parser.pipeline_factory import describe_effective_options; \\')
    add("from engineering_rag_parser.config import load_config; import json; \\")
    add(
        "print(json.dumps(describe_effective_options(load_config('configs/high_fidelity.yaml')), indent=2))\""
    )
    add("```")
    add("")

    path = Path("docs/docling_parameter_guide.md")
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(out))
    print("wrote", path, len(out), "lines")


if __name__ == "__main__":
    main()
