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

uv run cost-engine demo     # analyze the built-in synthetic account
```

`uv run` finds the project's virtualenv without activating it. If you prefer to
call `cost-engine` directly, activate first with `source .venv/bin/activate`. The
`s3` and `cost-explorer` commands also need the AWS extra: `uv pip install -e
'.[aws]'`.

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

### Getting a CUR file

A Cost & Usage Report isn't on by default. You enable it once, and AWS delivers
it to an S3 bucket on a schedule.

1. In the AWS console, open **Billing and Cost Management -> Data Exports** (older
   accounts call it **Cost & Usage Reports**). Create an export to an S3 bucket
   you own, with **Parquet** output (recommended) or CSV. Turn on the resource
   IDs and tags options so the resource-level rules have data to work with.
2. Wait for the first delivery (usually within 24 hours; it refreshes a few times
   a day after that).
3. Download the latest object from the export's S3 prefix and point the tool at
   it:

```bash
aws s3 cp s3://your-cur-bucket/path/to/latest.parquet ./my-cur.parquet
cost-engine report --input my-cur.parquet
cost-engine report --input my-cur.parquet --format md   --out report.md
cost-engine report --input my-cur.parquet --format json --out report.json
```

If you already query a CUR through Athena, an `UNLOAD ... TO 's3://...' FORMAT
PARQUET` of a single month works just as well.

**A note on column names.** The loader accepts either the raw export spelling
(`lineItem/UnblendedCost`) or the Athena/Glue-normalized one
(`line_item_unblended_cost`); it normalizes both. Only a small core set is
required (period, account, usage type, line-item type, cost). Optional columns
vary by CUR (tags are opt-in, `product`/`resource_tags` are nested in CUR 2.0),
so a missing one is filled rather than rejected: the service name falls back to
the product code, and rules that depend on an absent column simply don't fire,
with a note saying so. The full schema is in
[`schema.py`](src/cost_engine/schema.py).

A local file stays on your machine. `cost-engine` makes no network calls to
analyze it. See [SECURITY.md](SECURITY.md) for the full trust model.

### Or pull from AWS directly

With the AWS extra installed (`pip install 'cost-engine[aws]'`) and a read-only
credential on the standard boto3 chain, the tool fetches the data for you.

```bash
# Full fidelity: read the CUR under an S3 prefix and analyze it.
cost-engine s3 --bucket your-cur-bucket --prefix cost_report
cost-engine s3 --bucket your-cur-bucket --prefix cost_report --month 2026-04
cost-engine s3 --bucket your-cur-bucket --key path/to/exact-file.parquet

# Fast top-line: pull from the Cost Explorer API (no CUR setup needed).
cost-engine cost-explorer                                  # the last complete month
cost-engine cost-explorer --start 2026-05-01 --end 2026-06-01
```

Both default to the **most recent complete calendar month**, so the `$/mo` figure
reflects a full month, not a partial current one. AWS keeps rewriting the
in-progress month's CUR, so `s3` reads the billing period from the object path
rather than picking the newest file. Override with `--month YYYY-MM`, or
`--latest` for the current partial month; `cost-explorer` takes `--start`/`--end`
(end exclusive).

Use **`s3`** for the full picture: it reads the line-item CUR, so every rule and
breakdown works. **`cost-explorer`** is the quick path with no setup, but the API
returns cost by service and usage type only, with no resource IDs, tags, or
purchase term, so the untagged-spend and Savings Plan coverage rules are skipped
on that source. A read-only billing/Cost Explorer policy is all either needs.

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
uv run pytest        # 39 tests
uv run ruff check src tests
```

Adding a rule is one file plus one line in `analyze/rules/__init__.py`. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT. Built by [Zak Kann](https://zakkann.com).
