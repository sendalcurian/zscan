# Zero-Scan Data Quality: Continuous Observability via Table Metadata

## Core Concept

Traditional data quality (DQ) is a "read-time" concern, requiring expensive SQL queries or full table scans to validate data after it is written. **Zero-Scan DQ** shifts this to a **metadata-first approach**, repurposing statistics already computed and stored during the write process by modern table formats like Apache Iceberg.

These write-time statistics — including record counts, null counts, and value bounds — are stored in manifest files as byproducts of encoding with negligible overhead. This method allows for continuous observability, including anomaly detection and drift monitoring, without ever scanning the actual data.

Research shows that manifest statistics alone can satisfy **~60%** of common DQ rules, and extending these with lightweight counters and sketches can raise coverage to nearly **90%**.

---

## Local Prototyping: Lightweight Stack (No Spark)

Instead of Spark + Iceberg (JVM-heavy, complex setup), use a **Python-only stack** that runs on a laptop with zero infrastructure:

| Component | Role |
|---|---|
| **PyIceberg** (`pyiceberg[sql-sqlite,pyarrow]`) | Create Iceberg tables, append data, and — critically — read manifest-level column statistics via `table.inspect.files()` without touching any Parquet data |
| **DuckDB** + `iceberg` extension | Query metadata directly via `iceberg_metadata()`, `iceberg_column_stats()`, `iceberg_snapshots()` — all SQL, no data scan |
| **SQLite catalog** (PyIceberg `SqlCatalog`) | Stores Iceberg metadata in a local `catalog.db` file — no Hive, no REST server |
| **Local filesystem** | Tables and data files stored on disk — no S3, no MinIO |

### Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  PyIceberg   │────▶│  Iceberg Table   │────▶│  DuckDB              │
│  (write)     │     │  (local FS)      │     │  iceberg_metadata()  │
│  .append()   │     │                  │     │  iceberg_column_     │
└──────────────┘     │  metadata/*.json │     │  stats()             │
                     │  metadata/*.avro │◀────│  iceberg_snapshots() │
                     │  data/*.parquet  │     └────────┬────────────┘
                     └──────────────────┘              │
                                                       │
                                              zero data files read;
                                              only Avro manifests
                                              and metadata JSON
```

### Metadata Available per Data File (Zero-Scan)

Each `DataFile` entry in Iceberg manifests exposes these column-level statistics — computed at write time during Parquet encoding, stored in Avro manifest files, readable without opening any data file:

| Statistic | PyIceberg Attribute | DuckDB Column |
|---|---|---|
| Record count | `DataFile.record_count` | `record_count` |
| File size | `DataFile.file_size_in_bytes` | `file_size_in_bytes` |
| Column sizes | `DataFile.column_sizes` (map) | `column_sizes` |
| Value counts | `DataFile.value_counts` (map) | `value_counts` |
| **Null counts** | `DataFile.null_value_counts` (map) | `null_value_counts` |
| NaN counts | `DataFile.nan_value_counts` (map) | `nan_value_counts` |
| **Lower bounds** | `DataFile.lower_bounds` (map) | `lower_bounds` |
| **Upper bounds** | `DataFile.upper_bounds` (map) | `upper_bounds` |

### Prototyping Steps

1. **Setup**: Create an Iceberg table via PyIceberg with `SqlCatalog` + SQLite + local warehouse. Insert data with known quality issues (nulls, out-of-range values) across multiple commits to generate snapshot history.
2. **Metadata extraction**: Use `table.inspect.files()` to get PyArrow table of all data files with column stats. Or use DuckDB: `SELECT * FROM iceberg_metadata('path/to/metadata.json')`. No Parquet files are read.
3. **Quality checks from metadata alone**:
   - **Row count drift**: Compare `SUM(record_count)` across snapshots
   - **Null rate spike**: Aggregate `null_value_counts` per column across all files
   - **Range violation**: Check `MIN(lower_bounds)` and `MAX(upper_bounds)` against expected thresholds
   - **File count anomaly**: Track number of data files per snapshot
4. **Observation**: All checks execute in milliseconds on metadata (tens of KB–MB) vs seconds/minutes on data (GB+). This is the zero-scan difference.

### Three-Tier Rule Coverage (from Research)

| Tier | What Metadata Answers | Coverage | When It Falls Short |
|---|---|---|---|
| **Tier 1 — Exact** | Row counts, null counts, global bounds (`MIN >= 0`), NaN counts, column sizes | ~60% of DQ rules | N/A — these are exact aggregates |
| **Tier 2 — Targeted** | Uniqueness, membership, distinctness (with sketches: Theta for NDV, KLL for quantiles) | ~90% with extensions | When bounds overlap across files → scan only those files named by the manifest |
| **Tier 3 — Full scan** | Cross-column (`ship_date >= order_date`), cross-row correlations, full distributions | Remaining ~10% | Requires data access; reserved for genuinely hard checks |

---

## Product Requirements

### Problem Statement

Scan-based validation is prohibitively expensive at scale, consuming massive compute resources and introducing high detection latency (2–24 hours).

### Proposed Solution

Implement a metadata extraction pipeline that consumes Iceberg commit events and generates time-series observability signals.

### Key Features

1. **Writer Identity Filtering**
   - Use application identity metadata to ignore "maintenance noise" like compaction or sorting.

2. **Extension Support**
   - Integrate Puffin sidecar files to store Theta and KLL sketches for distinct counts and quantiles, expanding rule coverage.

3. **Declarative Constraints**
   - Allow users to define quality predicates that are evaluated during the Iceberg commit protocol, rejecting "bad" commits before they reach consumers.

### Success Metrics

- ~50% reduction in compute and storage consumption
- Detection latency reduced to under 20 minutes

---

## The Dual Benefit

This approach is grounded in the **"dual benefit" of metadata**: the same statistics required for query optimization (join-order estimation, selectivity) are identical to those needed for DQ monitoring. This alignment justifies the initial compute investment at write-time, as it improves both the performance of reading data and the reliability of the data itself.

---

## References & Related Work

### Core Research
- **Zero-Scan Data Quality** (arXiv:2605.30308, SIGMOD 2026) — LinkedIn's production deployment across 200K+ Iceberg tables (800+ PB). ~60% DQ rules from manifest stats alone; ~90% with counters + sketches. 50% reduction in compute/reads.
- **"Your Table Format Already Knows If the Data Is Broken"** (Shriom Tripathi, 2026) — Practitioner's framing: data quality and query pruning are the same problem. The metadata already written for data skipping is a continuously-updated DQ index.

### Lightweight Tooling (No Spark)
- **PyIceberg** (`py.iceberg.apache.org`) — Official Python library. `table.inspect.files()` returns per-file column stats as PyArrow. No JVM required.
- **DuckDB Iceberg Extension** — `iceberg_scan()`, `iceberg_metadata()`, `iceberg_snapshots()`, `iceberg_column_stats()` functions. Reads Iceberg metadata tables via SQL; entirely in-process.
- **iceberg-meta** (`pypi.org/project/iceberg-meta`) — CLI/TUI for Iceberg metadata exploration. `health` command detects small files, null rates, partition skew, and value bounds from manifest stats alone (~1.5s vs ~15s Spark startup).

### Open-Source DQ Projects (Scan-Based, but Adaptable)
- **anofox-tabular** — DuckDB extension with 81 SQL functions for validation, anomaly detection (Isolation Forest, DBSCAN), and profiling. Complements zero-scan by handling Tier 3 checks on metadata-filtered data.
- **provero-org/provero** — Declarative YAML-based DQ engine with DuckDB support. `provero watch` for continuous monitoring. Could integrate with metadata-first checks.
- **aegis-dq/aegis-dq** — 31 rule types, LLM diagnosis, SQL auto-fix proposals. DuckDB adapter. Agentic pipeline for planning → validation → diagnosis → remediation.
- **elementary-data/elementary** — dbt-native data observability with anomaly detection tests and automated monitors. Currently scan-based but could leverage metadata tables.
