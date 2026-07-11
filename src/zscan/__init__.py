"""zscan: Zero-scan data quality observability via Iceberg table metadata.

This package provides tools for monitoring data quality using metadata
extracted from Apache Iceberg tables, without scanning actual data files.

Typical usage example:

    from zscan import MetadataExtractor, QualityChecker

    extractor = MetadataExtractor("/path/to/warehouse")
    checker = QualityChecker(extractor)
    results = checker.run_checks()
"""

from zscan.core.checks import QualityChecker
from zscan.core.metadata import MetadataExtractor
from zscan.core.rules import Rule, RuleResult

__version__ = "0.1.0"
__all__ = [
    "MetadataExtractor",
    "QualityChecker",
    "Rule",
    "RuleResult",
]
