# `services/grounding`

Deterministic, post-generation validation of one parsed model answer against
the `ContextPackage` it was generated from.

## What these checks prove

- Every citation ID used inline (`[S1]`) or declared (`citations_used`,
  `supporting_evidence`) is one of the real, allow-listed IDs handed out for
  this context package — a citation marker embedded inside untrusted source
  text can never become a valid answer citation, because it was never
  assigned a real `SelectedSource.citation_id` in the first place.
- Every `supporting_evidence` quote is actually present (after documented
  normalization — Unicode NFKC, smart-quote/dash folding, whitespace
  collapse, casefold) in its cited source's `retrieval_text`.
- A non-refusal answer carries at least the configured minimum number of
  valid citations and at least one inline `[S<n>]` marker.

## What these checks do NOT prove

They do not mathematically prove that the answer's claim is semantically
entailed by the quoted text, and a `PASS` result is never described as
"fully hallucination-free." See
`docs/answering/SECURITY_AND_GROUNDING.md`.

## Status

- `PASS` — every configured hard check passed, no warnings.
- `PASS_WITH_WARNINGS` — no hard check failed, but a soft signal (citation
  coverage heuristic, a refusal that still carries citations) was raised.
- `FAIL` — a configured hard check failed (unknown citation, quote
  mismatch, missing citation on a non-refusal answer). The pipeline must
  never present a `FAIL` answer as trusted.

Depends only on `services/context_builder`'s `ContextPackage` type — never
on `services/answerer` or `clients/ollama`, so `services/answerer` can depend
on this package without a cycle.
