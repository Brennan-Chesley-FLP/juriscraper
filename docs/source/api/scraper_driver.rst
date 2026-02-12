Scraper Driver API
==================

The ``scraper_driver`` package provides the core framework for building scrapers
with a clean separation between parsing (Scraper) and I/O (Driver).

.. contents:: Module Contents
   :local:
   :depth: 2

Data Types
----------

Core data types including request types, parsed data, and the base scraper class.

.. automodule:: kent.data_types
   :members:
   :undoc-members:
   :show-inheritance:

Common Utilities
----------------

Base Classes and Models
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: kent.common.models.base
   :members:
   :undoc-members:
   :show-inheritance:

Decorators
~~~~~~~~~~

The ``@step`` decorator for defining scraper parsing steps.

.. automodule:: kent.common.decorators
   :members:
   :undoc-members:
   :show-inheritance:

Exceptions
~~~~~~~~~~

.. automodule:: kent.common.exceptions
   :members:
   :undoc-members:
   :show-inheritance:

Checked HTML
~~~~~~~~~~~~

Validated HTML element wrapper for safe XPath operations.

.. automodule:: kent.common.checked_html
   :members:
   :undoc-members:
   :show-inheritance:

Searchable Annotations
~~~~~~~~~~~~~~~~~~~~~~

Field annotations for search and filter capabilities.

.. automodule:: kent.common.searchable
   :members:
   :undoc-members:
   :show-inheritance:

Request Manager
~~~~~~~~~~~~~~~

.. automodule:: kent.common.request_manager
   :members:
   :undoc-members:
   :show-inheritance:

Deferred Validation
~~~~~~~~~~~~~~~~~~~

.. automodule:: kent.common.deferred_validation
   :members:
   :undoc-members:
   :show-inheritance:

XPath Observer
~~~~~~~~~~~~~~

.. automodule:: kent.common.xpath_observer
   :members:
   :undoc-members:
   :show-inheritance:

Drivers
-------

Driver implementations that handle I/O operations.

Async Driver
~~~~~~~~~~~~

.. automodule:: kent.driver.async_driver
   :members:
   :undoc-members:
   :show-inheritance:

Sync Driver
~~~~~~~~~~~

.. automodule:: kent.driver.sync_driver
   :members:
   :undoc-members:
   :show-inheritance:

Playwright Driver
~~~~~~~~~~~~~~~~~

.. automodule:: kent.driver.playwright_driver
   :members:
   :undoc-members:
   :show-inheritance:

Callbacks
~~~~~~~~~

.. automodule:: kent.driver.callbacks
   :members:
   :undoc-members:
   :show-inheritance:

Development Driver
~~~~~~~~~~~~~~~~~~

The development driver provides debugging and testing capabilities.

.. automodule:: kent.driver.dev_driver.dev_driver
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

.. automodule:: kent.driver.dev_driver.schema
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: kent.driver.dev_driver.errors
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

.. automodule:: kent.driver.dev_driver.speculation
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:
