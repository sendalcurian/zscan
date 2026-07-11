"""Tests for the metadata extraction module."""

from __future__ import annotations

import pytest

from zscan.core.metadata import (
    ColumnStats,
    DataFileStats,
    MetadataExtractor,
    SnapshotInfo,
    TableMetadata,
)


class TestColumnStats:
    """Tests for ColumnStats dataclass."""

    def test_column_stats_creation(self: TestColumnStats) -> None:
        """Test creating a ColumnStats instance."""
        stats = ColumnStats(
            column_id=1,
            column_name="test_col",
            value_count=100,
            null_count=5,
            nan_count=0,
            lower_bound=0,
            upper_bound=100,
        )
        assert stats.column_id == 1
        assert stats.column_name == "test_col"
        assert stats.value_count == 100
        assert stats.null_count == 5

    def test_column_stats_immutability(self: TestColumnStats) -> None:
        """Test that ColumnStats is immutable."""
        stats = ColumnStats(
            column_id=1,
            column_name="test",
            value_count=10,
            null_count=0,
            nan_count=0,
            lower_bound=None,
            upper_bound=None,
        )
        with pytest.raises(AttributeError):
            stats.value_count = 20


class TestDataFileStats:
    """Tests for DataFileStats dataclass."""

    def test_data_file_stats_creation(self: TestDataFileStats) -> None:
        """Test creating a DataFileStats instance."""
        stats = DataFileStats(
            file_path="/data/file1.parquet",
            file_format="PARQUET",
            record_count=1000,
            file_size_bytes=102400,
            partition={},
        )
        assert stats.record_count == 1000
        assert stats.file_format == "PARQUET"
        assert stats.column_stats == {}


class TestSnapshotInfo:
    """Tests for SnapshotInfo dataclass."""

    def test_snapshot_info_creation(self: TestSnapshotInfo) -> None:
        """Test creating a SnapshotInfo instance."""
        snap = SnapshotInfo(
            snapshot_id=123456789,
            timestamp_ms=1700000000000,
            operation="append",
            summary={"total-records": "1000"},
        )
        assert snap.snapshot_id == 123456789
        assert snap.operation == "append"


class TestTableMetadata:
    """Tests for TableMetadata dataclass."""

    def test_table_metadata_creation(self: TestTableMetadata) -> None:
        """Test creating a TableMetadata instance."""
        metadata = TableMetadata(
            table_name="test_table",
            location="/warehouse/test_table",
            current_snapshot_id=123,
            schema_fields=[{"id": 1, "name": "col1", "type": "string"}],
            snapshots=[],
            data_files=[],
        )
        assert metadata.table_name == "test_table"
        assert metadata.current_snapshot_id == 123


class TestMetadataExtractor:
    """Tests for MetadataExtractor class."""

    def test_extractor_init(self: TestMetadataExtractor, warehouse_path) -> None:
        """Test MetadataExtractor initialization."""
        extractor = MetadataExtractor(warehouse_path)
        assert extractor.warehouse_path == warehouse_path
        assert extractor._catalog is None

    def test_extractor_lazy_catalog(self: TestMetadataExtractor, warehouse_path) -> None:
        """Test that catalog is lazy-loaded."""
        extractor = MetadataExtractor(warehouse_path)
        # Catalog should not be loaded until accessed
        assert extractor._catalog is None
