"""Tests for searchable field metadata system.

This module tests the ability to annotate ScrapedData fields as searchable
and build params objects for configuring scraper filters.

Key behaviors tested:
- Marker classes (DateRange, SetFilter, UniqueMatch) can be applied to fields
- Runtime filter values can be set via attribute-style access
- BaseScraper.params() introspects generic type parameter(s)
- Multiple data models via Union types are supported
- Model and field can be set to None to disable filtering
"""

from datetime import date
from typing import Annotated

import pytest

from juriscraper.scraper_driver.common.data_models import ScrapedData
from juriscraper.scraper_driver.common.searchable import (
    DateRange,
    DateRangeFilter,
    SetFilter,
    SetFilterValue,
    UniqueMatch,
    UniqueMatchValue,
    build_params_for_scraper,
)
from juriscraper.scraper_driver.data_types import BaseScraper


class TestMarkerClasses:
    """Tests for marker classes used in field metadata."""

    def test_date_range_marker_is_frozen(self) -> None:
        """The DateRange marker shall be immutable."""
        marker = DateRange()
        assert marker == DateRange()

    def test_set_filter_marker_is_frozen(self) -> None:
        """The SetFilter marker shall be immutable."""
        marker = SetFilter()
        assert marker == SetFilter()

    def test_unique_match_marker_is_frozen(self) -> None:
        """The UniqueMatch marker shall be immutable."""
        marker = UniqueMatch()
        assert marker == UniqueMatch()


class TestFilterValueHolders:
    """Tests for runtime filter value holders."""

    def test_date_range_filter_defaults_to_none(self) -> None:
        """The DateRangeFilter shall default to None for both bounds."""
        filter_val = DateRangeFilter()
        assert filter_val.gte is None
        assert filter_val.lte is None
        assert not filter_val.is_set()

    def test_date_range_filter_is_set_with_gte(self) -> None:
        """The DateRangeFilter shall report is_set when gte is set."""
        filter_val = DateRangeFilter(gte=date(2024, 1, 1))
        assert filter_val.is_set()

    def test_date_range_filter_is_set_with_lte(self) -> None:
        """The DateRangeFilter shall report is_set when lte is set."""
        filter_val = DateRangeFilter(lte=date(2024, 12, 31))
        assert filter_val.is_set()

    def test_set_filter_value_defaults_to_empty(self) -> None:
        """The SetFilterValue shall default to an empty set."""
        filter_val = SetFilterValue()
        assert filter_val.values == set()
        assert not filter_val.is_set()

    def test_set_filter_value_is_set_with_values(self) -> None:
        """The SetFilterValue shall report is_set when values are present."""
        filter_val = SetFilterValue(values={"civil", "criminal"})
        assert filter_val.is_set()

    def test_unique_match_value_defaults_to_none(self) -> None:
        """The UniqueMatchValue shall default to None."""
        filter_val = UniqueMatchValue()
        assert filter_val.value is None
        assert not filter_val.is_set()

    def test_unique_match_value_is_set_with_value(self) -> None:
        """The UniqueMatchValue shall report is_set when value is present."""
        filter_val = UniqueMatchValue(value="2024-001")
        assert filter_val.is_set()


class TestFieldMetadataAnnotation:
    """Tests for annotating fields with searchable markers."""

    def test_date_range_field_detected(self) -> None:
        """The params builder shall detect DateRange annotated fields."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert "CaseData" in params.get_models()
        fields = params.CaseData.get_searchable_fields()
        assert "date_filed" in fields
        assert isinstance(fields["date_filed"].marker, DateRange)

    def test_set_filter_field_detected(self) -> None:
        """The params builder shall detect SetFilter annotated fields."""

        class CaseData(ScrapedData):
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        fields = params.CaseData.get_searchable_fields()
        assert "case_type" in fields
        assert isinstance(fields["case_type"].marker, SetFilter)

    def test_unique_match_field_detected(self) -> None:
        """The params builder shall detect UniqueMatch annotated fields."""

        class CaseData(ScrapedData):
            docket_number: Annotated[str, UniqueMatch()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        fields = params.CaseData.get_searchable_fields()
        assert "docket_number" in fields
        assert isinstance(fields["docket_number"].marker, UniqueMatch)

    def test_non_searchable_fields_ignored(self) -> None:
        """The params builder shall ignore fields without searchable annotation."""

        class CaseData(ScrapedData):
            case_name: str
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        fields = params.CaseData.get_searchable_fields()
        assert "case_name" not in fields
        assert "date_filed" in fields


class TestAttributeStyleAccess:
    """Tests for attribute-style access to filter values."""

    def test_date_range_gte_access(self) -> None:
        """The params shall allow setting gte via attribute access."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.date_filed.gte = date(2024, 1, 1)

        assert params.CaseData.date_filed.gte == date(2024, 1, 1)
        assert params.CaseData.date_filed.lte is None

    def test_date_range_lte_access(self) -> None:
        """The params shall allow setting lte via attribute access."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.date_filed.lte = date(2024, 12, 31)

        assert params.CaseData.date_filed.lte == date(2024, 12, 31)
        assert params.CaseData.date_filed.gte is None

    def test_set_filter_values_access(self) -> None:
        """The params shall allow setting values via attribute access."""

        class CaseData(ScrapedData):
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_type.values = {"civil", "criminal"}

        assert params.CaseData.case_type.values == {"civil", "criminal"}

    def test_unique_match_value_access(self) -> None:
        """The params shall allow setting value via attribute access."""

        class CaseData(ScrapedData):
            docket_number: Annotated[str, UniqueMatch()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.docket_number.value = "2024-001"

        assert params.CaseData.docket_number.value == "2024-001"

    def test_wrong_attribute_raises_error(self) -> None:
        """Accessing wrong attribute type shall raise AttributeError."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)

        # Try to access SetFilter attribute on DateRange field
        try:
            _ = params.CaseData.date_filed.values
            pytest.fail("Expected AttributeError")
        except AttributeError as e:
            assert "SetFilter" in str(e)


class TestModelDisabling:
    """Tests for disabling data models via None."""

    def test_model_enabled_by_default(self) -> None:
        """Data models shall be enabled by default."""

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert params.CaseData and params.CaseData.enabled is True

    def test_model_can_be_disabled(self) -> None:
        """Data models shall be disableable by setting to None."""

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData = None

        assert params.CaseData is None or params.CaseData.enabled is False

    def test_get_enabled_models_filters_disabled(self) -> None:
        """get_enabled_models shall exclude disabled models."""

        class CaseData(ScrapedData):
            docket: str

        class OralArgument(ScrapedData):
            audio_url: str

        class TestScraper(BaseScraper[CaseData | OralArgument]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData = None

        enabled = params.get_enabled_models()
        assert "CaseData" not in enabled
        assert "OralArgument" in enabled


class TestUnionTypes:
    """Tests for scrapers with multiple return types via Union."""

    def test_union_types_detected(self) -> None:
        """The params builder shall detect all types in a Union."""

        class CaseData(ScrapedData):
            docket: str

        class OralArgument(ScrapedData):
            audio_url: str

        class TestScraper(BaseScraper[CaseData | OralArgument]):
            pass

        params = build_params_for_scraper(TestScraper)
        models = params.get_models()

        assert "CaseData" in models
        assert "OralArgument" in models

    def test_union_types_independent_filters(self) -> None:
        """Each Union type shall have independent filter settings."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class OralArgument(ScrapedData):
            date_heard: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData | OralArgument]):
            pass

        params = build_params_for_scraper(TestScraper)

        # Set different filters on each type
        params.CaseData.date_filed.gte = date(2024, 1, 1)
        params.OralArgument.date_heard.gte = date(2023, 6, 1)

        assert params.CaseData.date_filed.gte == date(2024, 1, 1)
        assert params.OralArgument.date_heard.gte == date(2023, 6, 1)


class TestBaseScraperParamsMethod:
    """Tests for BaseScraper.params() classmethod."""

    def test_params_method_exists(self) -> None:
        """BaseScraper shall have a params() classmethod."""

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        # Should be callable as classmethod
        params = TestScraper.params()
        assert params is not None

    def test_params_returns_correct_models(self) -> None:
        """BaseScraper.params() shall return models matching generic type."""

        class CaseData(ScrapedData):
            docket: str
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = TestScraper.params()
        assert "CaseData" in params.get_models()
        assert "date_filed" in params.CaseData.get_searchable_fields()

    def test_params_with_multiple_types(self) -> None:
        """BaseScraper.params() shall handle Union types."""

        class CaseData(ScrapedData):
            docket: str

        class DocketEntry(ScrapedData):
            entry_number: int

        class TestScraper(BaseScraper[CaseData | DocketEntry]):
            pass

        params = TestScraper.params()
        models = params.get_models()

        assert "CaseData" in models
        assert "DocketEntry" in models


class TestActiveFilters:
    """Tests for retrieving active filters."""

    def test_get_active_filters_empty_initially(self) -> None:
        """get_active_filters shall return empty dict when no filters set."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        active = params.CaseData.get_active_filters()

        assert active == {}

    def test_get_active_filters_returns_set_filters(self) -> None:
        """get_active_filters shall return only fields with values set."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.date_filed.gte = date(2024, 1, 1)

        active = params.CaseData.get_active_filters()

        assert "date_filed" in active
        assert "case_type" not in active


class TestFieldProxyIsSet:
    """Tests for FieldProxy.is_set() method."""

    def test_date_range_is_set_false_initially(self) -> None:
        """DateRange field shall report is_set=False initially."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert not params.CaseData.date_filed.is_set()

    def test_date_range_is_set_true_after_gte(self) -> None:
        """DateRange field shall report is_set=True after setting gte."""

        class CaseData(ScrapedData):
            date_filed: Annotated[date, DateRange()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.date_filed.gte = date(2024, 1, 1)

        assert params.CaseData.date_filed.is_set()

    def test_set_filter_is_set_false_initially(self) -> None:
        """SetFilter field shall report is_set=False initially."""

        class CaseData(ScrapedData):
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert not params.CaseData.case_type.is_set()

    def test_set_filter_is_set_true_after_values(self) -> None:
        """SetFilter field shall report is_set=True after setting values."""

        class CaseData(ScrapedData):
            case_type: Annotated[str, SetFilter()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_type.values = {"civil"}

        assert params.CaseData.case_type.is_set()

    def test_unique_match_is_set_false_initially(self) -> None:
        """UniqueMatch field shall report is_set=False initially."""

        class CaseData(ScrapedData):
            docket: Annotated[str, UniqueMatch()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert not params.CaseData.docket.is_set()

    def test_unique_match_is_set_true_after_value(self) -> None:
        """UniqueMatch field shall report is_set=True after setting value."""

        class CaseData(ScrapedData):
            docket: Annotated[str, UniqueMatch()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.docket.value = "2024-001"

        assert params.CaseData.docket.is_set()


class TestErrorHandling:
    """Tests for error handling in the searchable system."""

    def test_unknown_model_raises_attribute_error(self) -> None:
        """Accessing unknown model shall raise AttributeError."""

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)

        try:
            _ = params.UnknownModel
            pytest.fail("Expected AttributeError")
        except AttributeError as e:
            assert "UnknownModel" in str(e)

    def test_unknown_field_raises_attribute_error(self) -> None:
        """Accessing unknown field shall raise AttributeError."""

        class CaseData(ScrapedData):
            docket: Annotated[str, UniqueMatch()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)

        try:
            _ = params.CaseData.unknown_field
            pytest.fail("Expected AttributeError")
        except AttributeError as e:
            assert "unknown_field" in str(e)

    def test_invalid_model_assignment_raises_value_error(self) -> None:
        """Assigning non-None value to model shall raise ValueError."""

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)

        try:
            params.CaseData = "invalid"  # type: ignore
            pytest.fail("Expected ValueError")
        except ValueError as e:
            assert "None" in str(e)
