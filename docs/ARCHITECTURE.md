# Architecture

```
                 +------------------+
   CUR file /    |     ingest       |  synthetic generator | parquet/CSV loader
   synthetic --> |  -> DataFrame    |  | (Phase 2) Cost Explorer / S3 CUR
                 +--------+---------+
                          |  one polars.DataFrame, schema in schema.py
                          v
                 +------------------+
                 |    aggregate     |  cost by service / account / team / region
                 +--------+---------+
                          v
                 +------------------+
                 |   rules engine   |  each rule -> Finding(cost, est. saving, why)
                 +--------+---------+
                          v
                 +------------------+
                 |     report       |  JSON / markdown  (+ optional LLM summary)
                 +------------------+
```

Every stage speaks one contract: the columnar dataset defined in
`schema.py`, named to match real AWS CUR columns. Ingestion sources are
interchangeable behind it; the synthetic generator and a real CUR loader produce
the same frame, so the rules never know or care where the data came from.

## Layout

| Path | Responsibility |
|---|---|
| `schema.py` | Canonical column names and dtypes (mirrors AWS CUR) |
| `models.py` | Result types: `Finding`, `Breakdown`, `Report` (pydantic) |
| `ingest/` | `synthetic` generator, `load` for parquet/CSV (`cur`/`cost_explorer` in Phase 2) |
| `analyze/aggregate.py` | Cost breakdowns by dimension |
| `analyze/rules/` | One file per rule; `__init__.py` is the registry |
| `analyze/engine.py` | Run all rules, assemble the `Report` |
| `report/summarize.py` | Optional Claude summary + deterministic fallback |
| `report/render.py` | JSON and markdown output |
| `cli.py` | `demo`, `report`, `gen-sample` |

## Adding a rule

1. Add `analyze/rules/my_rule.py` with a class subclassing `base.Rule`,
   implementing `evaluate(df) -> list[Finding]`.
2. State the dollar assumption in the finding's `detail`. No magic numbers
   without a stated basis.
3. Append an instance to `ALL_RULES` in `analyze/rules/__init__.py`.
4. Add a test: it fires with the expected dollars on synthetic data, and stays
   quiet on `clean_df`.

## Why this package is safe to depend on

The engine is deliberately a pure, offline library so a service can run it on
untrusted input without inheriting a large attack surface:

- No inbound network, no server.
- No `eval` / `exec` / `pickle` / `yaml.load` / shell-out. Input is data.
- The only outbound call is the opt-in Claude summary, skipped without a key.
- Deterministic given inputs; no hidden global state.

A consuming service still owns the trust boundary for the **inputs** it feeds in.
The split between this public engine and the private OpsCenter FinOps app is documented
below.

## The public / private boundary

This repository is public. The hosted web app (auth, multi-tenant storage,
dashboards, deploy config, secrets) lives in a separate **private** repository
and depends on this package. Two rules keep the boundary safe:

- **One-way dependency.** The app imports the engine; the engine never imports
  the app. Nothing about the app's routes, auth, or schema can leak through this
  code, because none of it is here.
- **Separate git histories.** This repo was initialized fresh. No private commit,
  config, or secret has ever been in its history, so none can be recovered from
  it.

Disclosure is only one direction of risk. The other, **the engine running inside
the app**, is handled on the app side by sandboxing analysis in a network-isolated,
secret-free worker, pinning this dependency by version and hash, and auditing it
in CI. See `SECURITY.md` ("Depending on cost-engine from a service") for the full
checklist.
```
  app  ──imports──▶  cost-engine        (trust flows this way; app sandboxes it)
  app  ──does NOT────  expose routes/secrets to this repo
```
