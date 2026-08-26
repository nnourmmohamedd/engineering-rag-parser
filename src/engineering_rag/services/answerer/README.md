# `services/answerer`

`GroundedAnswerService.answer(query, context) -> tuple[AnswerResponse, AnswerTrace]`:
builds the
prompt from `prompts/answering`, calls the injected
`clients.ollama.interface.LLMClient` (never `OllamaHTTPClient` directly),
parses the structured draft, runs `services/grounding` validation, and
applies refusal/repair rules. Never imports `chromadb`.

## Status resolution

| Condition | `status` |
|---|---|
| No selected sources in the `ContextPackage` | `insufficient_evidence` (pre-generation, no LLM call) |
| Model output never parses as valid JSON matching the schema (after the one allowed repair) | `generation_failed` |
| Grounding validation returns `FAIL` (after the one allowed repair) | `validation_failed` |
| Parsed, grounding not `FAIL`, model declared `insufficient_evidence: true` | `insufficient_evidence` |
| Parsed, grounding not `FAIL`, model answered | `answered` |

An `answered` status is never returned for a draft whose grounding
validation failed — see `_resolve_status`.

`AnswerTrace` carries the exact final prompt and raw/parsed model output for
artifact writing (`prompt_manifest.json`, `answer_draft.json`) — it is not
part of the stable `AnswerResponse` contract and is never surfaced in normal
CLI output. It never contains hidden reasoning: the model runs with
`think: false`, so there is no chain-of-thought to capture.

## One repair attempt, total

`allow_single_repair` (default `true`) grants **one** repair attempt per
`answer()` call, shared across both failure classes it may cover: malformed
JSON / missing schema fields, and a grounding `FAIL` (unknown citation,
missing citation, quote mismatch). It is never spent twice and never used to
retry a connection/timeout error from the LLM client — those are
infrastructure failures, not something re-prompting the model can fix.
