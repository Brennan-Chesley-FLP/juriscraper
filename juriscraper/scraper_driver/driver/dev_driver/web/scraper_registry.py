"""Scraper registry for discovering and loading scraper classes.

This module provides functionality for:
- Scanning directories for BaseScraper subclasses
- Extracting scraper metadata (courts, data types, status)
- Extracting parameter schema from ScraperParams
- Serializing/deserializing ScraperParams for web API
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from juriscraper.scraper_driver.common.searchable import (
        FieldProxy,
        ScraperParams,
    )
    from juriscraper.scraper_driver.data_types import BaseScraper

logger = logging.getLogger(__name__)


@dataclass
class FieldSchema:
    """Schema for a searchable field."""

    name: str
    filter_type: str  # "DateRange", "SetFilter", "UniqueMatch"
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "filter_type": self.filter_type,
            "description": self.description,
        }


@dataclass
class ModelSchema:
    """Schema for a data model's searchable fields."""

    name: str
    fields: list[FieldSchema] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass
class SpeculativeStepSchema:
    """Schema for a speculative step."""

    name: str
    default_starting_id: int = 1
    largest_observed_gap: int = 10

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "default_starting_id": self.default_starting_id,
            "largest_observed_gap": self.largest_observed_gap,
        }


@dataclass
class ScraperInfo:
    """Information about a discovered scraper."""

    module_path: str  # e.g., "juriscraper.sd.state.new_york.nyscef.scraper"
    class_name: str  # e.g., "NYSCEFScraper"
    full_path: str  # module_path:class_name

    # Metadata from scraper class
    court_ids: set[str] = field(default_factory=set)
    court_url: str = ""
    data_types: set[str] = field(default_factory=set)
    status: str = "unknown"
    version: str = ""
    requires_auth: bool = False
    rate_limit_ms: int | None = None

    # Parameter schema
    models: list[ModelSchema] = field(default_factory=list)
    speculative_steps: list[SpeculativeStepSchema] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "module_path": self.module_path,
            "class_name": self.class_name,
            "full_path": self.full_path,
            "court_ids": list(self.court_ids),
            "court_url": self.court_url,
            "data_types": list(self.data_types),
            "status": self.status,
            "version": self.version,
            "requires_auth": self.requires_auth,
            "rate_limit_ms": self.rate_limit_ms,
            "models": [m.to_dict() for m in self.models],
            "speculative_steps": [s.to_dict() for s in self.speculative_steps],
        }


class ScraperRegistry:
    """Registry for discovering and managing scraper classes."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._scrapers: dict[str, ScraperInfo] = {}
        self._classes: dict[str, type[BaseScraper[Any]]] = {}

    def scan_directory(self, base_dir: Path, package_prefix: str) -> int:
        """Scan a directory for scraper classes.

        Args:
            base_dir: Directory to scan (e.g., juriscraper/sd)
            package_prefix: Python package prefix (e.g., "juriscraper.sd")

        Returns:
            Number of scrapers discovered.
        """
        count = 0

        # Find all scraper.py files
        for scraper_file in base_dir.rglob("scraper.py"):
            try:
                # Build module path from file path
                relative_path = scraper_file.relative_to(base_dir)
                parts = list(relative_path.parent.parts) + ["scraper"]
                module_path = f"{package_prefix}.{'.'.join(parts)}"

                scrapers = self._scan_module(module_path)
                count += len(scrapers)

            except Exception as e:
                logger.warning(f"Error scanning {scraper_file}: {e}")

        return count

    def _scan_module(self, module_path: str) -> list[ScraperInfo]:
        """Scan a single module for scraper classes.

        Args:
            module_path: Full module path (e.g., "juriscraper.sd.state.new_york.nyscef.scraper")

        Returns:
            List of discovered ScraperInfo objects.
        """
        from juriscraper.scraper_driver.data_types import BaseScraper

        scrapers: list[ScraperInfo] = []

        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            logger.warning(f"Could not import {module_path}: {e}")
            return scrapers

        # Find all BaseScraper subclasses in the module
        for name in dir(module):
            obj = getattr(module, name)

            # Check if it's a class that inherits from BaseScraper
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, BaseScraper):
                continue
            if obj is BaseScraper:
                continue
            # Skip if not defined in this module
            if obj.__module__ != module_path:
                continue

            scraper_info = self._extract_scraper_info(obj, module_path, name)
            self._scrapers[scraper_info.full_path] = scraper_info
            self._classes[scraper_info.full_path] = obj
            scrapers.append(scraper_info)

            logger.info(f"Discovered scraper: {scraper_info.full_path}")

        return scrapers

    def _extract_scraper_info(
        self,
        scraper_class: type[BaseScraper[Any]],
        module_path: str,
        class_name: str,
    ) -> ScraperInfo:
        """Extract metadata and parameter schema from a scraper class.

        Args:
            scraper_class: The scraper class.
            module_path: Module path where scraper is defined.
            class_name: Name of the scraper class.

        Returns:
            ScraperInfo with metadata and schema.
        """
        full_path = f"{module_path}:{class_name}"

        # Extract class-level metadata
        court_ids = getattr(scraper_class, "court_ids", set()) or set()
        court_url = getattr(scraper_class, "court_url", "") or ""
        data_types = getattr(scraper_class, "data_types", set()) or set()
        status_enum = getattr(scraper_class, "status", None)
        status = status_enum.value if status_enum else "unknown"
        version = getattr(scraper_class, "version", "") or ""
        requires_auth = getattr(scraper_class, "requires_auth", False)
        rate_limit_ms = getattr(
            scraper_class, "msec_per_request_rate_limit", None
        )

        # Extract parameter schema and speculative steps
        models = self._extract_params_schema(scraper_class)
        speculative_steps = self._extract_speculative_steps(scraper_class)

        return ScraperInfo(
            module_path=module_path,
            class_name=class_name,
            full_path=full_path,
            court_ids=set(court_ids),
            court_url=court_url,
            data_types=set(data_types),
            status=status,
            version=version,
            requires_auth=requires_auth,
            rate_limit_ms=rate_limit_ms,
            models=models,
            speculative_steps=speculative_steps,
        )

    def _extract_params_schema(
        self, scraper_class: type[BaseScraper[Any]]
    ) -> list[ModelSchema]:
        """Extract parameter schema from scraper's data models.

        Args:
            scraper_class: The scraper class.

        Returns:
            List of ModelSchema objects.
        """
        from juriscraper.scraper_driver.common.searchable import (
            DateRange,
            SetFilter,
            UniqueMatch,
        )

        models: list[ModelSchema] = []

        try:
            params = scraper_class.params()
        except Exception as e:
            logger.warning(
                f"Could not build params for {scraper_class.__name__}: {e}"
            )
            return models

        for model_name, model_proxy in params.get_models().items():
            fields = []

            for (
                field_name,
                field_proxy,
            ) in model_proxy.get_searchable_fields().items():
                marker = field_proxy.marker

                if isinstance(marker, DateRange):
                    filter_type = "DateRange"
                elif isinstance(marker, SetFilter):
                    filter_type = "SetFilter"
                elif isinstance(marker, UniqueMatch):
                    filter_type = "UniqueMatch"
                else:
                    filter_type = "unknown"

                # Try to get field description from model
                description = None
                model_class = model_proxy.model_class
                if field_name in model_class.model_fields:
                    field_info = model_class.model_fields[field_name]
                    description = field_info.description

                fields.append(
                    FieldSchema(
                        name=field_name,
                        filter_type=filter_type,
                        description=description,
                    )
                )

            models.append(ModelSchema(name=model_name, fields=fields))

        return models

    def _extract_speculative_steps(
        self, scraper_class: type[BaseScraper[Any]]
    ) -> list[SpeculativeStepSchema]:
        """Extract speculative steps from scraper class.

        Args:
            scraper_class: The scraper class.

        Returns:
            List of SpeculativeStepSchema objects.
        """
        from juriscraper.scraper_driver.common.decorators import (
            get_speculate_metadata,
        )
        from juriscraper.scraper_driver.common.searchable import (
            _find_speculate_functions,
        )

        speculative_steps: list[SpeculativeStepSchema] = []

        try:
            step_names = _find_speculate_functions(scraper_class)
            for step_name in sorted(step_names):
                # Get the decorator metadata for largest_observed_gap
                func = getattr(scraper_class, step_name, None)
                metadata = get_speculate_metadata(func) if func else None
                largest_gap = metadata.largest_observed_gap if metadata else 10

                speculative_steps.append(
                    SpeculativeStepSchema(
                        name=step_name,
                        default_starting_id=1,
                        largest_observed_gap=largest_gap,
                    )
                )
        except Exception as e:
            logger.warning(
                f"Could not extract speculative steps for "
                f"{scraper_class.__name__}: {e}"
            )

        return speculative_steps

    def list_scrapers(self) -> list[ScraperInfo]:
        """List all discovered scrapers.

        Returns:
            List of ScraperInfo objects.
        """
        return list(self._scrapers.values())

    def get_scraper(self, full_path: str) -> ScraperInfo | None:
        """Get info for a specific scraper.

        Args:
            full_path: Full scraper path (module:class).

        Returns:
            ScraperInfo or None if not found.
        """
        return self._scrapers.get(full_path)

    def get_scraper_class(
        self, full_path: str
    ) -> type[BaseScraper[Any]] | None:
        """Get the actual scraper class.

        Args:
            full_path: Full scraper path (module:class).

        Returns:
            The scraper class or None if not found.
        """
        return self._classes.get(full_path)

    def instantiate_scraper(
        self, full_path: str, params_data: dict[str, Any] | None = None
    ) -> BaseScraper[Any] | None:
        """Instantiate a scraper with optional parameters.

        Args:
            full_path: Full scraper path (module:class).
            params_data: Optional parameter data from web form.

        Returns:
            Instantiated scraper or None if not found.
        """
        scraper_class = self.get_scraper_class(full_path)
        if scraper_class is None:
            return None

        # Build ScraperParams if params_data provided
        params = None
        if params_data:
            params = self._build_params(scraper_class, params_data)

        # Instantiate scraper with params (BaseScraper accepts params in __init__)
        return scraper_class(params=params)

    def _build_params(
        self,
        scraper_class: type[BaseScraper[Any]],
        params_data: dict[str, Any],
    ) -> ScraperParams:
        """Build ScraperParams from web form data.

        Args:
            scraper_class: The scraper class.
            params_data: Parameter data from web form.

        Returns:
            Configured ScraperParams.

        Expected params_data format:
        {
            "models": {
                "NYSCEFDocket": {
                    "enabled": true,
                    "fields": {
                        "date_filed": {
                            "gte": "2024-01-01",
                            "lte": "2024-12-31"
                        },
                        "court_id": {
                            "values": ["nysupctbrnx", "nysupctkings"]
                        },
                        "docket_number": {
                            "value": "2024-001"
                        }
                    }
                }
            },
            "speculative": {
                "parse_case": 100,
                "parse_detail": 500
            }
        }
        """
        params = scraper_class.params()

        models_data = params_data.get("models", {})
        for model_name, model_data in models_data.items():
            try:
                model_proxy = getattr(params, model_name)
            except AttributeError:
                logger.warning(f"Unknown model: {model_name}")
                continue

            # Handle model enable/disable
            if not model_data.get("enabled", True):
                setattr(params, model_name, None)
                continue

            # Set field values
            fields_data = model_data.get("fields", {})
            for field_name, field_data in fields_data.items():
                try:
                    field_proxy = getattr(model_proxy, field_name)
                except AttributeError:
                    logger.warning(f"Unknown field: {model_name}.{field_name}")
                    continue

                self._set_field_value(field_proxy, field_data)

        # Set speculative step starting IDs
        speculative_data = params_data.get("speculative", {})
        for step_name, starting_id in speculative_data.items():
            try:
                if starting_id is not None:
                    setattr(params.speculative, step_name, int(starting_id))
            except AttributeError:
                logger.warning(f"Unknown speculative step: {step_name}")
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Invalid starting ID for {step_name}: {starting_id} ({e})"
                )

        return params

    def _set_field_value(
        self, field_proxy: FieldProxy[Any], field_data: dict[str, Any]
    ) -> None:
        """Set a field's filter value from form data.

        Args:
            field_proxy: The field proxy to configure.
            field_data: Filter data from form.
        """
        from juriscraper.scraper_driver.common.searchable import (
            DateRange,
            SetFilter,
            UniqueMatch,
        )

        marker = field_proxy.marker

        if isinstance(marker, DateRange):
            if "gte" in field_data and field_data["gte"]:
                field_proxy.gte = self._parse_date(field_data["gte"])
            if "lte" in field_data and field_data["lte"]:
                field_proxy.lte = self._parse_date(field_data["lte"])

        elif isinstance(marker, SetFilter):
            if "values" in field_data and field_data["values"]:
                values = field_data["values"]
                if isinstance(values, list):
                    field_proxy.values = set(values)
                elif isinstance(values, str):
                    # Handle comma-separated string
                    field_proxy.values = {v.strip() for v in values.split(",")}

        elif isinstance(marker, UniqueMatch):
            if "value" in field_data and field_data["value"]:
                field_proxy.value = field_data["value"]

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in ISO format.

        Args:
            date_str: Date string (YYYY-MM-DD).

        Returns:
            Parsed date or None if invalid.
        """
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}")
            return None


# Global registry instance
_registry: ScraperRegistry | None = None


def get_registry() -> ScraperRegistry:
    """Get the global registry instance.

    Returns:
        The ScraperRegistry instance.

    Raises:
        RuntimeError: If registry not initialized.
    """
    if _registry is None:
        raise RuntimeError("Scraper registry not initialized")
    return _registry


def init_registry(sd_directory: Path | None = None) -> ScraperRegistry:
    """Initialize the global scraper registry.

    Args:
        sd_directory: Directory to scan for scrapers.
            Defaults to juriscraper/sd relative to this package.

    Returns:
        The initialized registry.
    """
    global _registry

    _registry = ScraperRegistry()

    # Default to juriscraper/sd
    if sd_directory is None:
        # Navigate from this file to juriscraper/sd
        # This file is at juriscraper/scraper_driver/driver/dev_driver/web/scraper_registry.py
        this_file = Path(__file__)
        sd_directory = this_file.parent.parent.parent.parent.parent / "sd"

    if sd_directory.exists():
        count = _registry.scan_directory(sd_directory, "juriscraper.sd")
        logger.info(f"Initialized scraper registry with {count} scrapers")
    else:
        logger.warning(f"Scraper directory not found: {sd_directory}")

    return _registry
