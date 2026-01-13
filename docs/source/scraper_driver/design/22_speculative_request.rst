===================================
Step 22: Speculative Request
===================================

The Problem
-----------

Some scrapers take advantage of expected sequential ids to gather data.
Generally, we don't know if an id exists before we request the page for it, so we need a way of potentially handling
an unbounded number of potential pages, and deciding when to stop checking ids.


The Solution
------------

**SpeculativeRequest** enables scrapers to yield requests that may or may not exist,
with the driver determining whether to continue based on the responses for missed requests:

.. code-block:: python

    @step(speculative=True)
    def parse_list(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
        page = 1
        while True:
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(url=f"/cases?page={page}"),
                continuation="parse_page",
                speculative_id=page,  # Track progress for resumption
            )

            if not should_continue:
                break  # Driver said stop (e.g., 404 received)

            page += 1

The scraper yields a ``SpeculativeRequest``, then receives ``True`` or ``False``
back indicating whether to continue.


How It Works
------------

The flow is:

1. Scraper yields ``SpeculativeRequest`` with URL and continuation name
2. Driver **parks the generator** (stores its state) and enqueues the request
3. Request flows through normal pipeline (queue, interceptors, deduplication)
4. Driver fetches the URL and checks the response status:

   - **2xx response**: Returns ``True`` to generator, calls continuation with response
   - **Non-2xx response**: Calls ``on_speculation_response`` callback (if provided)

     - Callback returns ``True``: Returns ``True`` to generator, but skips continuation
     - Callback returns ``False``: Returns ``False`` to generator, skips continuation
     - No callback configured: Returns ``False`` to generator, skips continuation

5. Generator resumes and receives the boolean result


Key Types
---------

SpeculativeRequest
^^^^^^^^^^^^^^^^^^

A request that returns ``True/False`` to the yielding generator:

.. code-block:: python

    @dataclass(frozen=True)
    class SpeculativeRequest(NonNavigatingRequest):
        """Request that returns True/False to the yielding generator."""
        speculative_id: int = 1  # Track which ID is being fetched
        speculation_context: SpeculationContext | None = None

The ``speculative_id`` field tracks which sequential ID is being fetched. Consumers
can configure the starting ID for each speculative step via params (see below).

SpeculationContext
^^^^^^^^^^^^^^^^^^

Mutable container holding the parked generator state:

.. code-block:: python

    @dataclass
    class SpeculationContext:
        parked_generator: Generator[ScraperYield, bool | None, None]
        parent_request: BaseRequest
        original_response: Response
        originating_continuation: str

ResumeStep
^^^^^^^^^^

A queue item that resumes a parked generator. This ensures proper priority ordering
for requests in the queue and we don't blow up memory:

.. code-block:: python

    @dataclass(frozen=True)
    class ResumeStep(BaseRequest):
        """Queued item to resume a parked generator."""
        speculation_context: SpeculationContext | None = None
        predicate_result: bool = True


Driver Integration
------------------

Callback Configuration
^^^^^^^^^^^^^^^^^^^^^^

The driver accepts an optional callback to decide continuation for non-2xx responses:

.. code-block:: python

    def track_consecutive_404s(response: Response, continuation_name: str) -> bool:
        """Stop after 3 consecutive 404s."""
        if response.status_code == 404:
            consecutive_404s += 1
            return consecutive_404s < 3
        consecutive_404s = 0
        return True

    driver = SyncDriver(
        scraper,
        on_speculation_response=track_consecutive_404s,
    )

For async drivers, the callback can be async:

.. code-block:: python

    async def async_callback(response: Response, continuation_name: str) -> bool:
        await log_response(response)
        return response.status_code < 500

    driver = AsyncDriver(
        scraper,
        on_speculation_response=async_callback,
    )

This way, the driver can easily decide how much speculation it wants to do.
Our callback might cap speculation at 3 failures, or it might cap it at 1 more than the largest gap it's seen,
or any other criteria we'd like.

Bidirectional Generators
------------------------

This feature changes the generator signature from unidirectional to bidirectional:

.. code-block:: python

    # Before: Generator[YieldType, None, None]
    # After:  Generator[YieldType, bool | None, None]
    #                              ^^^^^^^^^^^^
    #                              Send type (what driver sends back)

The ``@step`` decorator handles this transparently - values sent to the wrapper
generator are passed through to the underlying scraper generator.


Implementation Details
----------------------

Queue-Based Resumption
^^^^^^^^^^^^^^^^^^^^^^

When a generator yields ``SpeculativeRequest``:

1. Driver creates ``SpeculationContext`` with the generator reference
2. Attaches context to request via ``with_context()``
3. Enqueues request normally

When the request is processed:

1. Driver executes HTTP, determines success
2. Creates ``ResumeStep`` with the result
3. Enqueues ``ResumeStep`` (inherits priority from parent request)
4. If success, processes continuation inline

When ``ResumeStep`` is popped:

1. Driver retrieves parked generator from context
2. Calls ``generator.send(predicate_result)``
3. Continues processing any further yields

Deduplication Handling
^^^^^^^^^^^^^^^^^^^^^^

When a ``SpeculativeRequest`` is deduplicated (URL already seen):

- Driver still creates a ``ResumeStep`` with ``predicate_result=False``
- Generator resumes and receives ``False``
- This prevents infinite loops on duplicate URLs


Usage Examples
--------------

Infinite Pagination
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    class InfinitePaginationScraper(BaseScraper[CaseData]):
        @step(speculative=True)
        def parse_list(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
            page = 1
            while True:
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(url=f"/cases?page={page}"),
                    continuation="parse_page",
                    speculative_id=page,
                )

                if not should_continue:
                    break

                page += 1

        @step
        def parse_page(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
            for case in lxml_tree.checked_xpath("//div[@class='case']", "cases"):
                yield ParsedData(data={"title": case.text_content()})

Sequential Speculative Requests
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple speculative requests work naturally - each parks the generator,
resolves, resumes, then continues to the next:

.. code-block:: python

    @step(speculative=True)
    def parse_sections(self, response) -> Generator[ScraperYield, bool | None, None]:
        for section_id in range(1, 100):
            has_section = yield SpeculativeRequest(
                request=HTTPRequestParams(url=f"/doc/{doc_id}/section/{section_id}"),
                continuation="parse_section",
                speculative_id=section_id,
            )
            if not has_section:
                break  # No more sections

Tracking Speculative IDs with accumulated_data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For resumable scraping, pass the last successfully processed ID through
``accumulated_data``. This allows consumers to resume from where they left off:

.. code-block:: python

    from typing import Annotated
    from juriscraper.scraper_driver.common.searchable import SpeculativeID

    class CaseData(ScrapedData):
        """Case data with speculative ID for resumable scraping."""
        case_id: Annotated[str, SpeculativeID()]
        case_name: str

    class ResumableScraper(BaseScraper[CaseData]):
        @step
        def parse_list(
            self, lxml_tree, accumulated_data: dict
        ) -> Generator[ScraperYield, bool | None, None]:
            # Get starting ID from params (if resuming)
            start_id = accumulated_data.get("speculative_id", {}).get(
                "CaseData", {}
            ).get("case_id", 0)

            current_id = start_id + 1
            while True:
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(url=f"/cases/{current_id}"),
                    continuation="parse_case",
                    # Pass the current ID so parse_case can track progress
                    accumulated_data={
                        "speculative_id": {
                            "CaseData": {"case_id": current_id}
                        }
                    },
                )

                if not should_continue:
                    break

                current_id += 1

        @step
        def parse_case(
            self, lxml_tree, accumulated_data: dict
        ) -> Generator[ScraperYield, bool | None, None]:
            current_id = accumulated_data["speculative_id"]["CaseData"]["case_id"]
            case_name = lxml_tree.checked_xpath("//h1/text()", "case name")[0]

            yield ParsedData(
                data=CaseData(case_id=str(current_id), case_name=case_name)
            )

**Consuming with params:**

.. code-block:: python

    # Resume from a specific ID
    params = ResumableScraper.params()
    params.CaseData.case_id.gt = "12345"  # Start after ID 12345

    # Or fetch a specific ID
    params.CaseData.case_id.eq = "12346"  # Only fetch this ID

The ``SpeculativeID`` marker (see :doc:`20_search_and_standardization`) provides
``.gt`` for greater-than filtering and ``.eq`` for exact match, enabling
consumers to resume scraping from a known checkpoint.


Configuring Starting IDs via Params
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Steps marked with ``@step(speculative=True)`` can have their starting ID
configured by consumers via params. This enables resumable scraping:

.. code-block:: python

    class CaseIDScraper(BaseScraper[CaseData]):
        @step(speculative=True)
        def parse_cases(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
            # Get starting ID from params (defaults to 1)
            params = self.params()
            start_id = params.speculative.parse_cases

            case_id = start_id
            while True:
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(url=f"/cases/{case_id}"),
                    continuation="parse_case",
                    speculative_id=case_id,
                )

                if not should_continue:
                    break

                case_id += 1

**Consumer configuration:**

.. code-block:: python

    # Resume from a specific ID
    params = CaseIDScraper.params()
    params.speculative.parse_cases = 12345  # Start from ID 12345

    # Multiple speculative steps can be configured independently
    params.speculative.parse_cases = 100
    params.speculative.parse_details = 50

Tracking Speculative IDs with accumulated_data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For more complex scenarios, pass the current ID through ``accumulated_data``.
This allows child steps to access the current speculative ID:

.. code-block:: python

    from typing import Annotated
    from juriscraper.scraper_driver.common.searchable import SpeculativeID

    class CaseData(ScrapedData):
        """Case data with speculative ID for resumable scraping."""
        case_id: Annotated[str, SpeculativeID()]
        case_name: str

    class ResumableScraper(BaseScraper[CaseData]):
        @step(speculative=True)
        def parse_list(
            self, lxml_tree, accumulated_data: dict
        ) -> Generator[ScraperYield, bool | None, None]:
            # Get starting ID from params
            params = self.params()
            current_id = params.speculative.parse_list

            while True:
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(url=f"/cases/{current_id}"),
                    continuation="parse_case",
                    speculative_id=current_id,
                    # Pass the current ID so parse_case can track progress
                    accumulated_data={
                        "speculative_id": {
                            "CaseData": {"case_id": current_id}
                        }
                    },
                )

                if not should_continue:
                    break

                current_id += 1

        @step
        def parse_case(
            self, lxml_tree, accumulated_data: dict
        ) -> Generator[ScraperYield, bool | None, None]:
            current_id = accumulated_data["speculative_id"]["CaseData"]["case_id"]
            case_name = lxml_tree.checked_xpath("//h1/text()", "case name")[0]

            yield ParsedData(
                data=CaseData(case_id=str(current_id), case_name=case_name)
            )

**Consuming with field params:**

.. code-block:: python

    # Configure starting ID via speculative step
    params = ResumableScraper.params()
    params.speculative.parse_list = 12345  # Start from ID 12345

    # Or filter results by ID using SpeculativeID marker
    params.CaseData.case_id.gt = "12345"  # Only return cases after ID 12345
    params.CaseData.case_id.eq = "12346"  # Only return this specific case

The ``SpeculativeID`` marker (see :doc:`20_search_and_standardization`) provides
``.gt`` for greater-than filtering and ``.eq`` for exact match on result data,
while ``params.speculative`` controls where scraping starts.


Design Decisions
----------------

**Queue-based resumption**: Using ``ResumeStep`` ensures generators resume in
proper priority order, maintaining A*/depth-first traversal semantics.

**Limited serializability**: We aren't pickling the generator state, so we've effectively
chosen to pin the generator to a thread here. If we decide on more complex deployment procedures that involve
shipping the queue around, we'll need to rethink this. If we make a multithreaded driver (not just async) we'll
have to take special care. Both of these options seem unlikely at this time.


Next Steps
----------

In :doc:`23_playwright_driver`, we introduce a browser-based driver that uses
Playwright for HTTP execution. This enables JavaScript rendering, session
management, and handling of sites that require a real browser environment.
