"""Tests that the production package is self-contained, importable in isolation,
and respects the service-oriented architecture's dependency direction.

Guards against the classic prototype regression: parsing logic drifting into the
notebook, a notebook-only dependency creeping into the runtime path, or a
service reaching sideways/upward into pipelines or the API layer.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path("src/engineering_rag")
NOTEBOOK = Path("notebooks/01_docling_exploration.ipynb")


def _module_paths(root: Path = SRC) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    """Every dotted module name imported by a file, `import`/`from` alike."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


class TestPackageIsSelfContained:
    def test_package_imports_without_notebook_or_cwd(self) -> None:
        """Importing must not depend on the repo working directory or notebook state."""
        result = subprocess.run(
            [sys.executable, "-c", "import engineering_rag.pipelines.parsing_pipeline; print('ok')"],
            capture_output=True,
            text=True,
            cwd=Path(sys.prefix).parent,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_no_notebook_only_dependencies_in_runtime(self) -> None:
        forbidden = {"IPython", "ipywidgets", "matplotlib", "google", "openai", "requests", "boto3"}
        offenders: list[str] = []
        for path in _module_paths():
            for name in _imports(path):
                if name.split(".")[0] in forbidden:
                    offenders.append(f"{path}: {name}")
        assert not offenders, f"notebook/network dependencies in runtime: {offenders}"

    def test_no_agpl_dependency_in_runtime(self) -> None:
        """PyMuPDF/fitz is AGPL-3.0 and must not appear anywhere in the package."""
        offenders = [
            str(p)
            for p in _module_paths()
            if "import fitz" in p.read_text(encoding="utf-8")
            or "import pymupdf" in p.read_text(encoding="utf-8").lower()
        ]
        assert not offenders, f"AGPL dependency present: {offenders}"

    def test_every_module_has_a_docstring(self) -> None:
        missing = [
            str(p)
            for p in _module_paths()
            if ast.get_docstring(ast.parse(p.read_text(encoding="utf-8"))) is None
        ]
        assert not missing, f"modules without a docstring: {missing}"

    def test_no_print_statements_in_runtime(self) -> None:
        """Production code logs; it does not print."""
        offenders: list[str] = []
        for path in _module_paths():
            if path.name == "cli.py":  # the CLI is the presentation layer
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    offenders.append(f"{path}:{node.lineno}")
        assert not offenders, f"print() in runtime code: {offenders}"

    def test_docling_conversion_imports_are_confined_to_the_parser_service(self) -> None:
        """The heavy `docling` conversion package (models, backends, OCR) must touch
        only the parser's own isolation layer — API churn there must not ripple
        into the chunker, which only ever reads the already-converted document.
        """
        allowed = {"converter.py", "inventory.py", "exporters.py", "structure.py", "visual.py"}
        offenders: list[str] = []
        for path in _module_paths():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if (
                    stripped.startswith("import docling.")
                    or stripped == "import docling"
                    or stripped.startswith("from docling.")
                    or stripped.startswith("from docling import")
                ):
                    if path.name not in allowed:
                        offenders.append(str(path))
                    break
        assert not offenders, (
            f"unexpected `docling` (conversion package) imports outside the parser isolation layer: {offenders}"
        )

    def test_docling_core_document_model_is_shared_but_never_the_conversion_package(self) -> None:
        """`docling_core` (the DoclingDocument model) is legitimately shared by both
        services/parser and services/chunker — only the *conversion* package
        (`docling`) is isolation-confined (see the check above).
        """
        for path in _module_paths(SRC / "services" / "chunker"):
            text = path.read_text(encoding="utf-8")
            assert "import docling.\n" not in text
            for line in text.splitlines():
                stripped = line.strip()
                assert not (stripped == "import docling" or stripped.startswith("from docling import")), (
                    f"{path} imports the heavy `docling` conversion package; the chunker must only ever "
                    "consume the already-converted DoclingDocument (docling_core), never convert a PDF itself"
                )

    def test_old_package_does_not_exist(self) -> None:
        """No duplicated parser implementation may remain under the pre-migration name."""
        assert not Path("src/engineering_rag_parser").exists()


class TestServiceArchitectureBoundaries:
    """Enforces the allowed dependency direction: api -> pipelines -> services -> utils."""

    def test_utils_do_not_import_services_pipelines_or_api(self) -> None:
        offenders = [
            f"{p}: {name}"
            for p in _module_paths(SRC / "utils")
            for name in _imports(p)
            if name.startswith(
                ("engineering_rag.services", "engineering_rag.pipelines", "engineering_rag.api")
            )
        ]
        assert not offenders, f"utils must not depend upward: {offenders}"

    def test_services_do_not_import_pipelines_or_api(self) -> None:
        offenders = [
            f"{p}: {name}"
            for p in _module_paths(SRC / "services")
            for name in _imports(p)
            if name.startswith(("engineering_rag.pipelines", "engineering_rag.api"))
        ]
        assert not offenders, f"a service must not depend on pipelines or api: {offenders}"

    def test_pipelines_do_not_import_api(self) -> None:
        offenders = [
            f"{p}: {name}"
            for p in _module_paths(SRC / "pipelines")
            for name in _imports(p)
            if name.startswith("engineering_rag.api")
        ]
        assert not offenders, f"a pipeline must not depend on api: {offenders}"

    def test_lower_tiers_do_not_import_the_chatbot(self) -> None:
        """`chatbot` is an api-tier consumer: nothing beneath it may depend on it."""
        offenders = [
            f"{p}: {name}"
            for tier in ("utils", "services", "pipelines", "databases", "clients", "prompts")
            for p in _module_paths(SRC / tier)
            for name in _imports(p)
            if name.startswith("engineering_rag.chatbot")
        ]
        assert not offenders, f"{offenders} depend upward on engineering_rag.chatbot"

    def test_chatbot_reuses_pipelines_rather_than_service_internals(self) -> None:
        """The chatbot must orchestrate existing pipelines, never re-implement a stage.

        Importing a *service* directly from the chatbot is how duplicate
        parsing/chunking/indexing logic starts: the pipeline entry points are
        the supported contract. Typed contracts (config/model/exception
        modules) are fine -- executing a stage yourself is not.
        """
        allowed_service_modules = {
            # Typed contracts and errors only; none of these execute a stage.
            "engineering_rag.services.parser.config",
            "engineering_rag.services.parser.models",
            "engineering_rag.services.parser.errors",
            "engineering_rag.services.chunker.config",
            "engineering_rag.services.retriever",
            "engineering_rag.services.retriever.errors",
            "engineering_rag.services.reranker",
        }
        offenders = [
            f"{p}: {name}"
            for p in _module_paths(SRC / "chatbot")
            for name in _imports(p)
            if name.startswith("engineering_rag.services.") and name not in allowed_service_modules
        ]
        assert not offenders, (
            f"the chatbot must call pipelines, not reach into service internals: {offenders}"
        )

    def test_no_circular_imports_across_top_level_packages(self) -> None:
        """A cycle would make at least one of these fail to import."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import engineering_rag.utils.logging, engineering_rag.utils.paths, "
                "engineering_rag.services.parser, engineering_rag.pipelines.parsing_pipeline, "
                "engineering_rag.api.cli; print('ok')",
            ],
            capture_output=True,
            text=True,
            cwd=Path(sys.prefix).parent,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_cli_entry_point_imports_and_is_callable(self) -> None:
        from engineering_rag.api.cli import app

        assert callable(app)

    def test_default_data_paths_are_correct(self) -> None:
        from engineering_rag.utils.paths import (
            default_chunker_output_root,
            default_input_root,
            default_output_root,
            default_parser_output_root,
        )

        assert default_input_root() == Path("data/input")
        assert default_output_root() == Path("data/output")
        assert default_parser_output_root() == Path("data/output/parser")
        assert default_chunker_output_root() == Path("data/output/chunker")

    def test_logging_is_configured_only_at_the_application_boundary(self) -> None:
        """`logging.basicConfig()` must appear nowhere outside `api/cli.py`."""
        offenders = [
            str(p)
            for p in _module_paths()
            if "logging.basicConfig(" in p.read_text(encoding="utf-8") and p.name != "cli.py"
        ]
        assert not offenders, f"logging.basicConfig() called outside the application boundary: {offenders}"

    def test_chunker_service_public_interface_imports(self) -> None:
        """The chunker milestone is implemented; its public interface must import cleanly."""
        from engineering_rag.services.chunker import (
            ChunkerConfig,
            ChunkerRequest,
            ChunkerResult,
            ChunkerService,
        )

        assert callable(ChunkerService)
        assert ChunkerConfig is not None
        assert ChunkerRequest is not None
        assert ChunkerResult is not None


@pytest.mark.skipif(not NOTEBOOK.is_file(), reason="notebook not present")
class TestNotebookIsAThinClient:
    def test_notebook_is_valid_json(self) -> None:
        json.loads(NOTEBOOK.read_text(encoding="utf-8"))

    def test_notebook_contains_no_parsing_implementation(self) -> None:
        """The notebook must call the package, never reimplement it."""
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
        )
        forbidden = ["DocumentConverter(", "PdfPipelineOptions(", "PdfFormatOption("]
        offenders = [token for token in forbidden if token in source]
        assert not offenders, (
            f"notebook reimplements pipeline construction ({offenders}); it must call engineering_rag instead"
        )

    def test_notebook_imports_the_package(self) -> None:
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
        )
        assert "engineering_rag" in source

    def test_notebook_outputs_are_cleared(self) -> None:
        """Committed notebooks must not carry document-derived output."""
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        with_output = [
            i
            for i, cell in enumerate(nb.get("cells", []))
            if cell.get("cell_type") == "code" and cell.get("outputs")
        ]
        assert not with_output, f"cells {with_output} carry stored output; clear before committing"


class TestConfigsAreValid:
    @pytest.mark.parametrize("name", ["default", "high_fidelity", "scanned", "auto"])
    def test_shipped_config_loads_and_hashes(self, name: str) -> None:
        from engineering_rag.services.parser.config import load_config

        path = Path("configs") / f"{name}.yaml"
        if not path.is_file():
            pytest.skip(f"{path} missing")
        cfg = load_config(path)
        assert cfg.config_hash()
        assert cfg.docling.enable_remote_services is False
