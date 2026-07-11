"""Command-line interface for zscan.

This module provides the CLI for running zero-scan data quality checks
against Iceberg tables.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from zscan import __version__
from zscan.core.checks import QualityChecker, print_report
from zscan.core.metadata import MetadataExtractor
from zscan.core.rules import (
    FileCountAnomalyRule,
    NullRateRule,
    RangeViolationRule,
    RowCountDriftRule,
)
from zscan.utils.logging import setup_logging

app = typer.Typer(
    name="zscan",
    help="Zero-scan data quality observability via Iceberg table metadata",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit.

    Args:
        value: Whether to print version.
    """
    if value:
        console.print(f"[bold]zscan[/bold] version: {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """Zero-scan data quality observability via Iceberg table metadata."""


@app.command()
def check(
    table: Annotated[str, typer.Argument(help="Fully qualified table name (e.g., db.table)")],
    warehouse: Annotated[
        str,
        typer.Option("--warehouse", "-w", help="Path to Iceberg warehouse"),
    ] = ".",
    threshold: Annotated[
        float,
        typer.Option("--threshold", "-t", help="Null rate threshold (0.0-1.0)"),
    ] = 0.1,
    drift: Annotated[
        float,
        typer.Option("--drift", "-d", help="Row count drift threshold (%)"),
    ] = 20.0,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
) -> None:
    """Run quality checks against an Iceberg table.

    Reads only metadata files (manifests, snapshots) without scanning
    actual Parquet data files.
    """
    if verbose:
        setup_logging(level=logging.DEBUG)
    else:
        setup_logging(level=logging.INFO)

    console.print(f"[bold]Running quality checks on:[/bold] {table}")
    console.print(f"[dim]Warehouse:[/dim] {warehouse}")
    console.print()

    try:
        extractor = MetadataExtractor(warehouse)
        checker = QualityChecker(extractor)
        checker.add_rule(NullRateRule(default_threshold=threshold))
        checker.add_rule(RowCountDriftRule(threshold_pct=drift))
        checker.add_rule(FileCountAnomalyRule())
        checker.add_rule(RangeViolationRule(column_bounds={}))

        report = checker.run_checks(table)

        if json_output:
            typer.echo(json.dumps(report.to_dict(), indent=2))
        else:
            print_report(report, console)

        raise typer.Exit(code=0 if report.passed else 1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=2)


@app.command()
def inspect(
    table: Annotated[str, typer.Argument(help="Fully qualified table name")],
    warehouse: Annotated[
        str,
        typer.Option("--warehouse", "-w", help="Path to Iceberg warehouse"),
    ] = ".",
    snapshots: Annotated[
        bool,
        typer.Option("--snapshots", "-s", help="Show snapshot history"),
    ] = False,
    files: Annotated[
        bool,
        typer.Option("--files", "-f", help="Show data file details"),
    ] = False,
    schema: Annotated[
        bool,
        typer.Option("--schema", help="Show table schema"),
    ] = False,
) -> None:
    """Inspect Iceberg table metadata without scanning data files.

    Displays metadata information including schema, snapshots, and
    data file statistics.
    """
    try:
        extractor = MetadataExtractor(warehouse)
        metadata = extractor.get_table_metadata(table)

        console.print(f"\n[bold]Table:[/bold] {metadata.table_name}")
        console.print(f"[dim]Location:[/dim] {metadata.location}")
        console.print(f"[dim]Current Snapshot:[/dim] {metadata.current_snapshot_id}")
        console.print()

        if schema or (not snapshots and not files):
            console.print("[bold]Schema:[/bold]")
            for field in metadata.schema_fields:
                req = " [red]*[/red]" if field["required"] else ""
                console.print(f"  {field['name']}: {field['type']}{req}")
            console.print()

        if snapshots or (not schema and not files):
            console.print(f"[bold]Snapshots ({len(metadata.snapshots)}):[/bold]")
            for snap in metadata.snapshots:
                console.print(
                    f"  [{snap.snapshot_id}] {snap.operation} "
                    f"({snap.summary.get('total-records', '?')} records)",
                )
            console.print()

        if files or (not schema and not snapshots):
            console.print(f"[bold]Data Files ({len(metadata.data_files)}):[/bold]")
            for df in metadata.data_files[:10]:
                console.print(
                    f"  {Path(df.file_path).name} "
                    f"({df.record_count} records, {df.file_size_bytes / 1024:.1f} KB)",
                )
            if len(metadata.data_files) > 10:
                console.print(f"  ... and {len(metadata.data_files) - 10} more")
            console.print()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def diff(
    table: Annotated[str, typer.Argument(help="Fully qualified table name")],
    snapshot1: Annotated[int, typer.Argument(help="First snapshot ID")],
    snapshot2: Annotated[int, typer.Argument(help="Second snapshot ID")],
    warehouse: Annotated[
        str,
        typer.Option("--warehouse", "-w", help="Path to Iceberg warehouse"),
    ] = ".",
) -> None:
    """Compare metadata between two snapshots.

    Shows differences in record counts, file counts, and other metrics.
    """
    try:
        extractor = MetadataExtractor(warehouse)
        diff_result = extractor.get_snapshot_diff(table, snapshot1, snapshot2)

        console.print(f"\n[bold]Snapshot Diff: {table}[/bold]")
        console.print(
            f"  Snapshot 1: {diff_result['snapshot_1'].snapshot_id} "
            f"({diff_result['snapshot_1'].operation})",
        )
        console.print(
            f"  Snapshot 2: {diff_result['snapshot_2'].snapshot_id} "
            f"({diff_result['snapshot_2'].operation})",
        )
        console.print()
        console.print(
            f"  Record Count Diff: {diff_result['record_count_diff']:+,}",
        )
        console.print(
            f"  File Count Diff: {diff_result['file_count_diff']:+,}",
        )
        console.print()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
