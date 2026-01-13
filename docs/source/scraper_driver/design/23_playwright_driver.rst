=============================
Step 23: PlaywrightDriver
=============================

The Problem
-----------

Some sites use sophisticated anti-bot protection to prevent scraping. Playwright allows us to
run a browser with a javascript engine and a closer approximation of what they are looking for.

The Solution
------------

**PlaywrightDriver** provides a real browser backend for the scraper-driver
architecture. It mirrors AsyncDriver but uses Playwright for HTTP execution,
enabling JavaScript rendering and browser-based interactions.

.. code-block:: python

    from juriscraper.scraper_driver.driver.playwright_driver import PlaywrightDriver

    async with PlaywrightDriver(scraper, on_data=callback, headless=True) as driver:
        await driver.run()

Scrapers remain **driver-agnostic** - the same scraper code works with SyncDriver,
AsyncDriver, or PlaywrightDriver.


Key Differences from AsyncDriver
--------------------------------

PlaywrightDriver inherits the same architecture as AsyncDriver but with these
browser-specific behaviors:

1. **Tab-Based Navigation**: Each ``NavigatingRequest`` opens in a new browser tab
2. **JavaScript Execution**: Pages are fully rendered before content is extracted
3. **POST via Form Injection**: POST navigations inject a form + click submit
4. **TransientException Scope**: Only raised on browser/page crashes, not JS errors
5. **Header Capture**: HTTP headers captured via ``page.on("response")``


Tab Management
--------------

PlaywrightDriver manages browser tabs with **reference counting** to prevent
memory leaks while allowing child pages to remain open:

TabState
^^^^^^^^

Each tab is tracked with a ``TabState`` dataclass:

.. code-block:: python

    @dataclass
    class TabState:
        page: Page                      # Playwright page object
        url: str                        # Current URL
        ref_count: int                  # Number of pending child requests
        response_headers: dict[str, str]  # Captured from last navigation
        response_status: int            # HTTP status code

Lifecycle
^^^^^^^^^

1. **Tab Creation**: New tab created for each ``NavigatingRequest``
2. **Parent Reference**: Parent tab's ``ref_count`` incremented
3. **Child Processing**: Generator yields processed, child requests enqueued
4. **Tab Release**: Tab closed, parent ``ref_count`` decremented
5. **Parent Cleanup**: Parent closed when ``ref_count`` reaches 0

Tab context is tracked via ``accumulated_data["_playwright_tab_key"]``.


POST Navigation
---------------

Browser navigation via POST cannot use ``page.goto()`` directly. Instead,
PlaywrightDriver **injects a form** into the current page and clicks submit:

.. code-block:: python

    # Form injection JavaScript
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = url;

    for (const [key, value] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = String(value);
        form.appendChild(input);
    }

    const submit = document.createElement('button');
    submit.type = 'submit';
    form.appendChild(submit);
    document.body.appendChild(form);

Then ``page.click("#submit")`` triggers the navigation. This ensures proper
browser history, cookie handling, and redirect following.


Request Processing
------------------

NavigatingRequest
^^^^^^^^^^^^^^^^^

Opens a new tab and navigates via ``page.goto()`` (GET) or form injection (POST):

.. code-block:: python

    async def _process_navigating_request(self, request: NavigatingRequest) -> None:
        page, tab_key = await self._create_tab(request, parent_key)

        if request.request.method == HttpMethod.POST:
            final_url, headers, status = await self._post_and_capture(page, url, data)
        else:
            final_url, headers, status = await self._navigate_and_capture(page, url)

        content = await page.content()  # Get rendered HTML
        response = Response(...)

        gen = continuation(response)
        await self._process_generator(gen, response, request, tab_key)

NonNavigatingRequest
^^^^^^^^^^^^^^^^^^^^

Uses Playwright's request context API for raw HTTP (no page navigation):

.. code-block:: python

    async def _process_non_navigating_request(self, request: NonNavigatingRequest) -> None:
        api_response = await self._context.request.fetch(
            url, method=method, headers=headers, data=data
        )
        body = await api_response.body()
        response = Response(...)

This is useful for JSON APIs called from within a page context.

ArchiveRequest
^^^^^^^^^^^^^^

Downloads files via the request context API and passes to the archive callback.


Error Handling
--------------

TransientException
^^^^^^^^^^^^^^^^^^

Only raised for **browser or page crashes** - situations where the entire browser
process or tab has become unresponsive:

.. code-block:: python

    def _is_crash_error(self, error: PlaywrightError) -> bool:
        crash_indicators = [
            "Target closed",
            "crashed",
            "Browser closed",
            "Context closed",
            "Page closed",
            "Connection closed",
        ]
        return any(indicator in str(error) for indicator in crash_indicators)

JavaScript errors, timeouts, and network errors are **not** considered transient
since the browser can continue operating.


Header and Cookie Capture
-------------------------

HTTP headers are captured via Playwright's response event:

.. code-block:: python

    async def _navigate_and_capture(self, page: Page, url: str) -> tuple:
        captured_headers: dict[str, str] = {}
        captured_status: int = 200

        async def capture_response(response: PlaywrightResponse) -> None:
            if response.request.is_navigation_request():
                captured_headers = dict(response.headers)
                captured_status = response.status

        page.on("response", capture_response)
        await page.goto(url, wait_until="load")
        page.remove_listener("response", capture_response)

        return page.url, captured_headers, captured_status

Configuration Options
---------------------

Browser Selection
^^^^^^^^^^^^^^^^^

.. code-block:: python

    PlaywrightDriver(
        scraper,
        browser_type="chromium",  # or "firefox", "webkit"
        channel="chrome",          # Use native Chrome instead of Chromium
        headless=True,
    )

Viewport and User Agent
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    PlaywrightDriver(
        scraper,
        user_agent="CustomBot/1.0",
        viewport={"width": 1920, "height": 1080},
    )

Design Decisions
----------------

**Single worker model**: While AsyncDriver supports ``num_workers``, PlaywrightDriver
uses a single queue processor. This is subject to update later.

**Driver owns browser lifecycle**: The browser is created in ``start()``/``__aenter__``
and destroyed in ``stop()``/``__aexit__``. This ensures clean resource management.

**Scrapers remain driver-agnostic**: No browser-specific APIs are exposed to scrapers.
The same scraper code works with any driver implementation.

**Interceptors are buyer-beware**: Interceptors designed for httpx may not work
correctly with Playwright.
