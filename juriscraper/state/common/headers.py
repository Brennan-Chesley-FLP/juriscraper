"""Shared default HTTP headers for ``juriscraper`` state scrapers.

Baseline header sets to assign to a scraper's ``default_headers`` ClassVar
so the httpx transport sends them with every request.
"""

from __future__ import annotations

# The headers legacy ``AbstractSite``-based scrapers sent by default. Notably
# the ``User-Agent`` avoids the httpx default (``python-httpx/<ver>``), which
# some court WAFs silently drop the connection on (surfacing as a
# ``ReadError`` rather than an HTTP status).
JURISCRAPER: dict[str, str] = {
    "User-Agent": "Juriscraper",
    # Disable CDN caching on sites like SCOTUS (ahem).
    "Cache-Control": "no-cache, max-age=0, must-revalidate",
    # Backwards compatibility with HTTP/1.0 caches.
    "Pragma": "no-cache",
}
