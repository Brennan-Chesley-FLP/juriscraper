Step 20: Search and Standardization
====================================

The Problem
-----------

As scrapers grow in number and complexity, several challenges emerge:

1. **Discoverability** - How do users find scrapers for specific courts?
2. **Consistency** - How do we ensure all scrapers follow the same patterns?
3. **Documentation** - How do we auto-generate accurate documentation?
4. **Filtering** - How can users specify which data they want from a scraper?

In Step 20, we introduce **standardized metadata** on scrapers and a
**params interface** for configuring scraper filters.


Overview
--------

This step introduces:

1. **BaseScraper ClassVars** - Standardized metadata fields for autodoc
2. **ConsumerModel hierarchy** - Common base classes for return types
3. **Searchable field annotations** - Declarative filter specifications
4. **params() interface** - Attribute-style filter configuration
5. **Registry builder** - Auto-generates documentation from metadata


BaseScraper Metadata
--------------------

Every scraper should define these class variables for documentation:

.. code-block:: python

    from datetime import date
    from typing import ClassVar

    from juriscraper.scraper_driver.data_types import BaseScraper, ScraperStatus


    class MyScraper(BaseScraper[MyDataModel]):
        """Scraper for Example Court dockets."""

        # === REQUIRED METADATA ===

        # Court IDs from courts-db that this scraper covers
        court_ids: ClassVar[set[str]] = {"examplect", "examplectapp"}

        # Primary URL for the court system
        court_url: ClassVar[str] = "https://courts.example.gov/"

        # Data types produced (opinions, dockets, oral_arguments, etc.)
        data_types: ClassVar[set[str]] = {"dockets"}

        # Scraper lifecycle status
        status: ClassVar[ScraperStatus] = ScraperStatus.ACTIVE

        # === RECOMMENDED METADATA ===

        # Version tracking (date-based recommended)
        version: ClassVar[str] = "2025-01-03"
        last_verified: ClassVar[str] = "2025-01-03"

        # Earliest available records
        oldest_record: ClassVar[date] = date(1990, 1, 1)

        # === OPTIONAL METADATA ===

        # Authentication requirements
        requires_auth: ClassVar[bool] = False

        # Rate limiting (milliseconds between requests)
        msec_per_request_rate_limit: ClassVar[int] = 500

**Metadata Purpose:**

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Purpose
   * - ``court_ids``
     - Links to courts-db; enables coverage reports and filtering
   * - ``court_url``
     - Displayed in docs; used for manual verification
   * - ``data_types``
     - Coverage calculations; documentation categorization
   * - ``status``
     - Filter retired scrapers from production
   * - ``version``
     - Track scraper changes; cache invalidation
   * - ``oldest_record``
     - Set user expectations for data availability
   * - ``msec_per_request_rate_limit``
     - Rate limiter configuration


ConsumerModel Hierarchy
-----------------------

All scraper return types should inherit from ``ConsumerModel`` or its
specialized subclasses. This provides:

1. **Consistent field names** across scrapers
2. **Automatic documentation** of available fields
3. **Type safety** for downstream consumers

**Base Classes:**

.. code-block:: python

    from juriscraper.scraper_driver.common.models.base import (
        ConsumerModel,  # Abstract base for all data
        Docket,         # Case/docket metadata
        DocketEntry,    # Individual filings within a docket
        Opinion,        # Judicial opinions
        OpinionCluster, # Groups of related opinions
        Audio,          # Oral argument recordings
    )

**Creating Specialized Models:**

.. code-block:: python

    from pydantic import Field
    from juriscraper.scraper_driver.common.models.base import Docket, DocketEntry


    class BugCourtDocket(Docket):
        """Bug Court-specific docket model."""

        # Inherit base fields: docket_number, case_name, date_filed, etc.

        # Add Bug Court-specific field
        buzz_level: str = Field(default="")


    class BugCourtDocketEntry(DocketEntry):
        """Bug Court-specific docket entry model."""

        # Inherit base fields: date_filed, description, etc.

        # Add Bug Court-specific fields
        document_type: str = Field(default="")
        entry_category: str = Field(default="")
        internal_url: str = Field(min_length=1)

**Union Return Types:**

Scrapers can return multiple model types using Union:

.. code-block:: python

    class Site(BaseScraper[BugCourtDocket | BugCourtDocketEntry]):
        """Returns both dockets and docket entries."""
        ...


Searchable Field Annotations
----------------------------

Fields that can be filtered should be annotated with searchable markers.
This enables:

1. **Self-documenting APIs** - Field capabilities are declared in code
2. **Automatic param building** - The params() method knows what's filterable
3. **Documentation generation** - Searchability appears in auto-generated docs

**Three Filter Types:**

.. code-block:: python

    from datetime import date
    from typing import Annotated

    from pydantic import Field

    from juriscraper.scraper_driver.common.models.base import Docket
    from juriscraper.scraper_driver.common.searchable import (
        DateRange,    # gte/lte date bounds
        SetFilter,    # Set of allowed values
        UniqueMatch,  # Exact single value match
    )


    class BugDocket(Docket):
        """Docket with searchable fields."""

        # Date range filtering: filter by >= and/or <= dates
        date_filed: Annotated[date | None, DateRange()] = Field(default=None)

        # Set filtering: filter by a set of allowed values
        court_id: Annotated[str | None, SetFilter()] = Field(default=None)
        case_type: Annotated[str | None, SetFilter()] = Field(default=None)

        # Unique match: filter by exact value
        docket_number: Annotated[str | None, UniqueMatch()] = Field(default=None)

**Filter Behavior:**

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Marker
     - Filter Attributes
     - Use Case
   * - ``DateRange``
     - ``.gte``, ``.lte``
     - Date range queries
   * - ``SetFilter``
     - ``.values`` (set)
     - Multiple allowed values
   * - ``UniqueMatch``
     - ``.value`` (single)
     - Exact ID/number lookup


The params() Interface
----------------------

The ``BaseScraper.params()`` class method builds a filter configuration
object from the scraper's return type annotations:

**Basic Usage:**

.. code-block:: python

    from datetime import date

    # Build params from scraper's type annotations
    params = MyScraper.params()

    # Set date range filter
    params.CaseDocket.date_filed.gte = date(2024, 1, 1)
    params.CaseDocket.date_filed.lte = date(2024, 12, 31)

    # Set filter: only civil and criminal cases
    params.CaseDocket.case_type.values = {"civil", "criminal"}

    # Unique match: find specific docket
    params.CaseDocket.docket_number.value = "2024-001"

    # Disable a data type entirely
    params.CaseDocket = None

**Passing to Scraper:**

.. code-block:: python

    class MyScraper(BaseScraper[CaseDocket]):
        def get_entry_request(self, params: ScraperParams) -> BaseRequest:
            # Access filter values
            model = params.CaseDocket

            # Check if filters are set
            if model.date_filed.is_set():
                start = model.date_filed.gte
                end = model.date_filed.lte

            if model.case_type.is_set():
                allowed_types = model.case_type.values

            # Build request with filters applied
            return NavigatingRequest(
                url=self._build_search_url(start, end, allowed_types),
                continuation=self.parse_results,
            )

**Introspection:**

.. code-block:: python

    params = MyScraper.params()

    # Get all models
    for name, proxy in params.get_models().items():
        print(f"Model: {name}")

        # Get searchable fields
        for field_name, field_proxy in proxy.get_searchable_fields().items():
            print(f"  {field_name}: {type(field_proxy.marker).__name__}")

    # Get only enabled models
    enabled = params.get_enabled_models()

    # Get only active filters
    active = params.CaseDocket.get_active_filters()


Documentation Generation
------------------------

The registry builder script (``scripts/build_court_registry.py``) extracts
metadata from all scrapers and generates:

1. **court_registry.toml** - Machine-readable registry
2. **Sphinx documentation** - Auto-generated court coverage pages

**Running the Builder:**

.. code-block:: bash

    uv run python -m scripts.build_court_registry

**Generated Registry Fields:**

.. code-block:: toml

    [scrapers.Site]
    scraper_id = "Site"
    court_ids = ["bugct", "bugctapp"]
    court_url = "https://courts.bugcivil.gov/"
    data_types = ["dockets"]

    # Return type information
    return_type = "BugCourtDocket | BugCourtDocketEntry"
    parent_model = "Docket, DocketEntry"
    model_hierarchy = ["BugCourtDocket", "Docket", "ConsumerModel"]

    # Lifecycle metadata
    status = "active"
    version = "2025-01-03"
    oldest_record = "1900-01-01"
    requires_auth = false
    msec_per_request = 500

    # Searchable fields
    [scrapers.Site.searchability.BugCourtDocket]
    DateRange = ["date_filed"]
    SetFilter = ["court_id"]
    UniqueMatch = ["docket_number"]

**Sphinx Extension:**

The ``court_coverage`` Sphinx extension reads the registry and generates:

- Per-jurisdiction coverage pages
- Per-scraper documentation with metadata
- Coverage statistics and charts


Best Practices
--------------

**Metadata:**

1. Always set ``court_ids`` - Links your scraper to courts-db
2. Use accurate ``status`` - Don't leave scrapers as IN_DEVELOPMENT
3. Update ``version`` and ``last_verified`` regularly
4. Set ``oldest_record`` if known - Helps users set date filters

**ConsumerModel:**

1. Inherit from specific base classes (Docket, Opinion) not ConsumerModel
2. Add court-specific fields but keep common field names
3. Use Union types when returning multiple model types

**Searchable Fields:**

1. Annotate all filterable fields - Enables better documentation
2. Use appropriate marker types - DateRange for dates, SetFilter for enums
3. Place annotations on the model used for filtering, not necessarily the return type

**params() Interface:**

1. Check ``is_set()`` before accessing filter values
2. Use ``get_enabled_models()`` to skip disabled types
3. Handle None values gracefully


Testing
-------

**ConsumerModel Compliance:**

.. code-block:: python

    def test_scraper_return_type_is_consumer_model():
        """Scraper return types shall inherit from ConsumerModel."""
        return_type = get_return_type_from_generic(MyScraper)
        assert is_consumer_model_subclass(return_type)

**Searchability:**

.. code-block:: python

    def test_searchable_fields_detected():
        """Params shall detect searchable field annotations."""
        params = MyScraper.params()

        fields = params.CaseDocket.get_searchable_fields()
        assert "date_filed" in fields
        assert isinstance(fields["date_filed"].marker, DateRange)

**Filter Values:**

.. code-block:: python

    def test_date_range_filter():
        """Date range filter shall accept gte/lte values."""
        params = MyScraper.params()

        params.CaseDocket.date_filed.gte = date(2024, 1, 1)
        params.CaseDocket.date_filed.lte = date(2024, 12, 31)

        assert params.CaseDocket.date_filed.is_set()


Next Steps
----------

In :doc:`21_async_driver`, we introduce the AsyncDriver - an asynchronous
implementation that processes multiple requests concurrently using worker
coroutines for improved performance on I/O-bound workloads.