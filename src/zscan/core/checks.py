"""Quality check orchestration and reporting.

This module provides the QualityChecker class which orchestrates
running multiple data quality rules against table metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table as RichTable

from zscan.core.rules import (
    CheckStatus,
    FileCountAnomalyRule,
    NullRateRule,
    RowCountDriftRule,
    Rule,
    RuleResult,
)

if TYPE_CHECKING:
    from zscan.core.metadata import MetadataExtractor, TableMetadata


@dataclass(frozen=True)
class CheckReport:
    """Complete report from running all quality checks.

    Attributes:
        table_name: Name of the checked table.
        results: List of results from each rule.
        total_violations: Total number of violations across all rules.
        passed: Whether all checks passed.
    """

    table_name: str
    results: list[RuleResult]
    total_violations: int
    passed: bool

    @property
    def failed_rules(self: CheckReport) -> list[RuleResult]:
        """Return results that failed.

        Returns:
            List of RuleResult with FAILED status.
        """
        return [r for r in self.results if r.status == CheckStatus.FAILED]

    @property
    def skipped_rules(self: CheckReport) -> list[RuleResult]:
        """Return results that were skipped.

        Returns:
            List of RuleResult with SKIPPED status.
        """
        return [r for r in self.results if r.status == CheckStatus.SKIPPED]

    def to_dict(self: CheckReport) -> dict[str, Any]:
        """Convert report to dictionary.

        Returns:
            Dictionary representation of the report.
        """
        return {
            "table_name": self.table_name,
            "passed": self.passed,
            "total_violations": self.total_violations,
            "results": [
                {
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "violations": [
                        {
                            "column": v.column,
                            "message": v.message,
                            "severity": v.severity.value,
                            "details": v.details,
                        }
                        for v in r.violations
                    ],
                }
                for r in self.results
            ],
        }


class QualityChecker:
    """Orchestrates data quality checks against Iceberg table metadata.

    This class manages a collection of rules and executes them against
    table metadata extracted without scanning data files.

    Attributes:
        extractor: The MetadataExtractor for reading table metadata.
        rules: List of rules to evaluate.
    """

    def __init__(
        self: QualityChecker,
        extractor: MetadataExtractor,
        rules: list[Rule] | None = None,
    ) -> None:
        """Initialize the QualityChecker.

        Args:
            extractor: MetadataExtractor for reading Iceberg metadata.
            rules: List of rules to evaluate. If None, uses defaults.
        """
        self.extractor = extractor
        self.rules = rules or self._default_rules()

    def _default_rules(self: QualityChecker) -> list[Rule]:
        """Return the default set of quality rules.

        Returns:
            List of default Rule instances.
        """
        return [
            RowCountDriftRule(threshold_pct=20.0),
            NullRateRule(default_threshold=0.1),
            FileCountAnomalyRule(),
        ]

    def add_rule(self: QualityChecker, rule: Rule) -> None:
        """Add a rule to the checker.

        Args:
            rule: Rule instance to add.
        """
        self.rules.append(rule)

    def run_checks(
        self: QualityChecker, table_name: str, metadata: TableMetadata | None = None,
    ) -> CheckReport:
        """Run all quality checks against a table.

        Args:
            table_name: Fully qualified table name.
            metadata: Optional pre-fetched metadata. If None, extracts fresh.

        Returns:
            CheckReport with results from all rules.
        """
        if metadata is None:
            metadata = self.extractor.get_table_metadata(table_name)

        results = []
        for rule in self.rules:
            result = rule.evaluate(metadata)
            results.append(result)

        total_violations = sum(r.violation_count for r in results)
        all_passed = all(
            r.status in (CheckStatus.PASSED, CheckStatus.SKIPPED) for r in results
        )

        return CheckReport(
            table_name=table_name,
            results=results,
            total_violations=total_violations,
            passed=all_passed,
        )

    def run_checks_with_custom_rules(
        self: QualityChecker,
        table_name: str,
        custom_rules: list[Rule],
        metadata: TableMetadata | None = None,
    ) -> CheckReport:
        """Run checks with both default and custom rules.

        Args:
            table_name: Fully qualified table name.
            custom_rules: Additional rules to run.
            metadata: Optional pre-fetched metadata.

        Returns:
            CheckReport with combined results.
        """
        original_rules = self.rules.copy()
        self.rules = original_rules + custom_rules
        try:
            return self.run_checks(table_name, metadata)
        finally:
            self.rules = original_rules


def print_report(report: CheckReport, console: Console | None = None) -> None:
    """Print a formatted quality check report to console.

    Args:
        report: The CheckReport to display.
        console: Optional Rich Console instance.
    """
    if console is None:
        console = Console()

    console.print()
    console.rule(f"[bold]Data Quality Report: {report.table_name}[/bold]")
    console.print()

    # Summary
    status_color = "green" if report.passed else "red"
    status_text = "PASSED" if report.passed else "FAILED"
    console.print(f"Overall Status: [{status_color}]{status_text}[/{status_color}]")
    console.print(f"Total Violations: {report.total_violations}")
    console.print()

    # Results table
    table = RichTable(title="Rule Results")
    table.add_column("Rule", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Violations", justify="right")
    table.add_column("Details")

    for result in report.results:
        status_style = {
            CheckStatus.PASSED: "green",
            CheckStatus.FAILED: "red",
            CheckStatus.SKIPPED: "yellow",
            CheckStatus.ERROR: "red bold",
        }.get(result.status, "white")

        details = ""
        if result.violations:
            details = "\n".join(v.message for v in result.violations[:3])
            if len(result.violations) > 3:
                details += f"\n... and {len(result.violations) - 3} more"

        table.add_row(
            result.rule_name,
            f"[{status_style}]{result.status.value}[/{status_style}]",
            str(result.violation_count),
            details,
        )

    console.print(table)
    console.print()
