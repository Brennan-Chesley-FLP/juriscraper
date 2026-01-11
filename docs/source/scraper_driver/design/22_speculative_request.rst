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

    @step
    def parse_list(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
        page = 1
        while True:
            should_continue = yield SpeculativeRequest(
                request=HTTPRequestParams(url=f"/cases?page={page}"),
                continuation="parse_page",
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
        speculation_context: SpeculationContext | None = None

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
        @step
        def parse_list(self, lxml_tree) -> Generator[ScraperYield, bool | None, None]:
            page = 1
            while True:
                should_continue = yield SpeculativeRequest(
                    request=HTTPRequestParams(url=f"/cases?page={page}"),
                    continuation="parse_page",
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

    @step
    def parse_sections(self, response) -> Generator[ScraperYield, bool | None, None]:
        for section_id in range(1, 100):
            has_section = yield SpeculativeRequest(
                request=HTTPRequestParams(url=f"/doc/{doc_id}/section/{section_id}"),
                continuation="parse_section",
            )
            if not has_section:
                break  # No more sections


Design Decisions
----------------

**Queue-based resumption**: Using ``ResumeStep`` ensures generators resume in
proper priority order, maintaining A*/depth-first traversal semantics.

**Limited serializability**: We aren't pickling the generator state, so we've effectively
chosen to pin the generator to a thread here. If we decide on more complex deployment procedures that involve
shipping the queue around, we'll need to rethink this. If we make a multithreaded driver (not just async) we'll
have to take special care. Both of these options seem unlikely at this time.
