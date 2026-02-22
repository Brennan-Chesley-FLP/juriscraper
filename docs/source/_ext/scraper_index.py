"""Sphinx extension for auto-generating the Site Scrapers documentation.

Discovers all opinion and oral argument scrapers via
juriscraper.lib.importer.build_module_list(), looks up court names from
courts-db, instantiates each scraper to get its target URL, generates
coverage SVG maps, and produces tables with links to the court websites.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

if TYPE_CHECKING:
    from sphinx.application import Sphinx

_logger = logging.getLogger(__name__)

# Categories in display order
CATEGORIES = [
    "federal_appellate",
    "federal_district",
    "federal_bankruptcy",
    "federal_special",
    "administrative_agency",
    "state",
    "territories",
]

CATEGORY_LABELS = {
    "federal_appellate": "Federal Appellate",
    "federal_district": "Federal District",
    "federal_bankruptcy": "Federal Bankruptcy",
    "federal_special": "Federal Special",
    "administrative_agency": "Administrative Agency",
    "state": "State",
    "territories": "Territories",
}

_scraper_data: dict | None = None


def _get_scraper_url(mod_path: str) -> str:
    """Instantiate a scraper Site class and return its URL.

    Returns empty string if the scraper has no URL or instantiation fails.
    """
    try:
        mod = importlib.import_module(mod_path)
        site = mod.Site()
        return site.url or ""
    except Exception:
        return ""


def get_scraper_data() -> dict[str, dict[str, dict[str, Any]]]:
    """Discover all scrapers and build the mapping data structure.

    Returns a dict keyed by category, then short_name, with opinion/oral_arg
    module paths, their court site URLs, and court metadata from courts-db.
    """
    global _scraper_data
    if _scraper_data is not None:
        return _scraper_data

    from courts_db import court_dict

    from juriscraper.lib.importer import build_module_list

    opinions = build_module_list("juriscraper.opinions.united_states")
    oral_args = build_module_list("juriscraper.oral_args.united_states")

    data: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "opinions": [],
                "oral_args": [],
                "court_name": "",
                "court_type": "",
            }
        )
    )

    # opinions/oral_args entries are now (mod_path, url) tuples
    for mod_path in opinions:
        parts = mod_path.split(".")
        category = parts[3]
        short_name = parts[4]
        url = _get_scraper_url(mod_path)
        data[category][short_name]["opinions"].append((mod_path, url))

    for mod_path in oral_args:
        parts = mod_path.split(".")
        category = parts[3]
        short_name = parts[4]
        url = _get_scraper_url(mod_path)
        data[category][short_name]["oral_args"].append((mod_path, url))

    # Enrich with court metadata from courts-db
    for cat_data in data.values():
        for short_name, entry in cat_data.items():
            court = court_dict.get(short_name)
            if court:
                entry["court_name"] = court.get("name", "")
                entry["court_type"] = court.get("type", "")

    _scraper_data = dict(data)
    return _scraper_data


def _build_table(
    cat_data: dict[str, dict[str, Any]],
) -> list[nodes.Node]:
    """Build a docutils table node from category data.

    Returns a list of nodes: index entries, targets, and the table itself.
    The index entries make courts searchable via Sphinx search and the
    general index. The targets provide anchor links (e.g. #scraper-ca1).
    """
    result_nodes: list[nodes.Node] = []

    table = nodes.table(classes=["scraper-table"])
    tgroup = nodes.tgroup(cols=4)
    table += tgroup

    tgroup += nodes.colspec(colwidth=15)
    tgroup += nodes.colspec(colwidth=30)
    tgroup += nodes.colspec(colwidth=30)
    tgroup += nodes.colspec(colwidth=30)

    # Header row
    thead = nodes.thead()
    tgroup += thead
    header_row = nodes.row()
    thead += header_row
    for text in ["Court ID", "Court Name", "Opinions", "Oral Arguments"]:
        header_row += nodes.entry("", nodes.paragraph(text=text))

    # Body rows
    tbody = nodes.tbody()
    tgroup += tbody

    for short_name in sorted(cat_data.keys()):
        entry_data = cat_data[short_name]
        court_name = entry_data.get("court_name", "")
        anchor_id = f"scraper-{short_name}"

        # Index entries: searchable by court_id and by full court name
        index_entries = [
            ("single", f"{short_name} (scraper)", anchor_id, "", None),
        ]
        if court_name:
            index_entries.append(
                ("single", court_name, anchor_id, "", None),
            )
        result_nodes.append(addnodes.index(entries=index_entries))

        # Place the anchor ID directly on the row so links scroll to it
        row = nodes.row(ids=[anchor_id])
        tbody += row

        # Court ID cell
        id_para = nodes.paragraph("", "", nodes.literal(text=short_name))
        row += nodes.entry("", id_para)

        # Court Name cell
        row += nodes.entry("", nodes.paragraph(text=court_name or "—"))

        # Opinions cell
        op_para = nodes.paragraph()
        for i, (mod_path, url) in enumerate(entry_data["opinions"]):
            if i > 0:
                op_para += nodes.Text(", ")
            display = mod_path.rsplit(".", 1)[1]
            if url:
                ref = nodes.reference("", display, refuri=url)
                op_para += ref
            else:
                op_para += nodes.Text(display)
        if not entry_data["opinions"]:
            op_para += nodes.emphasis(text="—")
        row += nodes.entry("", op_para)

        # Oral Arguments cell
        oa_para = nodes.paragraph()
        for i, (mod_path, url) in enumerate(entry_data["oral_args"]):
            if i > 0:
                oa_para += nodes.Text(", ")
            display = mod_path.rsplit(".", 1)[1]
            if url:
                ref = nodes.reference("", display, refuri=url)
                oa_para += ref
            else:
                oa_para += nodes.Text(display)
        if not entry_data["oral_args"]:
            oa_para += nodes.emphasis(text="—")
        row += nodes.entry("", oa_para)

    result_nodes.append(table)
    return result_nodes


class ScraperTableDirective(SphinxDirective):
    """Render a scraper table for a given category.

    Usage::

        .. scraper-table::
           :category: federal_appellate
    """

    has_content = False
    option_spec = {
        "category": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        data = get_scraper_data()
        category = self.options.get("category")

        if category and category not in data:
            return [
                nodes.paragraph(
                    text=f"No scrapers found for category: {category}"
                )
            ]

        if category:
            return _build_table(data[category])

        # No category specified — render all
        result_nodes: list[nodes.Node] = []
        for cat in CATEGORIES:
            if cat not in data:
                continue
            result_nodes.extend(_build_table(data[cat]))
        return result_nodes


# ---------------------------------------------------------------------------
# Coverage map generation
# ---------------------------------------------------------------------------

# Map config: (svg_filename, template, title, color)
MAP_CONFIGS = [
    {
        "key": "state_opinions",
        "svg": "state_opinion_coverage.svg",
        "template": "state_coverage.svg.jinja2",
        "title": "State Opinion Coverage",
        "color": "#2e7d32",
    },
    {
        "key": "state_oral_args",
        "svg": "state_oral_arg_coverage.svg",
        "template": "state_coverage.svg.jinja2",
        "title": "State Oral Argument Coverage",
        "color": "#00695c",
    },
    {
        "key": "federal_opinions",
        "svg": "federal_opinion_coverage.svg",
        "template": "federal_coverage.svg.jinja2",
        "title": "Federal Opinion Coverage",
        "color": "#1565c0",
    },
    {
        "key": "federal_oral_args",
        "svg": "federal_oral_arg_coverage.svg",
        "template": "federal_coverage.svg.jinja2",
        "title": "Federal Oral Argument Coverage",
        "color": "#6a1b9a",
    },
]


def _get_state_scraper_links(app: Sphinx) -> dict[str, str]:
    """Map 2-letter state codes to their highest-level court scraper anchor.

    For each state, find the scraper whose courts-db entry has the
    highest court level (colr > iac > gjc > ljc > trial) and return
    a mapping of state_code -> scraper anchor ID.
    """
    from courts_db import court_dict
    from svg_paths import STATE_NAMES

    data = get_scraper_data()
    state_data = data.get("state", {})
    scraper_names = set(state_data.keys())

    location_to_code: dict[str, str] = {v: k for k, v in STATE_NAMES.items()}
    location_to_code["Washington D.C."] = "DC"

    level_rank = {
        "colr": 0,
        "iac": 1,
        "gjc": 2,
        "gjc & iac": 2,
        "ljc": 3,
        "trial": 4,
    }

    state_links: dict[str, str] = {}
    for code, name in STATE_NAMES.items():
        courts_in_state = {
            cid: c
            for cid, c in court_dict.items()
            if c.get("location") == name and cid in scraper_names
        }
        if not courts_in_state:
            continue
        best = None
        best_rank = 999
        for cid, c in courts_in_state.items():
            rank = level_rank.get(str(c.get("level", "")), 5)
            if rank < best_rank:
                best = cid
                best_rank = rank
        if best:
            state_links[code] = f"scraper-{best}"

    return state_links


def _compute_all_coverage(
    app: Sphinx,
) -> dict[str, Any]:
    """Compute coverage data for all 4 map types.

    Returns a dict keyed by map key with the coverage sets/dicts needed
    for SVG rendering.
    """
    from courts_db import court_dict
    from svg_paths import FEDERAL_CIRCUITS, STATE_NAMES

    data = get_scraper_data()

    # Reverse map: location name -> 2-letter code
    location_to_code: dict[str, str] = {v: k for k, v in STATE_NAMES.items()}
    location_to_code["Washington D.C."] = "DC"

    # --- State coverage (check appellate type via courts-db) ---
    state_opinion_states: set[str] = set()
    state_oa_states: set[str] = set()

    state_data = data.get("state", {})
    for short_name, entry in state_data.items():
        court = court_dict.get(short_name)
        if not court or court.get("type") != "appellate":
            continue
        loc = court.get("location", "")
        code = location_to_code.get(loc)
        if not code:
            continue
        if entry["opinions"]:
            state_opinion_states.add(code)
        if entry["oral_args"]:
            state_oa_states.add(code)

    # --- Federal circuit coverage ---
    fed_data = data.get("federal_appellate", {})

    def _circuit_has(field: str) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for circuit_num in FEDERAL_CIRCUITS:
            if circuit_num == "DC":
                covered = any(
                    s.startswith("cadc") and fed_data[s][field]
                    for s in fed_data
                )
            elif circuit_num.isdigit():
                prefix = f"ca{circuit_num}"
                covered = any(
                    (s == prefix or s.startswith(f"{prefix}_"))
                    and fed_data[s][field]
                    for s in fed_data
                )
            else:
                covered = False
            result[circuit_num] = covered
        return result

    return {
        "state_opinions": state_opinion_states,
        "state_oral_args": state_oa_states,
        "federal_opinions": _circuit_has("opinions"),
        "federal_oral_args": _circuit_has("oral_args"),
    }


def generate_coverage_maps(app: Sphinx) -> dict[str, str]:
    """Generate all 4 SVG coverage maps.

    Returns a dict of svg_filename -> svg_content for inline embedding.
    """
    from jinja2 import Environment, FileSystemLoader
    from svg_paths import (
        FEDERAL_CIRCUITS,
        STATE_NAMES,
        STATE_PATHS,
    )

    coverage = _compute_all_coverage(app)
    state_links = _get_state_scraper_links(app)

    # Link target base: relative path from coverage page to scrapers index
    index_url = "index.html"

    template_dir = Path(app.srcdir) / "_templates"

    env = Environment(
        loader=FileSystemLoader(str(template_dir)), autoescape=False
    )

    # Shared state path data
    all_state_paths = {
        code: {"path_data": STATE_PATHS[code]}
        for code in STATE_NAMES
        if STATE_PATHS.get(code)
    }

    circuit_labels = {
        "1": {"x": 890, "y": 145},
        "2": {"x": 820, "y": 175},
        "3": {"x": 805, "y": 230},
        "4": {"x": 780, "y": 290},
        "5": {"x": 520, "y": 430},
        "6": {"x": 680, "y": 250},
        "7": {"x": 600, "y": 230},
        "8": {"x": 480, "y": 200},
        "9": {"x": 120, "y": 280},
        "10": {"x": 330, "y": 310},
        "11": {"x": 700, "y": 410},
        "DC": {"x": 870, "y": 280},
    }

    svg_contents: dict[str, str] = {}

    for cfg in MAP_CONFIGS:
        template = env.get_template(cfg["template"])
        cov = coverage[cfg["key"]]

        if cfg["template"].startswith("state_"):
            # State map: cov is a set of 2-letter state codes
            state_map_data = {}
            for code, name in STATE_NAMES.items():
                path_data = STATE_PATHS.get(code, "")
                if not path_data:
                    continue
                anchor = state_links.get(code)
                state_map_data[code] = {
                    "name": name,
                    "path_data": path_data,
                    "covered": code in cov,
                    "unknown": False,
                    "link": (f"{index_url}#{anchor}" if anchor else ""),
                }
            svg = template.render(
                states=state_map_data,
                title=cfg["title"],
                covered_color=cfg["color"],
            )
        else:
            # Federal map: cov is a dict[str, bool]
            circuit_map_data = {}
            for circuit_num, state_codes in FEDERAL_CIRCUITS.items():
                anchor = (
                    "scraper-cadc"
                    if circuit_num == "DC"
                    else f"scraper-ca{circuit_num}"
                )
                circuit_map_data[circuit_num] = {
                    "state_codes": state_codes,
                    "covered": cov.get(circuit_num, False),
                    "unknown": False,
                    "link": f"{index_url}#{anchor}",
                }
            svg = template.render(
                circuits=circuit_map_data,
                states=all_state_paths,
                circuit_labels=circuit_labels,
                title=cfg["title"],
                covered_color=cfg["color"],
            )

        svg_contents[cfg["svg"]] = svg

    _logger.info(
        "scraper_index: generated 4 coverage maps "
        "(state opinions: %d/%d, state OA: %d/%d, "
        "federal opinions: %d/%d, federal OA: %d/%d)",
        len(coverage["state_opinions"]),
        len(STATE_NAMES),
        len(coverage["state_oral_args"]),
        len(STATE_NAMES),
        sum(coverage["federal_opinions"].values()),
        len(coverage["federal_opinions"]),
        sum(coverage["federal_oral_args"].values()),
        len(coverage["federal_oral_args"]),
    )

    return svg_contents


# ---------------------------------------------------------------------------
# RST page generation
# ---------------------------------------------------------------------------


def _generate_coverage_pages(
    app: Sphinx, svg_contents: dict[str, str]
) -> None:
    """Generate the 4 coverage RST pages with inlined SVGs.

    SVGs are embedded via ``.. raw:: html`` so that links and hover
    effects remain interactive (``<img>`` tags don't support SVG
    interactivity).
    """
    scrapers_dir = Path(app.srcdir) / "scrapers"
    scrapers_dir.mkdir(exist_ok=True)

    pages = [
        (
            "federal_opinion_coverage.rst",
            "Federal Opinion Coverage",
            "federal_opinion_coverage.svg",
        ),
        (
            "federal_oral_arg_coverage.rst",
            "Federal Oral Argument Coverage",
            "federal_oral_arg_coverage.svg",
        ),
        (
            "state_opinion_coverage.rst",
            "State Opinion Coverage",
            "state_opinion_coverage.svg",
        ),
        (
            "state_oral_arg_coverage.rst",
            "State Oral Argument Coverage",
            "state_oral_arg_coverage.svg",
        ),
    ]

    for filename, title, svg_file in pages:
        underline = "=" * len(title)
        svg_body = svg_contents[svg_file]
        # Indent each line of the SVG by 3 spaces for the raw directive
        indented_svg = "\n".join(
            f"   {line}" for line in svg_body.splitlines()
        )
        content = f"""\
{title}
{underline}

.. raw:: html

{indented_svg}
"""
        (scrapers_dir / filename).write_text(content)


def generate_scraper_pages(app: Sphinx) -> None:
    """Generate all scrapers/ RST pages at build time."""
    data = get_scraper_data()

    scrapers_dir = Path(app.srcdir) / "scrapers"
    scrapers_dir.mkdir(exist_ok=True)

    total_opinion = sum(
        len(e["opinions"]) for cat in data.values() for e in cat.values()
    )
    total_oa = sum(
        len(e["oral_args"]) for cat in data.values() for e in cat.values()
    )

    # Generate coverage maps and their pages
    svg_contents = generate_coverage_maps(app)
    _generate_coverage_pages(app, svg_contents)

    # Build per-category sections
    sections = []
    for cat in CATEGORIES:
        if cat not in data:
            continue
        label = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
        sections.append(
            f"""{label}
{"^" * len(label)}

.. scraper-table::
   :category: {cat}
"""
        )

    content = f"""\
.. _site-scrapers:

==============
Site Scrapers
==============

All available scrapers in juriscraper, organized by jurisdiction category.
Each entry shows the court identifier along with links to the court
websites scraped for opinions and oral arguments.

**{total_opinion}** opinion scrapers and **{total_oa}** oral argument
scrapers across **{len(data)}** categories.

.. toctree::
   :maxdepth: 1
   :caption: Coverage Maps

   federal_opinion_coverage
   federal_oral_arg_coverage
   state_opinion_coverage
   state_oral_arg_coverage

Scrapers by Category
---------------------

{chr(10).join(sections)}"""

    (scrapers_dir / "index.rst").write_text(content)
    _logger.info(
        "scraper_index: generated scrapers/ pages (%d opinions, %d oral args)",
        total_opinion,
        total_oa,
    )


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("scraper-table", ScraperTableDirective)
    app.connect("builder-inited", generate_scraper_pages)
    return {
        "version": "0.3",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
