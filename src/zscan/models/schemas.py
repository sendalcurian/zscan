"""Configuration schemas for zscan quality checks.

This module defines dataclasses for configuring quality checks
via YAML or JSON configuration files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuleConfig:
    """Configuration for a single quality rule.

    Attributes:
        name: Name of the rule class to instantiate.
        enabled: Whether this rule is active.
        params: Parameters to pass to the rule constructor.
    """

    name: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableConfig:
    """Configuration for a table to monitor.

    Attributes:
        name: Fully qualified table name.
        rules: List of rule configurations for this table.
    """

    name: str
    rules: list[RuleConfig] = field(default_factory=list)


@dataclass(frozen=True)
class QualityCheckConfig:
    """Top-level configuration for zscan quality checks.

    Attributes:
        warehouse_path: Path to the Iceberg warehouse.
        tables: List of table configurations to monitor.
        default_rules: Default rules applied to all tables.
    """

    warehouse_path: str
    tables: list[TableConfig] = field(default_factory=list)
    default_rules: list[RuleConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls: type[QualityCheckConfig], data: dict[str, Any]) -> QualityCheckConfig:
        """Create config from a dictionary.

        Args:
            data: Dictionary with configuration values.

        Returns:
            QualityCheckConfig instance.
        """
        tables = []
        for table_data in data.get("tables", []):
            rules = [
                RuleConfig(**rule) for rule in table_data.get("rules", [])
            ]
            tables.append(TableConfig(name=table_data["name"], rules=rules))

        default_rules = [
            RuleConfig(**rule) for rule in data.get("default_rules", [])
        ]

        return cls(
            warehouse_path=data["warehouse_path"],
            tables=tables,
            default_rules=default_rules,
        )

    @classmethod
    def from_yaml(cls: type[QualityCheckConfig], path: str | Path) -> QualityCheckConfig:
        """Load config from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            QualityCheckConfig instance.

        Raises:
            ImportError: If PyYAML is not installed.
            FileNotFoundError: If the file doesn't exist.
        """
        try:
            import yaml
        except ImportError:
            msg = "PyYAML is required for YAML config. Install with: pip install pyyaml"
            raise ImportError(msg)

        path = Path(path)
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)

        with path.open() as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)
