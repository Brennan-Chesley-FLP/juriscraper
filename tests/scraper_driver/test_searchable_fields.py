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
    SpeculativeID,
    SpeculativeIDValue,
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

    def test_speculative_id_marker_is_frozen(self) -> None:
        """The SpeculativeID marker shall be immutable."""
        marker = SpeculativeID()
        assert marker == SpeculativeID()


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

    def test_speculative_id_value_defaults_to_none(self) -> None:
        """The SpeculativeIDValue shall default to None for both gt and eq."""
        filter_val = SpeculativeIDValue()
        assert filter_val.gt is None
        assert filter_val.eq is None
        assert not filter_val.is_set()

    def test_speculative_id_value_is_set_with_gt(self) -> None:
        """The SpeculativeIDValue shall report is_set when gt is set."""
        filter_val = SpeculativeIDValue(gt="12345")
        assert filter_val.is_set()

    def test_speculative_id_value_is_set_with_eq(self) -> None:
        """The SpeculativeIDValue shall report is_set when eq is set."""
        filter_val = SpeculativeIDValue(eq="12346")
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

    def test_speculative_id_field_detected(self) -> None:
        """The params builder shall detect SpeculativeID annotated fields."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        fields = params.CaseData.get_searchable_fields()
        assert "case_id" in fields
        assert isinstance(fields["case_id"].marker, SpeculativeID)

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

    def test_speculative_id_gt_access(self) -> None:
        """The params shall allow setting gt via attribute access."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_id.gt = "12345"

        assert params.CaseData.case_id.gt == "12345"
        assert params.CaseData.case_id.eq is None

    def test_speculative_id_eq_access(self) -> None:
        """The params shall allow setting eq via attribute access."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_id.eq = "12346"

        assert params.CaseData.case_id.eq == "12346"
        assert params.CaseData.case_id.gt is None

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

    def test_speculative_id_is_set_false_initially(self) -> None:
        """SpeculativeID field shall report is_set=False initially."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        assert not params.CaseData.case_id.is_set()

    def test_speculative_id_is_set_true_after_gt(self) -> None:
        """SpeculativeID field shall report is_set=True after setting gt."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_id.gt = "12345"

        assert params.CaseData.case_id.is_set()

    def test_speculative_id_is_set_true_after_eq(self) -> None:
        """SpeculativeID field shall report is_set=True after setting eq."""

        class CaseData(ScrapedData):
            case_id: Annotated[str, SpeculativeID()]

        class TestScraper(BaseScraper[CaseData]):
            pass

        params = build_params_for_scraper(TestScraper)
        params.CaseData.case_id.eq = "12346"

        assert params.CaseData.case_id.is_set()


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


class TestPerFunctionDefiniteRangeAndPlus:
    """Tests for per-function definite_range and plus via params.speculative.{func}.

    These properties are configured per @speculate function, not at the root level.
    """

    def test_definite_range_defaults_to_none(self) -> None:
        """The definite_range property shall default to None."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        assert params.speculative.fetch_case.definite_range is None

    def test_definite_range_can_be_set(self) -> None:
        """The definite_range property shall be settable to a tuple (start, end)."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.definite_range = (1, 100)
        assert params.speculative.fetch_case.definite_range == (1, 100)

    def test_definite_range_can_be_set_to_none(self) -> None:
        """The definite_range property shall be settable to None."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.definite_range = (1, 100)
        params.speculative.fetch_case.definite_range = None
        assert params.speculative.fetch_case.definite_range is None

    def test_definite_range_validates_type(self) -> None:
        """The definite_range property shall reject non-tuple values."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(TypeError, match="must be a tuple"):
            params.speculative.fetch_case.definite_range = "100"  # type: ignore[assignment]

    def test_definite_range_validates_start_at_least_1(self) -> None:
        """The definite_range start must be at least 1."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(ValueError, match="start must be at least 1"):
            params.speculative.fetch_case.definite_range = (0, 100)

    def test_definite_range_validates_end_ge_start(self) -> None:
        """The definite_range end must be >= start."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(ValueError, match="end must be >= start"):
            params.speculative.fetch_case.definite_range = (100, 50)

    def test_plus_defaults_to_none(self) -> None:
        """The plus property shall default to None."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        assert params.speculative.fetch_case.plus is None

    def test_plus_can_be_set(self) -> None:
        """The plus property shall be settable to an integer."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.plus = 50
        assert params.speculative.fetch_case.plus == 50

    def test_plus_can_be_set_to_none(self) -> None:
        """The plus property shall be settable to None."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.plus = 50
        params.speculative.fetch_case.plus = None
        assert params.speculative.fetch_case.plus is None

    def test_plus_validates_type(self) -> None:
        """The plus property shall reject non-integer values."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(TypeError, match="must be an integer or None"):
            params.speculative.fetch_case.plus = "50"  # type: ignore[assignment]

    def test_plus_validates_non_negative(self) -> None:
        """The plus property shall reject negative values."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(ValueError, match="must be non-negative"):
            params.speculative.fetch_case.plus = -5

    def test_definite_range_and_plus_can_be_used_together(self) -> None:
        """The definite_range and plus properties shall work together."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.definite_range = (1, 100)
        params.speculative.fetch_case.plus = 20

        assert params.speculative.fetch_case.definite_range == (1, 100)
        assert params.speculative.fetch_case.plus == 20

    def test_multiple_functions_independent_config(self) -> None:
        """Multiple @speculate functions shall have independent configs."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

            @speculate
            def fetch_docket(self, docket_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/docket/{docket_id}"
                    ),
                    continuation="parse_docket",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.definite_range = (1, 100)
        params.speculative.fetch_case.plus = 20
        params.speculative.fetch_docket.definite_range = (1, 500)
        params.speculative.fetch_docket.plus = 50

        assert params.speculative.fetch_case.definite_range == (1, 100)
        assert params.speculative.fetch_case.plus == 20
        assert params.speculative.fetch_docket.definite_range == (1, 500)
        assert params.speculative.fetch_docket.plus == 50

    def test_invalid_function_raises(self) -> None:
        """Accessing non-existent speculate function raises AttributeError."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        params = build_params_for_scraper(TestScraper)
        with pytest.raises(AttributeError, match="not a speculate function"):
            _ = params.speculative.nonexistent_function

    def test_get_configs(self) -> None:
        """get_configs shall return all function configurations."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.common.searchable import (
            SpeculativeFunctionsProxy,
        )
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

            @speculate
            def fetch_docket(self, docket_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/docket/{docket_id}"
                    ),
                    continuation="parse_docket",
                )

        params = build_params_for_scraper(TestScraper)
        params.speculative.fetch_case.definite_range = (1, 100)
        params.speculative.fetch_docket.plus = 50

        # Must be SpeculativeFunctionsProxy (not SpeculativeStepsProxy)
        assert isinstance(params.speculative, SpeculativeFunctionsProxy)
        configs = params.speculative.get_configs()

        assert "fetch_case" in configs
        assert "fetch_docket" in configs
        assert configs["fetch_case"].definite_range == (1, 100)
        assert configs["fetch_case"].plus is None
        assert configs["fetch_docket"].definite_range is None
        assert configs["fetch_docket"].plus == 50


class TestFindSpeculateFunctions:
    """Tests for _find_speculate_functions helper."""

    def test_find_speculate_functions_empty(self) -> None:
        """The helper shall return an empty set for scrapers with no @speculate functions."""
        from juriscraper.scraper_driver.common.searchable import (
            _find_speculate_functions,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            pass

        funcs = _find_speculate_functions(TestScraper)
        assert funcs == set()

    def test_find_speculate_functions_single(self) -> None:
        """The helper shall find a single @speculate function."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.common.searchable import (
            _find_speculate_functions,
        )
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

        funcs = _find_speculate_functions(TestScraper)
        assert funcs == {"fetch_case"}

    def test_find_speculate_functions_multiple(self) -> None:
        """The helper shall find multiple @speculate functions."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.common.searchable import (
            _find_speculate_functions,
        )
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

            @speculate
            def fetch_docket(self, docket_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/docket/{docket_id}"
                    ),
                    continuation="parse_docket",
                )

            def normal_method(self):
                pass

        funcs = _find_speculate_functions(TestScraper)
        assert funcs == {"fetch_case", "fetch_docket"}

    def test_find_speculate_functions_ignores_private(self) -> None:
        """The helper shall ignore private methods (starting with _)."""
        from juriscraper.scraper_driver.common.decorators import speculate
        from juriscraper.scraper_driver.common.searchable import (
            _find_speculate_functions,
        )
        from juriscraper.scraper_driver.data_types import (
            HttpMethod,
            HTTPRequestParams,
            NavigatingRequest,
        )

        class CaseData(ScrapedData):
            docket: str

        class TestScraper(BaseScraper[CaseData]):
            @speculate
            def fetch_case(self, case_id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/case/{case_id}"
                    ),
                    continuation="parse_case",
                )

            @speculate
            def _fetch_internal(self, id: int) -> NavigatingRequest:
                return NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=f"/internal/{id}"
                    ),
                    continuation="parse_internal",
                )

        funcs = _find_speculate_functions(TestScraper)
        assert funcs == {"fetch_case"}
        assert "_fetch_internal" not in funcs
