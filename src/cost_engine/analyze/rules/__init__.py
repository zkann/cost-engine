"""Rule registry. To add a rule, write the class and append it to ``ALL_RULES``."""

from __future__ import annotations

from .base import Rule
from .data_transfer import DataTransferRule
from .gp2_to_gp3 import Gp2ToGp3Rule
from .idle_elastic_ip import IdleElasticIpRule
from .rds_reserved import RdsReservedCoverageRule
from .savings_plan_coverage import SavingsPlanCoverageRule
from .snapshot_retention import SnapshotRetentionRule
from .untagged_spend import UntaggedSpendRule

#: Every rule the engine runs, in a stable order.
ALL_RULES: list[Rule] = [
    IdleElasticIpRule(),
    Gp2ToGp3Rule(),
    SnapshotRetentionRule(),
    SavingsPlanCoverageRule(),
    RdsReservedCoverageRule(),
    DataTransferRule(),
    UntaggedSpendRule(),
]

__all__ = [
    "ALL_RULES",
    "Rule",
    "DataTransferRule",
    "Gp2ToGp3Rule",
    "IdleElasticIpRule",
    "RdsReservedCoverageRule",
    "SavingsPlanCoverageRule",
    "SnapshotRetentionRule",
    "UntaggedSpendRule",
]
