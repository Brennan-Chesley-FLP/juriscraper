"""Shared entry-parameter models for ``juriscraper/sd/state`` scrapers."""

from __future__ import annotations

from jkent.common.param_models import SpeculativeRange


class CourtRange(SpeculativeRange):
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
