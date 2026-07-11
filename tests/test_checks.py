"""Tests for the quality checks module."""

from __future__ import annotations

from zscan.core.checks import CheckReport
from zscan.core.metadata import (
    ColumnStats,
    DataFileStats,
    SnapshotInfo,
    TableMetadata,
)
from zscan.core.rules import (
    CheckStatus,
    FileCountAnomalyRule,
    NullRateRule,
    RangeViolationRule,
    RowCountDriftRule,
)


def create_test_metadata(
    snapshots: list[SnapshotInfo] | None = None,
    data_files: list[DataFileStats] | None = None,
) -> TableMetadata:
    """Create test metadata with sample data.

    Args:
        snapshots: Optional list of snapshots.
        data_files: Optional list of data files.

    Returns:
        TableMetadata for testing.
    """
    return TableMetadata(
        table_name="test_table",
        location="/warehouse/test_table",
        current_snapshot_id=1,
        schema_fields=[],
        snapshots=snapshots or [],
        data_files=data_files or [],
    )


class TestRowCountDriftRule:
    """Tests for RowCountDriftRule."""

    def test_skips_with_single_snapshot(self: TestRowCountDriftRule) -> None:
        """Test that rule is skipped with insufficient snapshots."""
        rule = RowCountDriftRule(threshold_pct=20.0)
        metadata = create_test_metadata(
            snapshots=[SnapshotInfo(1, 1000, "append", {"total-records": "100"})],
        )
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.SKIPPED

    def test_detects_drift(self: TestRowCountDriftRule) -> None:
        """Test detection of row count drift."""
        rule = RowCountDriftRule(threshold_pct=20.0)
        metadata = create_test_metadata(
            snapshots=[
                SnapshotInfo(1, 1000, "append", {"total-records": "1000"}),
                SnapshotInfo(2, 2000, "append", {"total-records": "500"}),
            ],
        )
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.FAILED
        assert result.violation_count > 0

    def test_passes_within_threshold(self: TestRowCountDriftRule) -> None:
        """Test no violation when within threshold."""
        rule = RowCountDriftRule(threshold_pct=20.0)
        metadata = create_test_metadata(
            snapshots=[
                SnapshotInfo(1, 1000, "append", {"total-records": "1000"}),
                SnapshotInfo(2, 2000, "append", {"total-records": "1050"}),
            ],
        )
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.PASSED


class TestNullRateRule:
    """Tests for NullRateRule."""

    def test_skips_with_no_files(self: TestNullRateRule) -> None:
        """Test that rule is skipped with no data files."""
        rule = NullRateRule(default_threshold=0.1)
        metadata = create_test_metadata()
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.SKIPPED

    def test_detects_high_null_rate(self: TestNullRateRule) -> None:
        """Test detection of high null rates."""
        rule = NullRateRule(default_threshold=0.1)
        stats = ColumnStats(
            column_id=1,
            column_name="col1",
            value_count=100,
            null_count=50,  # 33% null rate
            nan_count=0,
            lower_bound=0,
            upper_bound=100,
        )
        df = DataFileStats(
            file_path="/data/file.parquet",
            file_format="PARQUET",
            record_count=150,
            file_size_bytes=1024,
            partition={},
            column_stats={"col1": stats},
        )
        metadata = create_test_metadata(data_files=[df])
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.FAILED


class TestRangeViolationRule:
    """Tests for RangeViolationRule."""

    def test_skips_with_no_files(self: TestRangeViolationRule) -> None:
        """Test that rule is skipped with no data files."""
        rule = RangeViolationRule(column_bounds={"col1": (0, 100)})
        metadata = create_test_metadata()
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.SKIPPED

    def test_detects_range_violation(self: TestRangeViolationRule) -> None:
        """Test detection of range violations."""
        rule = RangeViolationRule(column_bounds={"col1": (0, 100)})
        stats = ColumnStats(
            column_id=1,
            column_name="col1",
            value_count=100,
            null_count=0,
            nan_count=0,
            lower_bound=-10,  # Below expected minimum
            upper_bound=50,
        )
        df = DataFileStats(
            file_path="/data/file.parquet",
            file_format="PARQUET",
            record_count=100,
            file_size_bytes=1024,
            partition={},
            column_stats={"col1": stats},
        )
        metadata = create_test_metadata(data_files=[df])
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.FAILED


class TestFileCountAnomalyRule:
    """Tests for FileCountAnomalyRule."""

    def test_skips_with_single_snapshot(self: TestFileCountAnomalyRule) -> None:
        """Test that rule is skipped with insufficient snapshots."""
        rule = FileCountAnomalyRule()
        metadata = create_test_metadata(
            snapshots=[SnapshotInfo(1, 1000, "append", {"total-data-files": "5"})],
        )
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.SKIPPED

    def test_detects_spike(self: TestFileCountAnomalyRule) -> None:
        """Test detection of file count spike."""
        rule = FileCountAnomalyRule(max_increase_pct=100.0)
        metadata = create_test_metadata(
            snapshots=[
                SnapshotInfo(1, 1000, "append", {"total-data-files": "5"}),
                SnapshotInfo(2, 2000, "append", {"total-data-files": "20"}),
            ],
        )
        result = rule.evaluate(metadata)
        assert result.status == CheckStatus.FAILED


class TestCheckReport:
    """Tests for CheckReport."""

    def test_report_properties(self: TestCheckReport) -> None:
        """Test CheckReport properties."""
        report = CheckReport(
            table_name="test",
            results=[],
            total_violations=0,
            passed=True,
        )
        assert report.passed is True
        assert report.total_violations == 0
        assert report.failed_rules == []
        assert report.skipped_rules == []

    def test_report_to_dict(self: TestCheckReport) -> None:
        """Test CheckReport serialization."""
        report = CheckReport(
            table_name="test",
            results=[],
            total_violations=0,
            passed=True,
        )
        result = report.to_dict()
        assert result["table_name"] == "test"
        assert result["passed"] is True
