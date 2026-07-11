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

# Browser-shaped header sets for sites whose WAF blocks the honest
# ``Juriscraper`` User-Agent. Use these on plain-HTTP (non-browser) scrapers
# to present a full desktop-browser fingerprint — matched User-Agent, Accept,
# Accept-Language, Accept-Encoding, and Sec-Fetch/Client-Hint headers a real
# navigation sends.
#
# NOTE: ``Accept-Encoding`` advertises ``br``. httpx can only decode Brotli when
# the ``brotli`` (or ``brotlicffi``) package is installed; without it, any
# response the server returns with ``Content-Encoding: br`` raises
# ``httpx.DecodingError``. Safe only where the server doesn't honor ``br``.
FF_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
        "Gecko/20100101 Firefox/140.0"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

CHROME_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="138", "Chromium";v="138"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
