"""Rule: unmanaged EBS snapshot retention.

CUR shows snapshot storage cost per snapshot but not snapshot age. A reliable
CUR-only signal that retention is unmanaged is the ratio of snapshot spend to
live EBS volume spend: when snapshots cost more than half of the volumes they
protect, retention has almost certainly outgrown any real recovery need. The
estimate is conservative and flagged lower-confidence, since the precise
prunable set needs the snapshot age from the EC2 API (Phase 2 connector).
"""

from __future__ import annotations

import polars as pl

from ... import schema as S
from ...models import Category, Finding, Severity
from . import base

# Flag when snapshot spend exceeds this fraction of live-volume spend.
SNAPSHOT_TO_VOLUME_RATIO_THRESHOLD = 0.5
# Conservative share of snapshot spend a lifecycle policy typically reclaims.
PRUNABLE_FRACTION = 0.40


class SnapshotRetentionRule(base.Rule):
    rule_id = "ebs-snapshot-retention"
    title = "Tighten EBS snapshot retention"

    def evaluate(self, df: pl.DataFrame) -> list[Finding]:
        usage = base.usage_only(df)
        snapshots = usage.filter(pl.col(S.USAGE_TYPE).str.contains("EBS:SnapshotUsage"))
        volumes = usage.filter(pl.col(S.USAGE_TYPE).str.contains("EBS:VolumeUsage"))

        snapshot_cost = base.cost_of(snapshots)
        volume_cost = base.cost_of(volumes)
        if snapshot_cost <= 0 or volume_cost <= 0:
            return []

        ratio = snapshot_cost / volume_cost
        if ratio < SNAPSHOT_TO_VOLUME_RATIO_THRESHOLD:
            return []

        savings = round(snapshot_cost * PRUNABLE_FRACTION, 2)
        ratio_pct = f"{ratio:.0%}"
        threshold_pct = f"{SNAPSHOT_TO_VOLUME_RATIO_THRESHOLD:.0%}"
        ids, count = base.resource_sample(snapshots)
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                category=Category.WASTE,
                severity=self._cap_severity(base.severity_for(savings)),
                monthly_cost=snapshot_cost,
                estimated_monthly_savings=savings,
                resource_ids=ids,
                affected_resource_count=count,
                confidence=0.55,
                detail=(
                    f"Snapshot spend is ${snapshot_cost:,.0f}/mo against ${volume_cost:,.0f}/mo "
                    f"of live volumes ({ratio_pct} ratio), well above the ~{threshold_pct} "
                    f"point where retention is usually unmanaged. Pruning the long tail "
                    f"typically reclaims ~{int(PRUNABLE_FRACTION * 100)}% (~${savings:,.0f}/mo)."
                ),
                recommendation=(
                    "Apply a Data Lifecycle Manager policy (e.g. keep 7 daily / 4 "
                    "weekly) and delete snapshots orphaned from deleted volumes. "
                    "Confirm the prunable set against snapshot age before deleting."
                ),
            )
        ]

    # Lower-confidence estimate: keep it MEDIUM at most even if dollars are large.
    @staticmethod
    def _cap_severity(sev: Severity) -> Severity:
        return Severity.MEDIUM if sev == Severity.HIGH else sev
