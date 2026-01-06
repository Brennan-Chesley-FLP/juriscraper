# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Path setup --------------------------------------------------------------
sys.path.insert(0, os.path.abspath("../.."))
sys.path.insert(0, os.path.abspath("_ext"))

# -- Project information -----------------------------------------------------
project = "Juriscraper"
copyright = "2025, Free Law Project"
author = "Free Law Project"
release = "2.6.98"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.inheritance_diagram",
    "sphinx.ext.graphviz",
    "sphinx.ext.intersphinx",
    "sphinxcontrib.mermaid",
    "court_coverage",  # Custom extension for court coverage docs
]

templates_path = ["_templates"]
exclude_patterns: list[str] = []

# -- Options for HTML output -------------------------------------------------
html_theme = "alabaster"
html_static_path = ["_static"]

# Alabaster theme options
html_theme_options = {
    "description": "Python library for scraping legal opinions",
    "github_user": "freelawproject",
    "github_repo": "juriscraper",
    "github_button": True,
    "github_type": "star",
    "fixed_sidebar": True,
}

# -- Extension configuration -------------------------------------------------

# Napoleon settings (for Google/NumPy style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_type_aliases = None

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
    #    "httpx": ("https://www.python-httpx.org/", None),
}

# Graphviz settings
graphviz_output_format = "svg"

# RST prolog - substitutions available in all documents
rst_prolog = """
.. |check| unicode:: U+2714 .. CHECK MARK
.. |x| unicode:: U+2718 .. CROSS MARK
"""
