"""Tests for :mod:`juriscraper.state.common.params`.

Covers :class:`InferrableDateRange` (relative-offset shorthand resolved
against the :data:`ANCHOR_DATE` context var) and
:class:`PersistedSpeculativeRange` (``[key]`` references resolved against the
:data:`SPEC_KV_STORE` context var). No network access.

Run:
    uv run python -m pytest juriscraper/state/common/test_params.py
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from jkent.common.param_models import DateRange, SpeculativeRange
from pydantic import BaseModel, ValidationError

from .params import (
    ANCHOR_DATE,
    SPEC_KV_STORE,
    CourtRange,
    InferrableDateRange,
    PersistedSpeculativeRange,
    SpecKVStore,
    YearlySpeculativeRange,
    anchor_date,
    spec_kv_store,
)

#: Fixed anchor used across the shorthand tests. Matches the examples in the
#: class docstring so the two never drift apart.
ANCHOR = date(2026, 7, 1)


def parse(shorthand: str) -> InferrableDateRange:
    """Validate ``shorthand`` against the :data:`ANCHOR` date."""
    with anchor_date(ANCHOR):
        return InferrableDateRange.model_validate(shorthand)


@pytest.mark.parametrize(
    ("shorthand", "start", "end"),
    [
        # The three examples from the design request.
        ("-4d", date(2026, 6, 27), date(2026, 7, 1)),
        ("-3d,+1d", date(2026, 6, 28), date(2026, 7, 2)),
        ("-1d,-4d", date(2026, 6, 27), date(2026, 6, 30)),
        # Single offset pairs with the anchor (implicit +0d).
        ("+0d", ANCHOR, ANCHOR),
        ("-0d", ANCHOR, ANCHOR),
        ("+7d", date(2026, 7, 1), date(2026, 7, 8)),
        # Weeks.
        ("-1w,+1w", date(2026, 6, 24), date(2026, 7, 8)),
        ("-2w", date(2026, 6, 17), date(2026, 7, 1)),
        # Months — calendar arithmetic, not fixed day counts.
        ("-1m", date(2026, 6, 1), date(2026, 7, 1)),
        ("-1m,+1m", date(2026, 6, 1), date(2026, 8, 1)),
        # Years, written high-then-low to prove reordering.
        ("+1y,-1y", date(2025, 7, 1), date(2027, 7, 1)),
        # Whitespace around and between tokens is tolerated.
        ("  -3d , +1d  ", date(2026, 6, 28), date(2026, 7, 2)),
    ],
)
def test_shorthand_expands_to_ordered_range(
    shorthand: str, start: date, end: date
) -> None:
    dr = parse(shorthand)
    assert (dr.start, dr.end) == (start, end)
    # start is always the earlier bound regardless of how it was written.
    assert dr.start <= dr.end


def test_single_offset_pairs_with_anchor() -> None:
    """A lone offset ranges between the target date and the anchor itself."""
    dr = parse("-4d")
    assert dr.end == ANCHOR
    assert dr.start == ANCHOR - (ANCHOR - date(2026, 6, 27))


def test_reordering_is_symmetric() -> None:
    """Swapping the two offsets yields the same range."""
    assert parse("-1d,-4d").model_dump() == parse("-4d,-1d").model_dump()


def test_month_arithmetic_clamps_to_end_of_month() -> None:
    """``relativedelta`` clamps overflowing days; ``-1m`` off Mar 31 is Feb 28."""
    with anchor_date(date(2026, 3, 31)):
        dr = InferrableDateRange.model_validate("-1m")
    assert dr.start == date(2026, 2, 28)
    assert dr.end == date(2026, 3, 31)


def test_year_arithmetic_handles_leap_day() -> None:
    """``+1y`` off a leap day clamps Feb 29 -> Feb 28 in a common year."""
    with anchor_date(date(2024, 2, 29)):
        dr = InferrableDateRange.model_validate("+1y")
    assert dr.start == date(2024, 2, 29)
    assert dr.end == date(2025, 2, 28)


def test_full_object_still_validates_like_daterange() -> None:
    """A ``{start, end}`` mapping bypasses the shorthand path entirely."""
    dr = InferrableDateRange.model_validate(
        {"start": "2020-01-01", "end": "2020-02-01"}
    )
    assert dr.start == date(2020, 1, 1)
    assert dr.end == date(2020, 2, 1)


def test_is_a_daterange() -> None:
    assert isinstance(parse("-4d"), DateRange)


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "4d",  # missing sign
        "-4",  # missing unit
        "-4x",  # bad unit
        "-4 d",  # internal space inside a token
        "garbage",
        "-3d,+1d,+2d",  # three offsets
        "-3d;+1d",  # wrong separator
    ],
)
def test_invalid_shorthand_raises(bad: str) -> None:
    with pytest.raises(ValidationError):
        parse(bad)


def test_defaults_to_today_when_anchor_unset() -> None:
    """With no anchor in context, offsets resolve against today()."""
    assert ANCHOR_DATE.get() is None  # nothing leaked from other tests
    dr = InferrableDateRange.model_validate("+0d")
    assert dr.start == date.today()
    assert dr.end == date.today()


def test_anchor_date_restores_previous_value_on_exit() -> None:
    assert ANCHOR_DATE.get() is None
    with anchor_date(ANCHOR):
        assert ANCHOR_DATE.get() == ANCHOR
    assert ANCHOR_DATE.get() is None


def test_anchor_var_flows_into_nested_field_validation() -> None:
    """The context var reaches a shorthand nested inside another model.

    This is the payoff of using a context var over Pydantic's ``info.context``:
    a scraper param model validated via ``model_validate`` can carry an
    ``InferrableDateRange`` field without threading ``context=`` down to it.
    """

    class Params(BaseModel):
        date_range: InferrableDateRange

    with anchor_date(ANCHOR):
        params = Params.model_validate({"date_range": "-4d"})
    assert params.date_range.start == date(2026, 6, 27)
    assert params.date_range.end == ANCHOR


# --------------------------------------------------------------------------
# PersistedSpeculativeRange
# --------------------------------------------------------------------------


class DictStore:
    """Minimal in-memory :class:`SpecKVStore` for tests."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def has(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str) -> str:
        return self._values[key]

    def set(self, key: str, value: str) -> None:
        self._values[key] = value


@pytest.fixture
def store() -> DictStore:
    return DictStore(
        {
            "base": json.dumps({"min": 5, "soft_max": 10, "gap": 20}),
            "cal": json.dumps(
                {
                    "court_id": "cal",
                    "min": 295928,
                    "soft_max": 295928,
                    "gap": 100,
                }
            ),
            "ga2025": json.dumps(
                {"year": 2025, "min": 1, "soft_max": 4000, "gap": 0}
            ),
        }
    )


def test_dict_store_satisfies_protocol() -> None:
    assert isinstance(DictStore(), SpecKVStore)


def test_key_reference_resolves_to_base_class(store: DictStore) -> None:
    with spec_kv_store(store):
        r = PersistedSpeculativeRange.model_validate("[base]")
    assert type(r) is PersistedSpeculativeRange
    assert (r.min, r.soft_max, r.gap) == (5, 10, 20)
    assert list(r.seed_range()) == [5, 6, 7, 8, 9]


def test_key_reference_preserves_subclass_type(store: DictStore) -> None:
    """A CourtRange field fed ``[key]`` parses out to a CourtRange."""
    with spec_kv_store(store):
        r = CourtRange.model_validate("[cal]")
    assert type(r) is CourtRange
    assert r.court_id == "cal"
    assert r.search_key() == "cal"


def test_yearly_range_is_persisted_and_typed(store: DictStore) -> None:
    with spec_kv_store(store):
        r = YearlySpeculativeRange.model_validate("[ga2025]")
    assert type(r) is YearlySpeculativeRange
    assert r.year == 2025
    assert (r.min, r.soft_max) == (1, 4000)


def test_inheritance_chain() -> None:
    assert issubclass(PersistedSpeculativeRange, SpeculativeRange)
    assert issubclass(CourtRange, PersistedSpeculativeRange)
    assert issubclass(YearlySpeculativeRange, PersistedSpeculativeRange)


def test_full_object_bypasses_key_lookup(store: DictStore) -> None:
    """A normal mapping validates without touching the store."""
    with spec_kv_store(store):
        r = CourtRange.model_validate(
            {"court_id": "nv", "min": 1, "soft_max": 1}
        )
    assert r.court_id == "nv"
    assert r.min == 1


def test_key_reference_tolerates_whitespace(store: DictStore) -> None:
    with spec_kv_store(store):
        r = CourtRange.model_validate("  [cal]  ")
    assert r.court_id == "cal"


def test_store_flows_into_nested_field_validation(store: DictStore) -> None:
    """The store context var reaches a ``[key]`` nested inside another model."""

    class Params(BaseModel):
        docket: CourtRange

    with spec_kv_store(store):
        params = Params.model_validate({"docket": "[cal]"})
    assert type(params.docket) is CourtRange
    assert params.docket.court_id == "cal"


def test_missing_key_raises(store: DictStore) -> None:
    with spec_kv_store(store), pytest.raises(ValidationError):
        CourtRange.model_validate("[nope]")


def test_no_active_store_raises() -> None:
    assert SPEC_KV_STORE.get() is None
    with pytest.raises(ValidationError):
        CourtRange.model_validate("[cal]")


def test_stored_json_still_validated_against_class() -> None:
    """Stored JSON missing a required field fails the subclass validation."""
    bad = DictStore(
        {"x": json.dumps({"min": 1, "soft_max": 1})}
    )  # no court_id
    with spec_kv_store(bad), pytest.raises(ValidationError):
        CourtRange.model_validate("[x]")


def test_non_reference_string_falls_through(store: DictStore) -> None:
    """A plain (non-bracketed) string isn't a reference; normal validation rejects it."""
    with spec_kv_store(store), pytest.raises(ValidationError):
        CourtRange.model_validate("cal")


def test_spec_kv_store_restores_previous_value_on_exit(
    store: DictStore,
) -> None:
    assert SPEC_KV_STORE.get() is None
    with spec_kv_store(store):
        assert SPEC_KV_STORE.get() is store
    assert SPEC_KV_STORE.get() is None
