"""Tests that the production package is self-contained and importable in isolation.

Guards against the classic prototype regression: parsing logic drifting into the
notebook, or a notebook-only dependency creeping into the runtime path.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path("src/engineering_rag_parser")
NOTEBOOK = Path("notebooks/01_docling_exploration.ipynb")


def _module_paths() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


class TestPackageIsSelfContained:
    def test_package_imports_without_notebook_or_cwd(self) -> None:
        """Importing must not depend on the repo working directory or notebook state."""
        result = subprocess.run(
            [sys.executable, "-c", "import engineering_rag_parser.pipeline; print('ok')"],
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
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in forbidden:
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

    def test_docling_imports_are_confined(self) -> None:
        """Docling API churn must touch only the modules designed to absorb it."""
        allowed = {"pipeline_factory.py", "parser.py", "exporters.py", "structure.py", "visual.py"}
        offenders: list[str] = []
        for path in _module_paths():
            text = path.read_text(encoding="utf-8")
            if ("import docling" in text or "from docling" in text) and path.name not in allowed:
                offenders.append(str(path))
        assert not offenders, f"unexpected Docling imports outside the isolation layer: {offenders}"


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
            f"notebook reimplements pipeline construction ({offenders}); it must call "
            "engineering_rag_parser instead"
        )

    def test_notebook_imports_the_package(self) -> None:
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
        )
        assert "engineering_rag_parser" in source

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
        from engineering_rag_parser.config import load_config

        path = Path("configs") / f"{name}.yaml"
        if not path.is_file():
            pytest.skip(f"{path} missing")
        cfg = load_config(path)
        assert cfg.config_hash()
        assert cfg.docling.enable_remote_services is False
