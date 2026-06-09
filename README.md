# cost-engine

Find dollar-quantified AWS savings from a Cost & Usage Report. `cost-engine`
reads CUR data, runs a set of FinOps rules, and prints a prioritized report:
what you spend, where it goes, and what to cut first, with the math behind every
number.

It runs offline on a built-in synthetic account, so you can try it in ten
seconds with no AWS access and no credentials.

```
ingest  ->  aggregate  ->  rules engine  ->  report (+ optional LLM summary)
```

## Quickstart

```bash
git clone https://github.com/zkann/cost-engine
cd cost-engine
uv venv && uv pip install -e .

cost-engine demo            # analyze the built-in synthetic account
```

Output (synthetic data):

```
AWS spend May 2026: $41,127/mo
Recoverable: $6,185/mo (15%, $74,225/yr)

Pri    Opportunity                                   Save/mo   Save/yr  Conf
HIGH   Cover steady on-demand compute (Savings Plan)  $2,570   $30,845   70%
MED    Review NAT and cross-AZ data-transfer spend    $1,416   $16,992   50%
MED    Tighten EBS snapshot retention                 $1,332   $15,984   55%
MED    Migrate gp2 EBS volumes to gp3                    $640    $7,680   95%
LOW    Release idle Elastic IP addresses                $227    $2,724   97%
INFO   Untagged spend can't be allocated                  -         -    90%
```

## Run it on your own data

Export your CUR to parquet or CSV (Athena `UNLOAD`, or an S3 CUR export) and
point the tool at the file:

```bash
cost-engine report --input my-cur.parquet
cost-engine report --input my-cur.parquet --format md  --out report.md
cost-engine report --input my-cur.parquet --format json --out report.json
```

The file stays on your machine. `cost-engine` makes no network calls to analyze
it. See [SECURITY.md](SECURITY.md) for the full trust model.

## What it checks

Each rule is a small, independent check that returns a current monthly cost and
an estimated monthly saving. The estimate's assumption is stated in the finding,
so no number is a black box.

| Rule | Category | Basis |
|---|---|---|
| Idle Elastic IPs | waste | `ElasticIP:IdleAddress` usage type, 100% recoverable |
| gp2 to gp3 migration | rightsizing | gp3 lists ~20% cheaper per GB-month |
| Snapshot retention | waste | snapshot spend vs live-volume spend ratio |
| Savings Plan coverage | commitment | on-demand vs committed compute, ~27% SP discount |
| NAT / cross-AZ transfer | data transfer | NAT + regional-transfer usage types |
| Untagged spend | governance | spend with no `team` tag, can't be allocated |

Every check is derivable from columns AWS actually emits in a CUR. Nothing
invents a signal that wouldn't exist in production data.

## Optional: LLM executive summary

With `ANTHROPIC_API_KEY` set, the report opens with a short Claude-written
summary. Without a key, a deterministic template fills the same slot, so the LLM
is polish, not a dependency. The model defaults to Haiku (the cheapest tier);
a cost tool should practice what it preaches.

```bash
uv pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-...
cost-engine demo
```

## Develop

```bash
uv pip install -e ".[dev]"
uv run pytest        # 31 tests
uv run ruff check src tests
```

Adding a rule is one file plus one line in `analyze/rules/__init__.py`. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT. Built by [Zak Kann](https://zakkann.com).
