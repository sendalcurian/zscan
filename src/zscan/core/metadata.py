"""Metadata extraction from Apache Iceberg tables.

This module provides the MetadataExtractor class which reads Iceberg
manifest statistics without scanning actual data files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
from pyiceberg.catalog import load_catalog

if TYPE_CHECKING:
    import pyarrow as pa
    from pyiceberg.table import Table


@dataclass(frozen=True)
class ColumnStats:
    """Statistics for a single column in a data file.

    Attributes:
        column_id: The Iceberg field ID.
        column_name: The human-readable column name.
        value_count: Number of non-null values in this file.
        null_count: Number of null values in this file.
        nan_count: Number of NaN values (float columns only).
        lower_bound: Minimum value in this file.
        upper_bound: Maximum value in this file.
    """

    column_id: int
    column_name: str
    value_count: int
    null_count: int
    nan_count: int
    lower_bound: Any
    upper_bound: Any


@dataclass(frozen=True)
class DataFileStats:
    """Statistics for a single data file in an Iceberg table.

    Attributes:
        file_path: Path to the Parquet data file.
        file_format: Format of the data file (e.g., 'PARQUET').
        record_count: Number of records in the file.
        file_size_bytes: Size of the file in bytes.
        partition: Partition values for this file.
        column_stats: Mapping of column name to ColumnStats.
    """

    file_path: str
    file_format: str
    record_count: int
    file_size_bytes: int
    partition: dict[str, Any]
    column_stats: dict[str, ColumnStats] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotInfo:
    """Information about an Iceberg snapshot.

    Attributes:
        snapshot_id: Unique identifier for this snapshot.
        timestamp_ms: Timestamp in milliseconds when snapshot was created.
        operation: Operation that created this snapshot (e.g., 'append').
        summary: Summary statistics for this snapshot.
    """

    snapshot_id: int
    timestamp_ms: int
    operation: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class TableMetadata:
    """Complete metadata for an Iceberg table at a point in time.

    Attributes:
        table_name: Name of the table.
        location: URI of the table location.
        current_snapshot_id: ID of the current snapshot.
        schema_fields: List of field definitions.
        snapshots: All available snapshots.
        data_files: Statistics for all data files in current snapshot.
    """

    table_name: str
    location: str
    current_snapshot_id: int | None
    schema_fields: list[dict[str, Any]]
    snapshots: list[SnapshotInfo]
    data_files: list[DataFileStats]


class MetadataExtractor:
    """Extracts metadata from Iceberg tables without scanning data files.

    This class provides methods to read Iceberg manifest statistics
    including record counts, null counts, value bounds, and more.
    All operations use only metadata files (Avro manifests, JSON metadata)
    and never read Parquet data files.

    Attributes:
        warehouse_path: Path to the Iceberg warehouse directory.
        catalog: The PyIceberg catalog instance.
    """

    def __init__(self, warehouse_path: str | Path, catalog_name: str = "default") -> None:
        """Initialize the MetadataExtractor.

        Args:
            warehouse_path: Path to the local Iceberg warehouse.
            catalog_name: Name of the catalog to use.
        """
        self.warehouse_path = Path(warehouse_path)
        self._catalog_name = catalog_name
        self._catalog = None

    @property
    def catalog(self: MetadataExtractor) -> Any:
        """Lazy-load and return the Iceberg catalog.

        Returns:
            The configured PyIceberg catalog instance.
        """
        if self._catalog is None:
            self._catalog = load_catalog(
                self._catalog_name,
                type="sql", uri=f"sqlite:///{self.warehouse_path / 'catalog.db'}", warehouse=str(self.warehouse_path),
            )
        return self._catalog

    def load_table(self: MetadataExtractor, table_name: str) -> Table:
        """Load an Iceberg table by name.

        Args:
            table_name: Fully qualified table name (e.g., 'db.table').

        Returns:
            The loaded Iceberg Table instance.
        """
        return self.catalog.load_table(table_name)

    def get_table_metadata(self: MetadataExtractor, table_name: str) -> TableMetadata:
        """Extract complete metadata for a table.

        Reads only metadata files (manifests, snapshots) without
        accessing any Parquet data files.

        Args:
            table_name: Fully qualified table name.

        Returns:
            TableMetadata containing all extracted statistics.
        """
        table = self.load_table(table_name)

        # Get snapshots
        snapshots = []
        if table.metadata.snapshots is not None:
            for snap in table.metadata.snapshots:
                snapshots.append(
                    SnapshotInfo(
                        snapshot_id=snap.snapshot_id,
                        timestamp_ms=snap.timestamp_ms,
                        operation=snap.summary.get("operation", "unknown"),
                        summary={"operation": str(snap.summary.operation.value), **snap.summary._additional_properties} if snap.summary else {},
                    ),
                )

        # Get schema fields
        schema_fields = [
            {
                "id": fld.field_id,
                "name": fld.name,
                "type": str(fld.field_type),
                "required": fld.required,
            }
            for fld in table.schema().fields
        ]

        # Get data files from current snapshot
        data_files = self._extract_data_files(table)

        return TableMetadata(
            table_name=table_name,
            location=table.location(),
            current_snapshot_id=(
                table.current_snapshot().snapshot_id
                if table.current_snapshot()
                else None
            ),
            schema_fields=schema_fields,
            snapshots=snapshots,
            data_files=data_files,
        )

    def _extract_data_files(self: MetadataExtractor, table: Table) -> list[DataFileStats]:
        """Extract data file statistics from table manifests.

        Args:
            table: The Iceberg table to extract from.

        Returns:
            List of DataFileStats for all files in current snapshot.
        """
        files_table = table.inspect.files()
        data_files = []

        for i in range(files_table.num_rows):
            row = {col: files_table.column(col)[i].as_py() for col in files_table.column_names}

            # Parse column stats
            column_stats = {}
            null_counts = dict(row.get("null_value_counts") or [])
            value_counts = dict(row.get("value_counts") or [])
            nan_counts = dict(row.get("nan_value_counts") or [])
            lower_bounds = dict(row.get("lower_bounds") or [])
            upper_bounds = dict(row.get("upper_bounds") or [])

            for col_id, null_count in null_counts.items():
                col_name = self._resolve_column_name(table, int(col_id))
                column_stats[col_name] = ColumnStats(
                    column_id=int(col_id),
                    column_name=col_name,
                    value_count=value_counts.get(col_id, 0),
                    null_count=null_count,
                    nan_count=nan_counts.get(col_id, 0),
                    lower_bound=lower_bounds.get(col_id),
                    upper_bound=upper_bounds.get(col_id),
                )

            data_files.append(
                DataFileStats(
                    file_path=row.get("file_path", ""),
                    file_format=row.get("file_format", "PARQUET"),
                    record_count=row.get("record_count", 0),
                    file_size_bytes=row.get("file_size_in_bytes", 0),
                    partition=row.get("partition", {}),
                    column_stats=column_stats,
                ),
            )

        return data_files

    def _resolve_column_name(
        self: MetadataExtractor, table: Table, column_id: int,
    ) -> str:
        """Resolve a column ID to its name using the table schema.

        Args:
            table: The Iceberg table with the schema.
            column_id: The Iceberg field ID to resolve.

        Returns:
            The column name, or 'unknown_{id}' if not found.
        """
        for fld in table.schema().fields:
            if fld.field_id == column_id:
                return fld.name
        return f"unknown_{column_id}"

    def get_snapshot_diff(
        self: MetadataExtractor, table_name: str, snapshot_id_1: int, snapshot_id_2: int,
    ) -> dict[str, Any]:
        """Compare metadata between two snapshots.

        Args:
            table_name: Fully qualified table name.
            snapshot_id_1: ID of the first (older) snapshot.
            snapshot_id_2: ID of the second (newer) snapshot.

        Returns:
            Dictionary with differences between snapshots.
        """
        metadata = self.get_table_metadata(table_name)

        snap1 = next(
            (s for s in metadata.snapshots if s.snapshot_id == snapshot_id_1), None,
        )
        snap2 = next(
            (s for s in metadata.snapshots if s.snapshot_id == snapshot_id_2), None,
        )

        if not snap1 or not snap2:
            msg = "One or both snapshot IDs not found"
            raise ValueError(msg)

        return {
            "snapshot_1": snap1,
            "snapshot_2": snap2,
            "record_count_diff": int(
                snap2.summary.get("total-records", 0),
            )
            - int(snap1.summary.get("total-records", 0)),
            "file_count_diff": int(
                snap2.summary.get("total-data-files", 0),
            )
            - int(snap1.summary.get("total-data-files", 0)),
        }

    def query_with_duckdb(
        self: MetadataExtractor, table_name: str, sql: str,
    ) -> pa.Table:
        """Execute a DuckDB query against Iceberg metadata.

        Uses DuckDB's iceberg extension to query metadata tables
        without scanning data files.

        Args:
            table_name: Fully qualified table name.
            sql: SQL query to execute (use '{table}' as placeholder for table path).

        Returns:
            PyArrow table with query results.
        """
        table = self.load_table(table_name)
        metadata_location = table.metadata_location

        con = duckdb.connect()
        con.execute("INSTALL iceberg; LOAD iceberg;")

        query = sql.replace("{table}", f"'{metadata_location}'")
        result = con.execute(query)
        return result.fetch_arrow_table()
