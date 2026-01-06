# Juriscraper Documentation

This directory contains the Sphinx documentation for Juriscraper.

## Building the Documentation

### Prerequisites

Make sure you have the dev dependencies installed:

```bash
uv sync --group dev
```

### Build HTML Documentation

```bash
cd docs
make html
```

The built documentation will be in `build/html/`. Open `build/html/index.html` in your browser.

### Clean Build

```bash
cd docs
make clean
make html
```

### Live Reload (Auto-rebuild on Changes)

```bash
cd docs
make livehtml
```

This will start a local server at http://127.0.0.1:8000 that automatically rebuilds and refreshes when you edit documentation files.

## Documentation Structure

- `source/` - Documentation source files (reStructuredText)
  - `index.rst` - Main documentation index
  - `scraper_driver/` - Scraper/Driver architecture docs
    - `index.rst` - Overview and concepts
    - `common.rst` - Common modules (base classes, utilities)
    - `asyncio.rst` - Async driver implementation
    - `sync.rst` - Sync driver implementation
  - `api/` - Complete API reference
    - `scraper_driver.rst` - Driver API reference
    - `sd_scrapers.rst` - New scraper implementations
    - `migration_utils.rst` - Migration utilities
    - `legacy.rst` - Legacy OpinionSite/OralArgumentSite
  - `conf.py` - Sphinx configuration
- `build/` - Built documentation (generated, not in git)

## Writing Documentation

### Documenting a New Module

1. Add docstrings to your Python code (Google or NumPy style)
2. Create or update an `.rst` file in `source/api/`
3. Add the module with `.. automodule::`

Example:

```rst
My New Module
=============

.. automodule:: juriscraper.my_module
   :members:
   :undoc-members:
   :show-inheritance:
```

### Adding Inheritance Diagrams

```rst
.. inheritance-diagram:: juriscraper.my_module.MyClass
   :parts: 1
```

### Adding Mermaid Diagrams

```rst
.. mermaid::

   graph TB
       A[Start] --> B[Process]
       B --> C[End]
```

## Sphinx Extensions

The documentation uses these extensions:

- `sphinx.ext.autodoc` - Extract documentation from docstrings
- `sphinx.ext.napoleon` - Support for Google/NumPy style docstrings
- `sphinx.ext.viewcode` - Add links to source code
- `sphinx.ext.inheritance_diagram` - Generate class inheritance diagrams
- `sphinx.ext.graphviz` - Render Graphviz diagrams
- `sphinx.ext.intersphinx` - Link to other project documentation
- `sphinxcontrib.mermaid` - Render Mermaid diagrams
