"""Searchable field metadata for ScrapedData models.

This module provides a system for annotating Pydantic model fields as
searchable, allowing scrapers to advertise which fields can be filtered
when querying for data.

Three filter types are supported:
- DateRange: Filter by date range (gte/lte)
- SetFilter: Filter by a set of allowed values
- UniqueMatch: Filter by exact match (single value)

Example usage in a ScrapedData model:

    from typing import Annotated

    class CaseData(ScrapedData):
        date_filed: Annotated[date, DateRange()]
        case_type: Annotated[str, SetFilter()]
        docket_number: Annotated[str, UniqueMatch()]

Example usage for querying:

    params = MyScraper.params()
    params.CaseData.date_filed.gte = date(2000, 1, 1)
    params.CaseData.case_type.values = {"civil", "criminal"}
    params.CaseData.docket_number.value = "2024-001"

    # Set to None to disable filtering for that field
    params.CaseData.date_filed = None

    # Set model to None to not return that data type
    params.CaseData = None
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    pass

# =============================================================================
# Marker Classes (used in Field metadata)
# =============================================================================


@dataclass(frozen=True)
class DateRange:
    """Marker for date range filtering.

    When used with typing.Annotated, indicates that the field can be
    filtered using greater-than-or-equal (gte) and/or less-than-or-equal
    (lte) date bounds.

    Example:
        date_filed: Annotated[date, DateRange()]
    """

    pass


@dataclass(frozen=True)
class SetFilter:
    """Marker for set-based filtering.

    When used with typing.Annotated, indicates that the field can be
    filtered by providing a set of allowed values.

    Example:
        case_type: Annotated[str, SetFilter()]
    """

    pass


@dataclass(frozen=True)
class UniqueMatch:
    """Marker for exact match filtering.

    When used with typing.Annotated, indicates that the field can be
    filtered by providing a single exact value to match.

    Example:
        docket_number: Annotated[str, UniqueMatch()]
    """

    pass


# Type for any searchable marker
SearchableMarker = DateRange | SetFilter | UniqueMatch


# =============================================================================
# Runtime Filter Value Holders
# =============================================================================


@dataclass
class DateRangeFilter:
    """Runtime filter values for DateRange fields.

    Attributes:
        gte: Minimum date (inclusive). None means no lower bound.
        lte: Maximum date (inclusive). None means no upper bound.
    """

    gte: date | None = None
    lte: date | None = None

    def is_set(self) -> bool:
        """Return True if any filter value is set."""
        return self.gte is not None or self.lte is not None


@dataclass
class SetFilterValue:
    """Runtime filter values for SetFilter fields.

    Attributes:
        values: Set of allowed values. Empty set means no filtering.
    """

    values: set[Any] = field(default_factory=set)

    def is_set(self) -> bool:
        """Return True if any filter values are set."""
        return len(self.values) > 0


@dataclass
class UniqueMatchValue:
    """Runtime filter value for UniqueMatch fields.

    Attributes:
        value: Exact value to match. None means no filtering.
    """

    value: Any = None

    def is_set(self) -> bool:
        """Return True if a filter value is set."""
        return self.value is not None


# =============================================================================
# Field Proxy (for attribute-style access)
# =============================================================================

T = TypeVar("T")


class FieldProxy(Generic[T]):
    """Proxy for accessing a searchable field's filter.

    Allows attribute-style access like:
        params.CaseData.date_filed.gte = date(2024, 1, 1)
    """

    def __init__(
        self,
        field_name: str,
        marker: SearchableMarker,
        filter_value: DateRangeFilter | SetFilterValue | UniqueMatchValue,
    ) -> None:
        self._field_name = field_name
        self._marker = marker
        self._filter_value = filter_value

    @property
    def field_name(self) -> str:
        """Return the field name."""
        return self._field_name

    @property
    def marker(self) -> SearchableMarker:
        """Return the searchable marker type."""
        return self._marker

    @property
    def filter(self) -> DateRangeFilter | SetFilterValue | UniqueMatchValue:
        """Return the filter value holder."""
        return self._filter_value

    # DateRangeFilter attributes
    @property
    def gte(self) -> date | None:
        """Get the gte date bound (DateRange only)."""
        if not isinstance(self._filter_value, DateRangeFilter):
            raise AttributeError(
                f"Field '{self._field_name}' is not a DateRange field"
            )
        return self._filter_value.gte

    @gte.setter
    def gte(self, value: date | None) -> None:
        """Set the gte date bound (DateRange only)."""
        if not isinstance(self._filter_value, DateRangeFilter):
            raise AttributeError(
                f"Field '{self._field_name}' is not a DateRange field"
            )
        self._filter_value.gte = value

    @property
    def lte(self) -> date | None:
        """Get the lte date bound (DateRange only)."""
        if not isinstance(self._filter_value, DateRangeFilter):
            raise AttributeError(
                f"Field '{self._field_name}' is not a DateRange field"
            )
        return self._filter_value.lte

    @lte.setter
    def lte(self, value: date | None) -> None:
        """Set the lte date bound (DateRange only)."""
        if not isinstance(self._filter_value, DateRangeFilter):
            raise AttributeError(
                f"Field '{self._field_name}' is not a DateRange field"
            )
        self._filter_value.lte = value

    # SetFilterValue attributes
    @property
    def values(self) -> set[Any]:
        """Get the allowed values set (SetFilter only)."""
        if not isinstance(self._filter_value, SetFilterValue):
            raise AttributeError(
                f"Field '{self._field_name}' is not a SetFilter field"
            )
        return self._filter_value.values

    @values.setter
    def values(self, value: set[Any]) -> None:
        """Set the allowed values set (SetFilter only)."""
        if not isinstance(self._filter_value, SetFilterValue):
            raise AttributeError(
                f"Field '{self._field_name}' is not a SetFilter field"
            )
        self._filter_value.values = value

    # UniqueMatchValue attributes
    @property
    def value(self) -> Any:
        """Get the exact match value (UniqueMatch only)."""
        if not isinstance(self._filter_value, UniqueMatchValue):
            raise AttributeError(
                f"Field '{self._field_name}' is not a UniqueMatch field"
            )
        return self._filter_value.value

    @value.setter
    def value(self, val: Any) -> None:
        """Set the exact match value (UniqueMatch only)."""
        if not isinstance(self._filter_value, UniqueMatchValue):
            raise AttributeError(
                f"Field '{self._field_name}' is not a UniqueMatch field"
            )
        self._filter_value.value = val

    def is_set(self) -> bool:
        """Return True if any filter value is configured."""
        return self._filter_value.is_set()


# =============================================================================
# Model Proxy (for accessing fields on a data model)
# =============================================================================


class ModelProxy:
    """Proxy for accessing searchable fields on a data model.

    Allows attribute-style access like:
        params.CaseData.date_filed.gte = date(2024, 1, 1)

    Can be set to None to indicate "don't return this data type".
    """

    def __init__(self, model_class: type[BaseModel]) -> None:
        self._model_class = model_class
        self._enabled: bool = True
        self._fields: dict[str, FieldProxy[Any]] = {}

        # Introspect the model for searchable fields
        self._init_searchable_fields()

    def _init_searchable_fields(self) -> None:
        """Initialize field proxies for all searchable fields in the model.

        Looks for searchable markers in typing.Annotated metadata.
        For example: date_filed: Annotated[date, DateRange()]
        """
        # Get type hints with Annotated metadata preserved
        try:
            hints = get_type_hints(self._model_class, include_extras=True)
        except Exception:
            # If type hints can't be resolved, skip
            return

        for field_name in self._model_class.model_fields:
            if field_name not in hints:
                continue

            type_hint = hints[field_name]

            # Check if this is an Annotated type
            if get_origin(type_hint) is not Annotated:
                continue

            # Get the metadata from Annotated[T, *metadata]
            args = get_args(type_hint)
            if len(args) < 2:
                continue

            # Look for a searchable marker in the metadata
            marker: SearchableMarker | None = None
            for arg in args[1:]:  # Skip first arg (the actual type)
                if isinstance(arg, DateRange | SetFilter | UniqueMatch):
                    marker = arg
                    break

            if marker is None:
                continue

            # Create appropriate filter value holder based on marker type
            if isinstance(marker, DateRange):
                filter_value: (
                    DateRangeFilter | SetFilterValue | UniqueMatchValue
                ) = DateRangeFilter()
            elif isinstance(marker, SetFilter):
                filter_value = SetFilterValue()
            elif isinstance(marker, UniqueMatch):
                filter_value = UniqueMatchValue()
            else:
                # Unknown marker type, skip
                continue

            self._fields[field_name] = FieldProxy(
                field_name=field_name,
                marker=marker,
                filter_value=filter_value,
            )

    @property
    def model_class(self) -> type[BaseModel]:
        """Return the underlying model class."""
        return self._model_class

    @property
    def enabled(self) -> bool:
        """Return whether this data type is enabled for retrieval."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set whether this data type is enabled for retrieval."""
        self._enabled = value

    def __getattr__(self, name: str) -> FieldProxy[Any]:
        """Get a field proxy by name."""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' has no attribute '{name}'"
            )
        if name in self._fields:
            return self._fields[name]
        raise AttributeError(
            f"Model '{self._model_class.__name__}' has no searchable field '{name}'"
        )

    def get_searchable_fields(self) -> dict[str, FieldProxy[Any]]:
        """Return all searchable field proxies."""
        return self._fields.copy()

    def get_active_filters(self) -> dict[str, FieldProxy[Any]]:
        """Return only fields that have active filters set."""
        return {
            name: proxy
            for name, proxy in self._fields.items()
            if proxy.is_set()
        }


# =============================================================================
# Params Container (root object returned by BaseScraper.params())
# =============================================================================


class ScraperParams:
    """Container for scraper parameters built from data model annotations.

    Provides attribute-style access to filter parameters for each data type
    a scraper can return.

    Example:
        params = MyScraper.params()
        params.CaseData.date_filed.gte = date(2024, 1, 1)
        params.OralArgumentData = None  # Don't return this type
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelProxy] = {}

    def _add_model(self, model_class: type[BaseModel]) -> None:
        """Add a data model to the params container."""
        self._models[model_class.__name__] = ModelProxy(model_class)

    def __getattr__(self, name: str) -> ModelProxy:
        """Get a model proxy by class name."""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' has no attribute '{name}'"
            )
        if name in self._models:
            return self._models[name]
        raise AttributeError(f"Scraper has no data model '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Allow setting model to None to disable it."""
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if name in self._models:
            if value is None:
                self._models[name].enabled = False
            else:
                raise ValueError(
                    f"Model proxy can only be set to None (got {type(value).__name__})"
                )
        else:
            object.__setattr__(self, name, value)

    def get_models(self) -> dict[str, ModelProxy]:
        """Return all model proxies."""
        return self._models.copy()

    def get_enabled_models(self) -> dict[str, ModelProxy]:
        """Return only enabled model proxies."""
        return {
            name: proxy
            for name, proxy in self._models.items()
            if proxy.enabled
        }


# =============================================================================
# Utility Functions
# =============================================================================


def _extract_union_args(type_hint: Any) -> list[type]:
    """Extract concrete types from a Union or UnionType.

    Args:
        type_hint: A type hint that may be a Union or UnionType.

    Returns:
        List of concrete types from the union, or [type_hint] if not a union.
    """
    origin = get_origin(type_hint)

    # Handle typing.Union
    if origin is not None:
        # For Union types, get_origin returns Union
        # Need to check if it's actually a Union
        try:
            from typing import Union

            if origin is Union:
                return list(get_args(type_hint))
        except ImportError:
            pass

    # Handle types.UnionType (Python 3.10+ X | Y syntax)
    try:
        from types import UnionType

        if isinstance(type_hint, UnionType):
            return list(get_args(type_hint))
    except ImportError:
        pass

    # Not a union, return as-is
    return [type_hint]


def build_params_for_scraper(scraper_class: type) -> ScraperParams:
    """Build a ScraperParams instance from a scraper class.

    Introspects the scraper's generic type parameter to find data models,
    then builds proxies for each model's searchable fields.

    Args:
        scraper_class: A scraper class that inherits from BaseScraper[T]

    Returns:
        A ScraperParams instance with model proxies for each data type.
    """
    params = ScraperParams()

    # Get the original bases to find BaseScraper[T]
    for base in getattr(scraper_class, "__orig_bases__", []):
        origin = get_origin(base)
        if origin is None:
            continue

        # Check if this is BaseScraper or a subclass
        # We look for any Generic base with type args
        args = get_args(base)
        if not args:
            continue

        # Process each type argument (could be a Union)
        for arg in args:
            # Extract all types from potential Union
            types = _extract_union_args(arg)
            for t in types:
                # Skip non-class types (like None, forward refs)
                if isinstance(t, type) and issubclass(t, BaseModel):
                    params._add_model(t)

    return params
