"""Data quality rule definitions and evaluation.

This module defines the Rule base class and concrete rule implementations
for zero-scan data quality checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zscan.core.metadata import TableMetadata


class Severity(StrEnum):
    """Severity level for rule violations.

    Attributes:
        INFO: Informational, no action needed.
        WARNING: Potential issue, review recommended.
        ERROR: Definite issue, action required.
        CRITICAL: Severe issue, immediate action required.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CheckStatus(StrEnum):
    """Status of a rule check execution.

    Attributes:
        PASSED: Check passed, no violations found.
        FAILED: Check failed, violations detected.
        SKIPPED: Check skipped due to insufficient data.
        ERROR: Check encountered an error during execution.
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class RuleViolation:
    """Represents a single violation of a data quality rule.

    Attributes:
        rule_name: Name of the violated rule.
        column: Column where violation occurred (if applicable).
        message: Human-readable description of the violation.
        severity: Severity level of the violation.
        details: Additional context about the violation.
    """

    rule_name: str
    column: str | None
    message: str
    severity: Severity
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleResult:
    """Result of executing a data quality rule.

    Attributes:
        rule_name: Name of the rule that was checked.
        status: Overall status of the check.
        violations: List of violations found.
        metadata: Additional metadata about the check execution.
    """

    rule_name: str
    status: CheckStatus
    violations: list[RuleViolation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self: RuleResult) -> bool:
        """Check if the rule passed without violations.

        Returns:
            True if status is PASSED, False otherwise.
        """
        return self.status == CheckStatus.PASSED

    @property
    def violation_count(self: RuleResult) -> int:
        """Return the number of violations found.

        Returns:
            Count of violations.
        """
        return len(self.violations)


class Rule(ABC):
    """Abstract base class for data quality rules.

    All zero-scan data quality rules must inherit from this class
    and implement the evaluate method.

    Attributes:
        name: Unique name for this rule.
        description: Human-readable description of what this rule checks.
        severity: Default severity for violations of this rule.
    """

    def __init__(
        self: Rule, name: str, description: str, severity: Severity = Severity.WARNING,
    ) -> None:
        """Initialize the rule.

        Args:
            name: Unique name for this rule.
            description: Human-readable description.
            severity: Default severity for violations.
        """
        self.name = name
        self.description = description
        self.severity = severity

    @abstractmethod
    def evaluate(self: Rule, metadata: TableMetadata) -> RuleResult:
        """Evaluate this rule against table metadata.

        Args:
            metadata: The table metadata to evaluate against.

        Returns:
            RuleResult containing the outcome of the check.
        """

    def __repr__(self: Rule) -> str:
        """Return string representation of the rule.

        Returns:
            String with rule name and severity.
        """
        return f"{self.__class__.__name__}(name='{self.name}', severity={self.severity})"


class RowCountDriftRule(Rule):
    """Detect significant changes in row count between snapshots.

    This rule compares the current snapshot's record count against
    historical snapshots to detect unexpected drops or spikes.

    Attributes:
        threshold_pct: Maximum allowed percentage change (default 20%).
    """

    def __init__(
        self: RowCountDriftRule,
        threshold_pct: float = 20.0,
        severity: Severity = Severity.WARNING,
    ) -> None:
        """Initialize the row count drift rule.

        Args:
            threshold_pct: Maximum allowed percentage change in row count.
            severity: Severity level for violations.
        """
        super().__init__(
            name="row_count_drift",
            description=f"Detect row count changes exceeding {threshold_pct}%",
            severity=severity,
        )
        self.threshold_pct = threshold_pct

    def evaluate(self: RowCountDriftRule, metadata: TableMetadata) -> RuleResult:
        """Evaluate row count drift across snapshots.

        Args:
            metadata: The table metadata containing snapshot history.

        Returns:
            RuleResult with drift violations if detected.
        """
        if len(metadata.snapshots) < 2:
            return RuleResult(
                rule_name=self.name,
                status=CheckStatus.SKIPPED,
                metadata={"reason": "Insufficient snapshots for comparison"},
            )

        violations = []
        snapshots = sorted(metadata.snapshots, key=lambda s: s.timestamp_ms)

        for i in range(1, len(snapshots)):
            prev_count = int(snapshots[i - 1].summary.get("total-records", 0))
            curr_count = int(snapshots[i].summary.get("total-records", 0))

            if prev_count == 0:
                continue

            change_pct = abs(curr_count - prev_count) / prev_count * 100

            if change_pct > self.threshold_pct:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=None,
                        message=(
                            f"Row count changed by {change_pct:.1f}% "
                            f"(snapshot {snapshots[i-1].snapshot_id} → "
                            f"{snapshots[i].snapshot_id})"
                        ),
                        severity=self.severity,
                        details={
                            "previous_count": prev_count,
                            "current_count": curr_count,
                            "change_pct": change_pct,
                            "snapshot_from": snapshots[i - 1].snapshot_id,
                            "snapshot_to": snapshots[i].snapshot_id,
                        },
                    ),
                )

        return RuleResult(
            rule_name=self.name,
            status=CheckStatus.FAILED if violations else CheckStatus.PASSED,
            violations=violations,
        )


class NullRateRule(Rule):
    """Check that null rates in columns don't exceed thresholds.

    This rule uses Iceberg metadata's null_value_counts to detect
    columns with excessive null values without scanning data.

    Attributes:
        column_thresholds: Mapping of column names to max null rates.
        default_threshold: Default max null rate if column not in mapping.
    """

    def __init__(
        self: NullRateRule,
        column_thresholds: dict[str, float] | None = None,
        default_threshold: float = 0.1,
        severity: Severity = Severity.WARNING,
    ) -> None:
        """Initialize the null rate rule.

        Args:
            column_thresholds: Per-column null rate thresholds (0.0 to 1.0).
            default_threshold: Default threshold for unlisted columns.
            severity: Severity level for violations.
        """
        super().__init__(
            name="null_rate_check",
            description="Check that null rates don't exceed thresholds",
            severity=severity,
        )
        self.column_thresholds = column_thresholds or {}
        self.default_threshold = default_threshold

    def evaluate(self: NullRateRule, metadata: TableMetadata) -> RuleResult:
        """Evaluate null rates across all data files.

        Args:
            metadata: The table metadata containing column statistics.

        Returns:
            RuleResult with null rate violations if detected.
        """
        if not metadata.data_files:
            return RuleResult(
                rule_name=self.name,
                status=CheckStatus.SKIPPED,
                metadata={"reason": "No data files found"},
            )

        # Aggregate null counts per column
        column_totals: dict[str, dict[str, int]] = {}

        for df in metadata.data_files:
            for col_name, stats in df.column_stats.items():
                if col_name not in column_totals:
                    column_totals[col_name] = {"nulls": 0, "total": 0}
                column_totals[col_name]["nulls"] += stats.null_count
                column_totals[col_name]["total"] += stats.value_count + stats.null_count

        violations = []
        for col_name, totals in column_totals.items():
            if totals["total"] == 0:
                continue

            null_rate = totals["nulls"] / totals["total"]
            threshold = self.column_thresholds.get(col_name, self.default_threshold)

            if null_rate > threshold:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=col_name,
                        message=(
                            f"Null rate {null_rate:.2%} exceeds threshold {threshold:.2%} "
                            f"in column '{col_name}'"
                        ),
                        severity=self.severity,
                        details={
                            "null_count": totals["nulls"],
                            "total_count": totals["total"],
                            "null_rate": null_rate,
                            "threshold": threshold,
                        },
                    ),
                )

        return RuleResult(
            rule_name=self.name,
            status=CheckStatus.FAILED if violations else CheckStatus.PASSED,
            violations=violations,
        )


class RangeViolationRule(Rule):
    """Check that column values stay within expected bounds.

    Uses Iceberg metadata's lower_bounds and upper_bounds to detect
    out-of-range values without scanning data files.

    Attributes:
        column_bounds: Mapping of column names to (min, max) tuples.
    """

    def __init__(
        self: RangeViolationRule,
        column_bounds: dict[str, tuple[float | None, float | None]],
        severity: Severity = Severity.ERROR,
    ) -> None:
        """Initialize the range violation rule.

        Args:
            column_bounds: Expected (min, max) bounds per column.
                Use None for unbounded (e.g., (0, None) for >= 0).
            severity: Severity level for violations.
        """
        super().__init__(
            name="range_violation",
            description="Check that values stay within expected bounds",
            severity=severity,
        )
        self.column_bounds = column_bounds

    def evaluate(self: RangeViolationRule, metadata: TableMetadata) -> RuleResult:
        """Evaluate value bounds against expected ranges.

        Args:
            metadata: The table metadata containing column statistics.

        Returns:
            RuleResult with range violations if detected.
        """
        if not metadata.data_files:
            return RuleResult(
                rule_name=self.name,
                status=CheckStatus.SKIPPED,
                metadata={"reason": "No data files found"},
            )

        violations = []

        for col_name, (expected_min, expected_max) in self.column_bounds.items():
            # Aggregate bounds across all files
            actual_min = None
            actual_max = None

            for df in metadata.data_files:
                if col_name in df.column_stats:
                    stats = df.column_stats[col_name]
                    # Skip if bounds are bytes (binary encoded)
                    if isinstance(stats.lower_bound, bytes) or isinstance(stats.upper_bound, bytes):
                        continue
                    if stats.lower_bound is not None:
                        actual_min = (
                            stats.lower_bound
                            if actual_min is None
                            else min(actual_min, stats.lower_bound)
                        )
                    if stats.upper_bound is not None:
                        actual_max = (
                            stats.upper_bound
                            if actual_max is None
                            else max(actual_max, stats.upper_bound)
                        )

            if actual_min is None and actual_max is None:
                continue

            # Check lower bound violation
            if expected_min is not None and actual_min is not None and actual_min < expected_min:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=col_name,
                        message=(
                            f"Column '{col_name}' has values below minimum: "
                            f"{actual_min} < {expected_min}"
                        ),
                        severity=self.severity,
                        details={
                            "actual_min": actual_min,
                            "expected_min": expected_min,
                            "actual_max": actual_max,
                        },
                    ),
                )

            # Check upper bound violation
            if expected_max is not None and actual_max is not None and actual_max > expected_max:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=col_name,
                        message=(
                            f"Column '{col_name}' has values above maximum: "
                            f"{actual_max} > {expected_max}"
                        ),
                        severity=self.severity,
                        details={
                            "actual_min": actual_min,
                            "actual_max": actual_max,
                            "expected_max": expected_max,
                        },
                    ),
                )

        return RuleResult(
            rule_name=self.name,
            status=CheckStatus.FAILED if violations else CheckStatus.PASSED,
            violations=violations,
        )


class FileCountAnomalyRule(Rule):
    """Detect anomalies in the number of data files per snapshot.

    Sudden increases in file count may indicate write failures or
    lack of compaction. Sudden decreases may indicate data loss.

    Attributes:
        max_increase_pct: Maximum allowed percentage increase in file count.
        max_decrease_pct: Maximum allowed percentage decrease in file count.
    """

    def __init__(
        self: FileCountAnomalyRule,
        max_increase_pct: float = 100.0,
        max_decrease_pct: float = 50.0,
        severity: Severity = Severity.WARNING,
    ) -> None:
        """Initialize the file count anomaly rule.

        Args:
            max_increase_pct: Max allowed % increase in file count.
            max_decrease_pct: Max allowed % decrease in file count.
            severity: Severity level for violations.
        """
        super().__init__(
            name="file_count_anomaly",
            description="Detect anomalies in data file counts",
            severity=severity,
        )
        self.max_increase_pct = max_increase_pct
        self.max_decrease_pct = max_decrease_pct

    def evaluate(self: FileCountAnomalyRule, metadata: TableMetadata) -> RuleResult:
        """Evaluate file count trends across snapshots.

        Args:
            metadata: The table metadata containing snapshot history.

        Returns:
            RuleResult with file count anomalies if detected.
        """
        if len(metadata.snapshots) < 2:
            return RuleResult(
                rule_name=self.name,
                status=CheckStatus.SKIPPED,
                metadata={"reason": "Insufficient snapshots for comparison"},
            )

        violations = []
        snapshots = sorted(metadata.snapshots, key=lambda s: s.timestamp_ms)

        for i in range(1, len(snapshots)):
            prev_count = int(snapshots[i - 1].summary.get("total-data-files", 0))
            curr_count = int(snapshots[i].summary.get("total-data-files", 0))

            if prev_count == 0:
                continue

            change_pct = (curr_count - prev_count) / prev_count * 100

            if change_pct > self.max_increase_pct:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=None,
                        message=(
                            f"File count increased by {change_pct:.1f}% "
                            f"(snapshot {snapshots[i-1].snapshot_id} → "
                            f"{snapshots[i].snapshot_id})"
                        ),
                        severity=self.severity,
                        details={
                            "previous_count": prev_count,
                            "current_count": curr_count,
                            "change_pct": change_pct,
                        },
                    ),
                )
            elif change_pct < -self.max_decrease_pct:
                violations.append(
                    RuleViolation(
                        rule_name=self.name,
                        column=None,
                        message=(
                            f"File count decreased by {abs(change_pct):.1f}% "
                            f"(snapshot {snapshots[i-1].snapshot_id} → "
                            f"{snapshots[i].snapshot_id})"
                        ),
                        severity=self.severity,
                        details={
                            "previous_count": prev_count,
                            "current_count": curr_count,
                            "change_pct": change_pct,
                        },
                    ),
                )

        return RuleResult(
            rule_name=self.name,
            status=CheckStatus.FAILED if violations else CheckStatus.PASSED,
            violations=violations,
        )
