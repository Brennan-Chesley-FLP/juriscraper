#!/usr/bin/env python3
"""Build court registry from scraper metadata.

This script discovers all new-architecture scrapers, extracts their metadata,
calculates coverage statistics, and outputs a consolidated TOML registry file.

Usage:
    python -m scripts.build_court_registry

Output:
    docs/source/_generated/court_registry.toml
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from datetime import date
from pathlib import Path

try:
    import tomllib  # ty: ignore[unresolved-import]
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tomli_w  # noqa: E402

from juriscraper.scraper_driver.common.models.base import (  # noqa: E402
    ConsumerModel,
)
from juriscraper.scraper_driver.common.searchable import (  # noqa: E402
    DateRange,
    SetFilter,
    UniqueMatch,
    build_params_for_scraper,
)
from juriscraper.scraper_driver.data_types import BaseScraper  # noqa: E402


def get_return_type_info(scraper_class: type) -> dict[str, str | list[str]]:
    """Extract return type and its ConsumerModel parent class.

    Analyzes the scraper's generic type parameter to find the return type
    and its inheritance chain back to ConsumerModel. Handles both single
    types and Union types.

    Args:
        scraper_class: A scraper class that inherits from BaseScraper[T].

    Returns:
        Dict with:
        - "return_type": Name of the return type class (or "A | B" for unions)
        - "parent_model": Name of the immediate ConsumerModel subclass parent
        - "model_hierarchy": List of class names from return type to ConsumerModel
    """
    from types import UnionType
    from typing import Union, get_args, get_origin

    # Extract the return type from BaseScraper[T]
    return_type = None
    for base in getattr(scraper_class, "__orig_bases__", []):
        origin = get_origin(base)
        if origin is BaseScraper or (
            isinstance(origin, type) and issubclass(origin, BaseScraper)
        ):
            args = get_args(base)
            if args:
                return_type = args[0]
                break

    if return_type is None:
        return {}

    # Handle Union types (X | Y or Union[X, Y])
    type_origin = get_origin(return_type)
    if type_origin is Union or isinstance(return_type, UnionType):
        # Get all types in the union
        union_args = get_args(return_type)
        type_names = [t.__name__ for t in union_args if isinstance(t, type)]

        # Build combined hierarchy from all types
        all_hierarchy: list[str] = []
        parent_models: set[str] = set()

        for t in union_args:
            if not isinstance(t, type):
                continue
            for cls in t.__mro__:
                if cls is object:
                    continue
                if cls.__name__ not in all_hierarchy:
                    all_hierarchy.append(cls.__name__)
                # Find ConsumerModel parents
                if (
                    issubclass(cls, ConsumerModel)
                    and cls is not ConsumerModel
                    and cls is not t
                ):
                    parent_models.add(cls.__name__)

        return {
            "return_type": " | ".join(type_names),
            "parent_model": ", ".join(sorted(parent_models))
            if parent_models
            else "",
            "model_hierarchy": all_hierarchy,
        }

    # Single type case
    if not isinstance(return_type, type):
        return {}

    # Build the model hierarchy back to ConsumerModel
    hierarchy: list[str] = []
    parent_model = ""

    for cls in return_type.__mro__:
        if cls is object:
            continue
        hierarchy.append(cls.__name__)
        # Find the first ConsumerModel subclass (not ConsumerModel itself)
        if (
            not parent_model
            and issubclass(cls, ConsumerModel)
            and cls is not ConsumerModel
            and cls is not return_type
        ):
            parent_model = cls.__name__

    # If we didn't find a parent, and the return type is a direct subclass
    if (
        not parent_model
        and issubclass(return_type, ConsumerModel)
        and return_type is not ConsumerModel
    ):
        # Check if direct child of ConsumerModel
        if ConsumerModel in return_type.__bases__:
            parent_model = "ConsumerModel"
        else:
            # Find the parent that's a ConsumerModel subclass
            for base in return_type.__bases__:
                if (
                    issubclass(base, ConsumerModel)
                    and base is not ConsumerModel
                ):
                    parent_model = base.__name__
                    break

    return {
        "return_type": return_type.__name__,
        "parent_model": parent_model,
        "model_hierarchy": hierarchy,
    }


def load_court_table() -> dict:
    """Load the master court table from data/courts.toml."""
    court_file = PROJECT_ROOT / "docs" / "data" / "courts.toml"
    if not court_file.exists():
        print(f"Warning: {court_file} not found, using empty court table")
        return {"courts": {}, "jurisdictions": {"unknown": {"codes": []}}}

    with open(court_file, "rb") as f:
        return tomllib.load(f)


def get_data_types(scraper_class: type) -> list[str]:
    """Get data types from the scraper's data_types ClassVar.

    Args:
        scraper_class: A scraper class that inherits from BaseScraper.

    Returns:
        Sorted list of data type names.
    """
    data_types: set[str] = getattr(scraper_class, "data_types", set())
    return sorted(data_types) if data_types else []


def get_searchability(scraper_class: type) -> dict[str, dict[str, list[str]]]:
    """Extract searchable field info from a scraper's data models.

    Uses the searchable field metadata system to find fields annotated
    with DateRange, SetFilter, or UniqueMatch markers.

    Args:
        scraper_class: A scraper class that inherits from BaseScraper.

    Returns:
        Dict mapping model name to dict of filter types to field names.
        Example: {"CaseData": {"DateRange": ["date_filed"], "SetFilter": ["case_type"]}}
    """
    try:
        params = build_params_for_scraper(scraper_class)
    except Exception:
        return {}

    result: dict[str, dict[str, list[str]]] = {}

    for model_name, model_proxy in params.get_models().items():
        model_fields: dict[str, list[str]] = {
            "DateRange": [],
            "SetFilter": [],
            "UniqueMatch": [],
        }

        for (
            field_name,
            field_proxy,
        ) in model_proxy.get_searchable_fields().items():
            marker = field_proxy.marker
            if isinstance(marker, DateRange):
                model_fields["DateRange"].append(field_name)
            elif isinstance(marker, SetFilter):
                model_fields["SetFilter"].append(field_name)
            elif isinstance(marker, UniqueMatch):
                model_fields["UniqueMatch"].append(field_name)

        # Only include model if it has searchable fields
        if any(model_fields.values()):
            # Sort field names for consistent output
            for key in model_fields:
                model_fields[key] = sorted(model_fields[key])
            result[model_name] = model_fields

    return result


def discover_scrapers() -> list[dict]:
    """Find all new-architecture scraper classes.

    Walks the juriscraper.sd_scrapers.scrapers package tree and finds
    all classes that:
    - Inherit from BaseScraper
    - Have court_ids defined (non-empty)

    Returns:
        List of metadata dictionaries for each discovered scraper.
    """
    scrapers: list[dict] = []
    base_package = "juriscraper.sd_scrapers.scrapers"
    base_path = PROJECT_ROOT / "juriscraper" / "sd_scrapers" / "scrapers"

    if not base_path.exists():
        print(f"Warning: {base_path} not found")
        return scrapers

    # Import the base package first
    try:
        importlib.import_module(base_package)
    except ImportError as e:
        print(f"Warning: Could not import {base_package}: {e}")
        return scrapers

    # Walk all submodules
    for _importer, modname, ispkg in pkgutil.walk_packages(
        path=[str(base_path)],
        prefix=base_package + ".",
    ):
        if ispkg:
            continue

        try:
            module = importlib.import_module(modname)
        except Exception as e:
            print(f"Warning: Could not import {modname}: {e}")
            continue

        # Find scraper classes in this module
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and hasattr(obj, "court_ids")
                and getattr(obj, "court_ids", None)  # Non-empty
            ):
                metadata = extract_metadata(obj)
                if metadata:
                    scrapers.append(metadata)

    return scrapers


def extract_metadata(scraper_class: type) -> dict | None:
    """Extract metadata from a scraper class.

    Args:
        scraper_class: A scraper class with autodoc metadata.

    Returns:
        Dictionary of metadata, or None if required fields are missing.
    """
    court_ids: set[str] = getattr(scraper_class, "court_ids", set())
    if not court_ids:
        return None

    oldest = getattr(scraper_class, "oldest_record", None)
    status = getattr(scraper_class, "status", None)
    return_type_info = get_return_type_info(scraper_class)

    return {
        "scraper_id": scraper_class.__name__,
        "court_ids": sorted(court_ids),
        "court_url": getattr(scraper_class, "court_url", ""),
        "data_types": get_data_types(scraper_class),
        "searchability": get_searchability(scraper_class),
        "return_type": return_type_info.get("return_type", ""),
        "parent_model": return_type_info.get("parent_model", ""),
        "model_hierarchy": return_type_info.get("model_hierarchy", []),
        "status": status.value if status else "unknown",
        "version": getattr(scraper_class, "version", None) or "",
        "last_verified": getattr(scraper_class, "last_verified", None) or "",
        "oldest_record": oldest.isoformat() if oldest else None,
        "requires_auth": getattr(scraper_class, "requires_auth", False),
        "msec_per_request": getattr(
            scraper_class, "msec_per_request_rate_limit", None
        ),
        "module_path": scraper_class.__module__,
        "docstring": (scraper_class.__doc__ or "").strip(),
    }


def calculate_coverage(
    courts: dict, scrapers: list[dict]
) -> tuple[dict, dict]:
    """Calculate coverage statistics per jurisdiction.

    Coverage is calculated as:
        covered_court_types / total_court_types

    Where court_types = court × data_type combinations.

    Args:
        courts: The master court table from courts.toml.
        scrapers: List of scraper metadata dictionaries.

    Returns:
        Tuple of (jurisdiction statistics dict, court names dict).
    """
    # Build map of court_id -> set of scraped data types
    covered: dict[str, set[str]] = {}
    for scraper in scrapers:
        for court_id in scraper["court_ids"]:
            if court_id not in covered:
                covered[court_id] = set()
            covered[court_id].update(scraper["data_types"])

    # Calculate per-jurisdiction coverage
    jurisdictions: dict[str, dict] = {}
    court_names: dict[str, str] = {}
    for court_id, court_info in courts.get("courts", {}).items():
        jur = court_info.get("jurisdiction", "UNKNOWN")
        if jur not in jurisdictions:
            jurisdictions[jur] = {
                "total_court_types": 0,
                "covered_court_types": 0,
                "courts": [],
            }

        # Store court name
        court_names[court_id] = court_info.get("name", court_id)

        expected_types = set(court_info.get("data_types", []))
        jurisdictions[jur]["total_court_types"] += len(expected_types)

        covered_types = covered.get(court_id, set())
        jurisdictions[jur]["covered_court_types"] += len(
            expected_types & covered_types
        )
        jurisdictions[jur]["courts"].append(court_id)

    # Calculate percentages
    for _jur, stats in jurisdictions.items():
        if stats["total_court_types"] > 0:
            stats["coverage_pct"] = round(
                stats["covered_court_types"] / stats["total_court_types"], 3
            )
        else:
            stats["coverage_pct"] = 0.0
        # Sort courts for consistent output
        stats["courts"] = sorted(stats["courts"])

    return jurisdictions, court_names


def build_registry() -> dict:
    """Build the complete court registry.

    Returns:
        Registry dictionary ready for TOML serialization.
    """
    courts = load_court_table()
    scrapers = discover_scrapers()
    jurisdictions, court_names = calculate_coverage(courts, scrapers)

    # Count unique courts covered
    all_covered_courts = set()
    for scraper in scrapers:
        all_covered_courts.update(scraper["court_ids"])

    registry = {
        "meta": {
            "generated": date.today().isoformat(),
            "description": "Auto-generated court scraper registry",
        },
        "stats": {
            "total_scrapers": len(scrapers),
            "total_courts_known": len(courts.get("courts", {})),
            "total_courts_covered": len(all_covered_courts),
        },
        "scrapers": {s["scraper_id"]: s for s in scrapers},
        "jurisdictions": jurisdictions,
        "court_names": court_names,
    }

    return registry


def write_registry(registry: dict, output_path: Path) -> None:
    """Write registry to TOML file.

    Args:
        registry: The registry dictionary.
        output_path: Path to write the TOML file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        tomli_w.dump(registry, f)

    print(f"Wrote registry to {output_path}")


def main() -> int:
    """Main entry point."""
    print("Building court registry...")

    registry = build_registry()

    # Print summary
    stats = registry["stats"]
    print(f"  Scrapers found: {stats['total_scrapers']}")
    print(f"  Courts known: {stats['total_courts_known']}")
    print(f"  Courts covered: {stats['total_courts_covered']}")

    # Write output
    output_path = (
        PROJECT_ROOT / "docs" / "source" / "_generated" / "court_registry.toml"
    )
    write_registry(registry, output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
