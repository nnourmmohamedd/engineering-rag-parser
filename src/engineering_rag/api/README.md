# `api` — user/system entry points

## Today: the CLI

`cli.py` is the `engrag-parse` Typer application (console script:
`engrag-parse = "engineering_rag.api.cli:app"`). It is the *only* place that:

- configures logging (`engineering_rag.utils.logging.configure_logging`);
- calls into orchestration (`engineering_rag.pipelines.parsing_pipeline`);
- decides presentation (Rich tables/console output vs. `--json`).

Commands: `inspect`, `run`, `validate`, `show` — unchanged from the previous
package layout, including exit codes (`0` pass/pass-with-warnings, `1`
validation FAIL, `2` preflight rejection, `3` unexpected runtime failure).

## Future: an HTTP interface

Not implemented. When it exists, it belongs in this package
(e.g. `api/http.py` exposing a FastAPI app) and must call the same
`engineering_rag.pipelines.*` orchestration functions the CLI calls — never
reach into a service's internals directly, and never duplicate the CLI's
option-to-config translation logic.
