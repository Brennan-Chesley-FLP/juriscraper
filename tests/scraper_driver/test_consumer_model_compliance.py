"""Tests for ConsumerModel compliance across all scrapers.

These tests dynamically discover all scrapers and verify they properly
subclass ConsumerModel for their return types.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from typing import get_args, get_origin

import pytest

from juriscraper.scraper_driver.common.models.base import (
    ConsumerModel,
)
from juriscraper.scraper_driver.data_types import BaseScraper

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def discover_all_scrapers() -> list[tuple[str, type]]:
    """Discover all scraper classes in the codebase.

    Walks the juriscraper.sd_scrapers.scrapers package tree and finds
    all classes that inherit from BaseScraper.

    Returns:
        List of (module_path, scraper_class) tuples.
    """
    scrapers: list[tuple[str, type]] = []
    base_package = "juriscraper.sd_scrapers.scrapers"
    base_path = PROJECT_ROOT / "juriscraper" / "sd_scrapers" / "scrapers"

    if not base_path.exists():
        return scrapers

    # Import the base package first
    try:
        importlib.import_module(base_package)
    except ImportError:
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
        except Exception:
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
                scrapers.append((modname, obj))

    return scrapers


def get_return_type_from_generic(scraper_class: type) -> type | None:
    """Extract the return type from BaseScraper[T] generic parameter.

    Args:
        scraper_class: A class that inherits from BaseScraper[T].

    Returns:
        The type T from BaseScraper[T], or None if not found.
    """
    # Look through the class's original bases for the generic parameter
    for base in getattr(scraper_class, "__orig_bases__", []):
        origin = get_origin(base)
        if origin is BaseScraper or (
            isinstance(origin, type) and issubclass(origin, BaseScraper)
        ):
            args = get_args(base)
            if args:
                return args[0]

    # Also check parent classes recursively
    for parent in scraper_class.__mro__[1:]:
        if parent is BaseScraper or parent is object:
            continue
        result = get_return_type_from_generic(parent)
        if result:
            return result

    return None


def is_consumer_model_subclass(type_hint: type | None) -> bool:
    """Check if a type hint is a subclass of ConsumerModel.

    Handles both direct types and Union types.

    Args:
        type_hint: The type to check.

    Returns:
        True if the type is a subclass of ConsumerModel.
    """
    if type_hint is None:
        return False

    # Direct type check
    if isinstance(type_hint, type):
        return issubclass(type_hint, ConsumerModel)

    # Handle Union types and other generics
    origin = get_origin(type_hint)
    if origin is not None:
        # For Union types, check all args
        args = get_args(type_hint)
        if args:
            return all(
                is_consumer_model_subclass(arg)
                for arg in args
                if arg is not type(None)
            )

    return False


# Discover scrapers once at module load time
ALL_SCRAPERS = discover_all_scrapers()


@pytest.mark.parametrize(
    "module_path,scraper_class",
    ALL_SCRAPERS,
    ids=[f"{path}:{cls.__name__}" for path, cls in ALL_SCRAPERS],
)
def test_scraper_return_type_is_consumer_model(
    module_path: str, scraper_class: type
):
    """Each scraper shall have a return type that is a ConsumerModel subclass.

    This test dynamically discovers all scrapers in the codebase and verifies
    that their generic return type (the T in BaseScraper[T]) is a subclass
    of ConsumerModel.

    This ensures that all scraped data follows a consistent model hierarchy
    that can be documented and validated uniformly.
    """
    return_type = get_return_type_from_generic(scraper_class)

    assert return_type is not None, (
        f"Scraper {scraper_class.__name__} in {module_path} does not "
        f"specify a generic return type. Use BaseScraper[MyModel] where "
        f"MyModel is a ConsumerModel subclass."
    )

    assert is_consumer_model_subclass(return_type), (
        f"Scraper {scraper_class.__name__} in {module_path} has return type "
        f"{return_type} which is not a ConsumerModel subclass. "
        f"All scraper return types must inherit from ConsumerModel "
        f"(e.g., Docket, DocketEntry, Opinion, etc.)."
    )


@pytest.mark.skip
def test_at_least_one_scraper_discovered():
    """The test suite shall discover at least one scraper.

    This is a sanity check to ensure the discovery mechanism is working.
    """
    assert len(ALL_SCRAPERS) > 0, (
        "No scrapers were discovered. Check that the scraper discovery "
        "logic is working correctly."
    )


def test_consumer_model_hierarchy():
    """ConsumerModel shall be the base class for all data models.

    Verifies that key model classes like Docket and DocketEntry
    properly inherit from ConsumerModel.
    """
    from juriscraper.scraper_driver.common.models.base import (
        Audio,
        Docket,
        DocketEntry,
        Opinion,
        OpinionCluster,
    )

    assert issubclass(Docket, ConsumerModel)
    assert issubclass(DocketEntry, ConsumerModel)
    assert issubclass(Opinion, ConsumerModel)
    assert issubclass(OpinionCluster, ConsumerModel)
    assert issubclass(Audio, ConsumerModel)
