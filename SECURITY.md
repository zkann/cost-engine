# Security & trust model

`cost-engine` is a library and CLI that analyzes cost data. This document
states what it does and does not do, so you can reason about running it on your
own data and about depending on it from another service.

## What the engine does

- Reads a CUR file (parquet/CSV) from local disk, or generates synthetic data.
- Computes aggregates and runs rule checks. Pure, in-memory, deterministic.
- Writes a report to stdout or a file you name.

## What the engine does not do

- **No server, no listener, no inbound network.** There is nothing to connect to.
- **No secret storage.** It never writes credentials to disk. The only
  credential it touches is `ANTHROPIC_API_KEY` from the environment, and only if
  you opt into the LLM summary. The **CLI** convenience-loads a `.env` from the
  current directory (real environment variables win); the **library** never
  reads `.env` or any file for credentials, so a service embedding
  `cost_engine`, like the sandboxed OpsCenter worker, cannot have secrets
  resurrected from disk.
- **No outbound calls during analysis.** The only network call in the codebase is
  the optional Claude summary. With no key set, even that is skipped. Parsing and
  analyzing a CUR makes zero network requests.
- **No `eval` / `exec` / `pickle` / `yaml.load` / shell-out.** Input is parsed as
  data, never executed.

## Running it on your own AWS data

When you point the tool at a CUR you exported, the file stays on your machine.
For the real AWS connectors (Phase 2), the engine uses the standard boto3
credential chain (your env, profile, or instance role). It does not ask for,
store, or transmit keys. Grant a read-only billing/Cost Explorer policy and
nothing more.

## Depending on cost-engine from a service (important)

If you import `cost-engine` into a web app or worker, you are running its code
**in your process, with your privileges, on your data.** A bug in the engine or
in a transitive dependency (polars, pyarrow, pydantic) becomes a bug in your
service. Treat it like any dependency that parses untrusted input:

1. **Isolate it.** Run CUR parsing/analysis in a sandboxed worker: a separate
   process or container with memory/CPU/time limits, **network egress
   disabled**, and an environment that holds **no database, cloud, or session
   secrets**. If a parser is ever exploited by a crafted file, it lands somewhere
   with nothing to steal and nowhere to send it.
2. **Validate before you hand it over.** Enforce file size, row count, content
   type, and a schema check at your trust boundary, not inside the engine.
3. **Pin by version and hash.** Depend on a tagged release or a hashed lockfile
   entry, never a moving branch. Run `pip-audit` / Dependabot so a new CVE is
   surfaced before you upgrade.
4. **Skip the LLM summary in multi-tenant paths** (`use_llm=False`) so report
   data can't drive an outbound model call from inside your service, or give it a
   scoped key in the isolated worker.

The hosted OpsCenter app applies all four. See its repository's architecture
notes for the worker design.

## Reporting a vulnerability

Email zak@zakkann.com. Please do not open a public issue for a security report.
