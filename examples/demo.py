"""Demo script showing zscan zero-scan data quality checks.

This script demonstrates how to use zscan to check data quality
using only Iceberg metadata, without scanning actual data files.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pyarrow as pa
from pyiceberg.catalog import SqlCatalog

from zscan import MetadataExtractor, QualityChecker
from zscan.core.checks import print_report
from zscan.core.rules import (
    FileCountAnomalyRule,
    NullRateRule,
    RangeViolationRule,
    RowCountDriftRule,
)
from zscan.utils.logging import setup_logging


def create_sample_table(warehouse_path: Path) -> str:
    """Create a sample Iceberg table with test data.

    Args:
        warehouse_path: Path to the warehouse directory.

    Returns:
        Table name.
    """
    catalog = SqlCatalog(
        "default",
        uri=f"sqlite:///{warehouse_path / 'catalog.db'}", warehouse=str(warehouse_path),
    )

    # Create namespace
    catalog.create_namespace_if_not_exists("demo")

    # Define schema
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("name", pa.string(), nullable=True),
            pa.field("value", pa.float64(), nullable=True),
            pa.field("category", pa.string(), nullable=True),
        ],
    )

    # Create table
    table_name = "demo.sample_data"
    table = catalog.create_table_if_not_exists(
        table_name,
        schema=schema,
    )

    # Insert batch 1 (clean data)
    data1 = pa.table(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
            "value": [10.0, 20.0, 30.0, 40.0, 50.0],
            "category": ["A", "B", "A", "B", "A"],
        },
    )
    table.append(data1)

    # Insert batch 2 (with nulls)
    data2 = pa.table(
        {
            "id": [6, 7, 8, 9, 10],
            "name": ["Frank", None, "Hank", None, "Jack"],
            "value": [60.0, None, 80.0, None, 100.0],
            "category": ["B", "A", None, "B", None],
        },
    )
    table.append(data2)

    # Insert batch 3 (with out-of-range value)
    data3 = pa.table(
        {
            "id": [11, 12, 13, 14, 15],
            "name": ["Kate", "Liam", "Mia", "Noah", "Olivia"],
            "value": [-5.0, 120.0, 130.0, 140.0, 150.0],  # -5 is out of range
            "category": ["A", "B", "A", "B", "A"],
        },
    )
    table.append(data3)

    return table_name


def main() -> None:
    """Run the demo quality checks."""
    setup_logging()


    with tempfile.TemporaryDirectory() as tmpdir:
        warehouse_path = Path(tmpdir) / "warehouse"
        warehouse_path.mkdir()

        table_name = create_sample_table(warehouse_path)

        extractor = MetadataExtractor(warehouse_path)
        metadata = extractor.get_table_metadata(table_name)

        checker = QualityChecker(extractor)
        checker.add_rule(NullRateRule(default_threshold=0.1))
        checker.add_rule(RowCountDriftRule(threshold_pct=20.0))
        checker.add_rule(FileCountAnomalyRule())
        checker.add_rule(
            RangeViolationRule(
                column_bounds={"value": (0.0, None)},  # value >= 0
            ),
        )

        report = checker.run_checks(table_name, metadata=metadata)
        print_report(report)





if __name__ == "__main__":
    main()
