"""Shared entry-parameter models for ``juriscraper/sd/state`` scrapers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from typing import Any, Protocol, runtime_checkable

from dateutil.relativedelta import relativedelta
from jkent.common.param_models import DateRange, SpeculativeRange
from pydantic import model_validator

#: One offset (``[+-]<n><unit>``), optionally followed by a second,
#: comma-separated one. Surrounding and inter-token whitespace is tolerated.
_SHORTHAND_RE = re.compile(r"\s*[+-]\d+[dwmy]\s*(?:,\s*[+-]\d+[dwmy]\s*)?")
_OFFSET_RE = re.compile(r"([+-])(\d+)([dwmy])")

#: Anchor the relative offsets of an :class:`InferrableDateRange` shorthand
#: resolve against. When unset (the default), shorthands resolve against
#: :meth:`datetime.date.today`. Set it — usually via the :func:`anchor_date`
#: context manager — to pin resolution to a fixed date (e.g. a run's logical
#: "as of" date, or a frozen clock in tests).
ANCHOR_DATE: ContextVar[date | None] = ContextVar("anchor_date", default=None)


@contextmanager
def anchor_date(value: date) -> Iterator[None]:
    """Resolve :class:`InferrableDateRange` shorthands against ``value``.

    Sets :data:`ANCHOR_DATE` for the duration of the ``with`` block and
    restores the previous value on exit::

        with anchor_date(date(2026, 7, 1)):
            dr = InferrableDateRange.model_validate("-4d")
            # dr == DateRange(start=date(2026, 6, 27), end=date(2026, 7, 1))
    """
    token = ANCHOR_DATE.set(value)
    try:
        yield
    finally:
        ANCHOR_DATE.reset(token)


def _resolve_anchor() -> date:
    """Return the current anchor date, defaulting to today."""
    anchor = ANCHOR_DATE.get()
    return anchor if anchor is not None else date.today()


def _apply_offset(token: str, anchor: date) -> date:
    """Apply a single ``[+-]<n><unit>`` offset to ``anchor``.

    ``token`` is assumed to already match :data:`_OFFSET_RE` (the whole
    shorthand having been checked against :data:`_SHORTHAND_RE`). Days and
    weeks use exact arithmetic; months and years use calendar-aware
    :class:`dateutil.relativedelta`.
    """
    match = _OFFSET_RE.fullmatch(token.strip())
    assert match is not None  # guaranteed by the _SHORTHAND_RE check
    sign, magnitude, unit = match.groups()
    amount = int(magnitude) * (-1 if sign == "-" else 1)
    if unit == "d":
        return anchor + timedelta(days=amount)
    if unit == "w":
        return anchor + timedelta(weeks=amount)
    if unit == "m":
        return anchor + relativedelta(months=amount)
    return anchor + relativedelta(years=amount)


class InferrableDateRange(DateRange):
    """A :class:`~jkent.common.param_models.DateRange` that also accepts a
    relative-offset shorthand string.

    A full ``{"start": ..., "end": ...}`` object validates exactly like the
    parent ``DateRange``. Additionally, a **string** of the form::

        [+-]<n><unit>[,[+-]<n><unit>]

    where ``<unit>`` is one of ``d`` (days), ``w`` (weeks), ``m`` (months) or
    ``y`` (years), is expanded relative to an *anchor date* into a concrete
    ``{start, end}`` pair. The anchor is taken from the :data:`ANCHOR_DATE`
    context var (see :func:`anchor_date`) and defaults to today.

    One offset or two may be given. A single offset pairs with the anchor
    itself (i.e. an implicit ``+0d``). The two resulting dates are ordered so
    :attr:`start` is always the earlier one, regardless of the order written.

    With an anchor of ``2026-07-01``::

        "-4d"      -> start=2026-06-27, end=2026-07-01
        "-3d,+1d"  -> start=2026-06-28, end=2026-07-02
        "-1d,-4d"  -> start=2026-06-27, end=2026-06-30

    Months and years use calendar arithmetic (:class:`dateutil.relativedelta`),
    so ``-1m`` from ``2026-03-31`` is ``2026-02-28``.
    """

    @model_validator(mode="before")
    @classmethod
    def _expand_shorthand(cls, data: Any) -> Any:
        """Expand a shorthand string into a ``{start, end}`` mapping.

        Non-string input (a mapping, an existing model) is passed through
        untouched for normal ``DateRange`` field validation.
        """
        if not isinstance(data, str):
            return data
        if _SHORTHAND_RE.fullmatch(data) is None:
            raise ValueError(
                f"invalid date-range shorthand {data!r}; expected one or two "
                "comma-separated offsets like '-4d' or '-3d,+1d' "
                "(units: d, w, m, y)"
            )
        anchor = _resolve_anchor()
        tokens = data.split(",")
        if len(tokens) == 1:
            tokens.append("+0d")
        start, end = sorted(_apply_offset(t, anchor) for t in tokens)
        return {"start": start, "end": end}


@runtime_checkable
class SpecKVStore(Protocol):
    """A key/value store that persists speculative-range state across runs.

    Values are opaque JSON **strings**: :meth:`get` returns the JSON text a
    :class:`PersistedSpeculativeRange` shorthand parses, and :meth:`set` stores
    it (typically ``range.model_dump_json()``). Any object implementing these
    three methods satisfies the protocol — no explicit subclassing needed.
    """

    def has(self, key: str) -> bool:
        """Return whether a value is stored under ``key``."""
        ...

    def get(self, key: str) -> str:
        """Return the JSON string stored under ``key``.

        Only called after :meth:`has` returns True for the same key.
        """
        ...

    def set(self, key: str, value: str) -> None:
        """Store the JSON string ``value`` under ``key``."""
        ...


#: The store that :class:`PersistedSpeculativeRange` ``[key]`` shorthands
#: resolve against. Unset by default; populate it — usually via the
#: :func:`spec_kv_store` context manager — before validating seed params that
#: reference persisted state.
SPEC_KV_STORE: ContextVar[SpecKVStore | None] = ContextVar(
    "spec_kv_store", default=None
)


@contextmanager
def spec_kv_store(store: SpecKVStore) -> Iterator[None]:
    """Make ``store`` the active :data:`SPEC_KV_STORE` for the block.

    Sets the context var for the duration of the ``with`` block and restores
    the previous value on exit::

        with spec_kv_store(my_store):
            r = CourtRange.model_validate("[cal-docket-cursor]")
    """
    token = SPEC_KV_STORE.set(store)
    try:
        yield
    finally:
        SPEC_KV_STORE.reset(token)


#: A ``[key]`` reference: a single key wrapped in square brackets. Surrounding
#: whitespace is tolerated; the key itself may not contain brackets.
_KEY_REF_RE = re.compile(r"\[([^\[\]]+)\]")


class PersistedSpeculativeRange(SpeculativeRange):
    """A :class:`~jkent.common.param_models.SpeculativeRange` whose seed value
    can be loaded from a :class:`SpecKVStore`.

    A full ``{"min": ..., ...}`` object (or any other input) validates exactly
    like the parent ``SpeculativeRange``. Additionally, a **string** of the
    form ``[key]`` is resolved at validation time: the key is looked up in the
    active :data:`SPEC_KV_STORE` (see :func:`spec_kv_store`), and the stored
    JSON string is parsed and validated as this class.

    Because resolution happens in a ``mode="before"`` validator that returns a
    plain mapping, subclasses parse out to *their own* type — e.g. a
    :class:`CourtRange` field fed ``"[k]"`` yields a ``CourtRange`` (provided
    the stored JSON carries ``court_id``).

    The lookup raises if no store is active or the key is absent — a ``[key]``
    reference is only a pointer, with no inline seed to fall back to, so the
    store must be populated before validation.
    """

    @model_validator(mode="before")
    @classmethod
    def _resolve_persisted(cls, data: Any) -> Any:
        """Resolve a ``[key]`` reference against the active store.

        Non-string input, and strings that aren't a ``[key]`` reference, are
        passed through untouched for normal ``SpeculativeRange`` validation.
        """
        if not isinstance(data, str):
            return data
        match = _KEY_REF_RE.fullmatch(data.strip())
        if match is None:
            return data
        key = match.group(1)
        store = SPEC_KV_STORE.get()
        if store is None:
            raise ValueError(
                f"cannot resolve persisted range {data!r}: no SpecKVStore is "
                "active (enter a spec_kv_store(...) block first)"
            )
        if not store.has(key):
            raise ValueError(
                f"cannot resolve persisted range {data!r}: the active "
                f"SpecKVStore has no value for key {key!r}"
            )
        return json.loads(store.get(key))


class CourtRange(PersistedSpeculativeRange):
    """A ``SpeculativeRange`` tagged with the CourtListener court id it probes.

    The driver dispatches a speculative entry with **only** its speculative
    param — it calls ``entry(<speculative_param>=range)`` and binds no other
    arguments — so a scraper that speculates across several courts can't take
    ``court_ids`` as a separate argument. The target court rides here instead:
    seed one ``CourtRange`` per court. The driver's ``from_int`` advancement
    preserves ``court_id`` (and any subclass fields) because it copies via
    ``model_copy``.

    Sites whose search key *is* the CourtListener id use ``CourtRange``
    directly and read :attr:`court_id`. Sites that address courts by a
    site-specific key (a letter prefix, a numeric id, …) subclass and override
    :meth:`search_key` to translate, typically via a ``court_id``-keyed dict.

    See ``california/appellatecases_courtinfo_ca_gov`` (``CaCourtRange``) for a
    prefix-translating subclass, and ``SCRAPER_STANDARDS.md`` §4
    ("Multi-court speculative entries").
    """

    court_id: str
    """CourtListener court id this range probes (e.g. ``"cal"``)."""

    def search_key(self) -> str:
        """Return the site's search key for this court.

        Base implementation returns the court id unchanged; override to
        translate a CourtListener id into the value the site searches by.
        """
        return self.court_id


class YearlySpeculativeRange(PersistedSpeculativeRange):
    """Persisted counterpart of :class:`jkent.common.param_models.YearlySpeculativeRange`.

    Identical in shape to jkent's ``YearlySpeculativeRange`` — a
    ``SpeculativeRange`` with an added ``year`` field for scrapers that
    partition IDs by year (e.g. docket numbers of the form ``2025-00123``) —
    but subclasses :class:`PersistedSpeculativeRange`, so it also accepts a
    ``[key]`` store reference. ``seed_range``/``from_int``/``max_gap`` are
    inherited unchanged; ``from_int`` copies via ``model_copy``, so ``year`` is
    carried through advancement.

    This shadows the jkent class by name; scrapers currently importing
    ``YearlySpeculativeRange`` from jkent will be migrated to this one.
    """

    year: int
    """The calendar year for this partition."""
