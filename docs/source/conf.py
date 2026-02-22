# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import logging
import os
import sys

# -- Path setup --------------------------------------------------------------
sys.path.insert(0, os.path.abspath("../.."))
sys.path.insert(0, os.path.abspath("_ext"))


# Custom filter to suppress duplicate object description warnings
class DuplicateObjectFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "duplicate object description" in record.getMessage()


for logger_name in ["sphinx", "sphinx.domains", "sphinx.domains.python"]:
    logging.getLogger(logger_name).addFilter(DuplicateObjectFilter())

# -- Project information -----------------------------------------------------
project = "Juriscraper"
copyright = "2025, Free Law Project"
author = "Free Law Project"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.inheritance_diagram",
    "sphinx.ext.graphviz",
    "sphinx.ext.intersphinx",
    "sphinxcontrib.mermaid",
    "sphinx_immaterial",
    "scraper_index",
]

templates_path = ["_templates"]
exclude_patterns: list[str] = []

# -- Options for HTML output -------------------------------------------------
html_theme = "sphinx_immaterial"
html_static_path = ["_static"]

html_theme_options = {
    "font": False,
    "repo_url": "https://github.com/freelawproject/juriscraper",
    "repo_name": "freelawproject/juriscraper",
    "features": [
        "search.suggest",
        "search.highlight",
        "search.share",
        "navigation.expand",
        "navigation.top",
        "toc.follow",
    ],
}

# -- Extension configuration -------------------------------------------------

# Napoleon settings (for Google/NumPy style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_use_param = True
napoleon_use_rtype = True

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_typehints = "description"
autodoc_class_signature = "separated"

# Inheritance diagram settings
inheritance_graph_attrs = {"rankdir": "TB", "size": '"8.0, 10.0"'}
inheritance_node_attrs = {"shape": "box", "fontsize": 11, "height": 0.5}

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# Graphviz settings
graphviz_output_format = "svg"

# RST prolog - substitutions available in all documents
rst_prolog = """
.. |check| unicode:: U+2714 .. CHECK MARK
.. |x| unicode:: U+2718 .. CROSS MARK
"""
