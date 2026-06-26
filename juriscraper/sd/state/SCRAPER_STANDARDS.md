# Scraper standards (`juriscraper/sd/state/`)

Authoritative conventions for the jkent-based state scrapers. Hand this to
an agent (or read it yourself) before writing or updating a scraper under
`juriscraper/sd/state/`.

Companion docs:
- [`JKENT_REFERENCE.md`](JKENT_REFERENCE.md) — the jkent API surface this doc
  builds on (imports, `@entry`/`@step` injection, `Request`/`HTTPRequestParams`,
  param types, `DriverRequirement`, `PageElement`). Read it if a rule here
  mentions a jkent symbol you don't recognize — these docs are meant to be
  self-contained without reading the jkent source.
- [`CL_MODELS.md`](CL_MODELS.md) — the CourtListener target models; what to name
  model fields (§8).
- [`ENTRY_METHODS.md`](../../../ENTRY_METHODS.md) — the census and taxonomy these
  entry-naming rules came from (§4).

Reference implementation: **NYCoA / Court-PASS**
(`new_york/nycourts_gov/`). When this doc and a real scraper disagree, prefer
this doc; when this doc is silent, copy NYCoA.

> **This doc targets jkent v0.1.0 (`jkent.*`).** Much of the existing fleet was
> written against an older jkent and must be migrated. The most common
> drift: `@step(xsd=...)` — **`xsd=` no longer exists** on `@step`; a single
> `parsers.py` module instead of a `parsers/` package; See
> [Migrating an old scraper](#migrating-an-old-scraper).

---

## 1. What a scraper is

A scraper is **pure parsing logic**. It declares entry points, fetches pages by
yielding `Request`s, and yields `ParsedData` once a page is parsed. All
I/O — HTTP, browser, rate limiting, file storage, retries, persistence — is the
driver's job. A scraper never performs I/O itself.

```python
class FooScraper(BaseScraper[FooDocket]):   # generic over its emitted type
    @entry(FooDocket)
    def dockets_by_bulk(self, court_ids: set[str]) -> Generator[Request, None, None]:
        yield Request(request=HTTPRequestParams(...), continuation=self.parse_list)

    @step
    def parse_list(self, page: PageElement) -> Generator[ScraperYield[FooDocket], None, None]:
        for link in page.find_links(Selector.XPath("//a[@class='case']"), "case links"):
            yield link.follow(continuation=self.parse_detail)

    @step
    def parse_detail(self, page: PageElement) -> Generator[ScraperYield[FooDocket], None, None]:
        yield ParsedData(FooDocket.raw(...))
```

---

## 2. Directory & file layout

```
<state>/<host_slug>/
    __init__.py
    scraper.py          # the BaseScraper subclass
    models.py           # ScrapedData subclasses
    parsers/            # one JKentParser subclass per page-type (see §9)
        __init__.py     #   re-exports the parser classes
        _common.py      #   shared helpers (date parsing, text repair, …)
        <page_type>.py
    README.md           # short: what the site is, quirks, entry points, flows
```

- `<host_slug>` is the scraper's host with dots → underscores
  (`courtpass.nycourts.gov` → `nycourts_gov`, keyed by the meaningful host part).
- `parsers/` is a **package**, not a single `parsers.py`. Trivial scrapers with
  one tiny page may inline extraction in the step, but anything with real
  XPath belongs in a `JKentParser`.

---

## 3. Class metadata (required)

Every scraper sets this full block. All fields are **required** — including
`last_verified`.

```python
class NYCourtPassScraper(BaseScraper[_Yield]):
    court_ids: ClassVar[set[str]] = {"ny"}
    court_url: ClassVar[str] = "https://courtpass.nycourts.gov"
    data_types: ClassVar[set[str]] = {"dockets"}        # {"dockets"|"opinions"|"oral_arguments"|...}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-17"               # YYYY-MM-DD, bump on change
    last_verified: ClassVar[str] = "2026-06-17"         # YYYY-MM-DD last confirmed working
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = [...]   # [] for plain HTTP
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]
```

- `court_ids` is the set of **CourtListener court IDs** this scraper covers.
- `driver_requirements` drives auto-selection of HTTP vs Playwright and the
  browser profile. It is **scraper-wide and binary** (the whole scraper runs
  under HTTP or under Playwright) — never reason about it per-step. Use
  `JS_EVAL` for JS-rendered sites, `FF_ALIKE`/`CHROME_ALIKE` for a profile,
  `*CAP_HANDLER` for captcha/Cloudflare, `STRICTLY_SERIAL` for ViewState/session
  sites. Full member list in [`JKENT_REFERENCE.md`](JKENT_REFERENCE.md) §7.
- `rate_limits` is `pyrate_limiter` `Rate`s; set a real ceiling per site, don't
  leave it `None` for a court that needs throttling.

---

## 4. Entry points — the naming scheme

This is the core standard. An entry point is named for **what it returns** and
**how it addresses records**, and takes the court set as its first argument.

> The driver **seeds** every entry argument (`court_ids`, the `DateRange`, a
> `SpeculativeRange`, …) — an entry never reads `self._params`. And declaring a
> field searchable seeds entries; it does **not** make the driver post-filter
> your output. Any in-scraper filtering must ride down the chain in
> `accumulated_data`. See [`JKENT_REFERENCE.md`](JKENT_REFERENCE.md) §2.

### The shape

```
<records>_by_<addressing-mode>(court_ids: set[str], <addressing-arg>)
```

- **`court_ids: set[str]` is the first argument of every entry** — *except* the
  single-record direct lookup, which takes `court_id: str` (exactly one court).
- `<records>` is the plural record noun: `dockets`, `opinions`,
  `oral_arguments`, … (singular for the single-record lookup: `docket_by_number`).

### The canonical entries (for dockets — swap the noun for other record types)

| Entry | When to use | Addressing arg |
| --- | --- | --- |
| `dockets_by_filing_date(court_ids, date_range)` | court lets you enumerate by a date it exposes | `date_range: DateRange` |
| `dockets_by_number(court_ids, docket_number)` | public docket-number space we walk/speculate (by year or range) | `docket_number: SpeculativeRange \| YearlySpeculativeRange` |
| `dockets_by_internal_id(court_ids, internal_id)` | an opaque internal ID we've found worth probing | `internal_id: SpeculativeRange \| YearlySpeculativeRange` |
| `dockets_by_bulk(court_ids)` | the site only really lets you pull everything (e.g. NYCoA) | — |
| `dockets_by_number_prefix(court_ids, prefix)` | enumerate along a number prefix (e.g. Alaska) | `prefix: int` (or as the site requires) |
| `docket_by_number(court_id, docket_number)` | fetch one specific, already-known docket | `court_id: str`, `docket_number: str` |

### Swap rules

- **Date type:** if the searchable date isn't the filing date, swap the
  qualifier for the date the court actually exposes:
  `dockets_by_argument_date`, `dockets_by_decision_date`, etc.
- **Record noun:** for non-docket scrapers swap `dockets` → `opinions`,
  `oral_arguments`, etc. — and the singular accordingly
  (`opinion_by_number`, `oral_argument_by_number`).
- **Bulk + client-side filtering:** a `*_by_bulk` entry may still accept
  optional client-side filter params (e.g. NYCoA filters the full pull by an
  argument/decision date window) — but the *addressing mode* is bulk, so the
  name stays `*_by_bulk`. Only name it `*_by_<date>` when the **court** drives
  the date search server-side.

### Speculative params

`dockets_by_number` / `dockets_by_internal_id` take a `Speculative` param
(`SpeculativeRange` for a flat ID space, `YearlySpeculativeRange` for
year-partitioned IDs) so the driver can probe and advance. Name the param for
its role (`docket_number`, `internal_id`) — **not** for its concrete range
subtype.

### Multi-court speculative entries

A speculative entry is the **one** §4 exception to "`court_ids` first": it
can't take `court_ids` (or any other argument) at all. The driver dispatches
a speculative entry with **only** its speculative param — it calls
`entry(<speculative_param>=<range>)` and never binds the other parameters —
so a `court_ids: set[str]` argument would be unbound and the call would raise
`TypeError`. (Seeding confirms this: `initial_seed` stores only the
speculative template and discards the rest.) So **don't** consolidate a
multi-court speculative scraper into `dockets_by_number(court_ids, …)` — it
will not run. Two correct shapes:

- **Court carried in the speculative param (preferred — one canonical
  entry).** Use the shared **`CourtRange`** (`juriscraper/state/common/params.py`)
  — a `SpeculativeRange` carrying a `court_id` plus a `search_key()` hook — and
  seed once per court. `Speculative.from_int` copies via `model_copy`, so it
  preserves `court_id` (and any subclass fields) as the driver advances. When
  the site addresses courts by a non-CL key (a letter prefix, a numeric id, …),
  subclass `CourtRange` and override `search_key()` to translate, typically via
  a `court_id`-keyed dict. This keeps a single `dockets_by_number` entry across
  many courts. See California (`appellatecases_courtinfo_ca_gov`):
  `CaCourtRange(CourtRange)` maps the CL `court_id` to the site's case-number
  prefix. (If a single CL court id legitimately spans several distinct
  number-spaces, carry an extra discriminator field on the subclass.)
- **One entry per court** (court encoded in the method name, no `court_ids`
  arg), e.g. Alaska's `fetch_supreme_court_docket` /
  `fetch_court_of_appeals_docket`. Fine for two or three courts; prefer the
  first shape when the count grows.

### Example

```python
@entry(NYCourtPassDocket)
def docket_by_number(self, court_id: str, docket_number: str) -> Generator[Request, None, None]:
    """Look up one docket by its APL/CTQ/JCR number."""
    ...

@entry(NYCourtPassDocket)
def dockets_by_bulk(self, court_ids: set[str]) -> Generator[Request, None, None]:
    """NYCoA only exposes the whole docket set; pull it and filter locally."""
    ...
```

---

## 5. Steps (`@step`)

Steps are decorated parse methods. The decorator injects by **parameter name** —
declare only what you use (full list + the "can't call a `@step` directly in
tests" caveat in [`JKENT_REFERENCE.md`](JKENT_REFERENCE.md) §3):

| Param | Injected value |
| --- | --- |
| `page` | `PageElement` (preferred — enables selector observation; see §9) |
| `json_content` | parsed JSON |
| `text` | decoded body string |
| `response` | the `Response` |
| `request` / `previous_request` | current / parent `Request` |
| `accumulated_data` | dict carried down the request chain |
| `local_filepath` | downloaded file path (archive responses; `None` otherwise) |

`@step` accepts only: `priority`, `encoding` (default `"utf-8"`), `await_list`,
`auto_await_timeout`. **There is no `xsd=`** — drop it on migration.

- `await_list` (Playwright only; HTTP driver ignores it): list of
  `WaitForLoadState` / `WaitForSelector` / `WaitForURL` / `WaitForTimeout`. Use
  it on every JS-driven step that depends on async content.
- `encoding` governs `text` injection only; HTML parsing auto-detects from the
  bytes.
- Carry per-page state in `accumulated_data`, **never on `self`** — steps must
  be stateless (one scraper instance is reused across all executions).

### Priorities

Lower number = runs sooner. Default is **9** (leave `priority` unset).

- **Descending by depth.** Within a multi-hop flow, give shallower steps higher
  numbers and deeper steps lower numbers, so in-flight cases finish before new
  ones start (NYCoA: 6 → 5 → 4 → 3). Exact numbers don't matter; the
  monotonic descent does. The rule of thumb here is add one for every step between
  this one and the final set of downloads or the end of the step chain.
- **0 and 1 are reserved for `archive=True` (download) requests.** `archive=True`
  auto-assigns priority 1; use explicit `priority=0` for the most
  time-sensitive downloads (stale server state). Keep all non-download flow
  steps at **2 or higher**.

---

## 6. `deduplication_key`

The default key is a sha256 of method+URL+params+data. Override it with a
**stable, human-readable** key so the same logical request dedups across runs
even when the URL carries volatile tokens (ViewState, session ids).

- Format: **`<continuation-or-record>:<identifying-args>`**, colon-delimited.
  - `f"docket_by_number:{docket_number}"`
  - `f"docket_detail:{search_page}:{search_row}"`
  - `f"docket_filing_detail:{docket_number}"`
- **No court-id prefix.** Keys are already scoped per-scraper/per-run; the
  ad-hoc `gactapp-`/`tames-` prefixes in the old fleet are not the standard.
- **File downloads** Use something unique here, if we're lucky, it's something like
`f"{docket_number}-{docket_sequence_number}-{filename}.{file_extension}", but not all
court sites have unique filenames, or even visible filenames. These will be used in actual filenames
so avoid using colons.
- **`SkipDeduplicationCheck()`** only for genuinely non-idempotent requests:
  pagination postbacks, session warmups. Don't use it to paper over a key you
  could make stable.

---

## 7. Requests, navigation & downloads

- Build requests with `Request(request=HTTPRequestParams(...), continuation=...)`,
  or — preferred when the page gives you the affordance — `link.follow(...)` /
  `form.submit(...)` from the `PageElement` API. Form/link helpers attach `via=`
  metadata so the Playwright driver can replay the browser action.
- `continuation` may be the bound method (`self.parse_x`) — it's auto-resolved
  to its name and the target step's priority is inherited.
- Pass data forward via `accumulated_data=`; it is deep-copied per request, so
  sibling requests never share mutable state.
- **Downloads:** `archive=True`. The file lands locally and is injected into the
  continuation as `local_filepath`. Emit a separate file model linked back to
  its parent record by a shared key (NYCoA: `docket_number` on both
  `NYCourtPassDocket` and `NYCourtPassFile`).

---

## 8. Models (`models.py`)

- Subclass `jkent.common.data_models.ScrapedData` (a pydantic `BaseModel`).
- One model per logical record; nest child models (entries, attorneys, files)
  as typed lists.
- **Field-level docstrings** on every non-obvious field (see NYCoA `models.py`).
- Construct via **`Model.raw(...)`** in steps (deferred validation) so a partial
  parse surfaces as a validation error at confirm time, not a hard crash mid-run.
- Include provenance fields where useful: `source_url`, `source_entry_point`,
  and any cross-page join key.
- Models should hew as close as possible to the CourtListener models we're targetting
see CL_MODELS.md. Prefer field names to align, for example `docket_number` instead of `case_number`.
- Field-cleaning types (`HarmonizedCaseName`, `CleanString`) are **not yet
  available in this tree** — see [Open items](#open-items). Until they're
  ported, use plain `str` and clean in the parser.

---

## 9. Parsers (`parsers/`)

Page extraction lives in `JKentParser[T]` subclasses (`jkent.common.parser`),
one per page-type, in its own module under `parsers/`:

```python
class DocketResultsParser(JKentParser[NYCourtPassDocket]):
    def __call__(self, page: PageElement) -> list[DeferredValidation[NYCourtPassDocket]]:
        ...
```

- Returns one `DeferredValidation[T]` per logical record on the page
  (single-record page → one-element list; row page → one per row).
- The scraper step calls the parser and merges its `raw_data`, keeping
  navigation concerns (postbacks, pagination, downloads) in the step — see
  NYCoA's thin `_extract_*` adapters.
- `JKentParser.from_string` / `from_file` let you exercise a parser against
  saved HTML offline — **write parser tests this way.**

### `PageElement` query API — use count assertions

Every query takes a human description and `min_count` / `max_count`. A
mismatch raises `HTMLStructuralAssumptionException`, which is how the framework
detects structural drift — **lean on it**:

```python
rows = page.query(XPath("//table[@id='results']//tr"), "result rows", min_count=1)
links = page.find_links(Selector.XPath("//a[@class='case']"), "case links", min_count=0)
```

Use `min_count=0` only when genuinely-empty is valid; otherwise assert the
structure you expect so a silent site change fails loudly.

### Stay on the `PageElement` API — never reach into `._element`

Use only the public `PageElement` surface — `query` / `query_strings` /
`text_content` / `get_attribute` / `inner_html` / `find_links` / `find_form`.
**Never** touch `cell._element` (the wrapped lxml node) or import `lxml`
directly in a parser. Beyond being private, the wrapping depth is not stable:
the `@step` `page` injection hands you a *double*-wrapped element while
`JKentParser.from_string`/`from_file` give a *single*-wrapped one, so
`._element._element` works in production and `AttributeError`s under your
offline parser test (or vice-versa) — a silent mismatch that fakes empty
results.

When `text_content()` collapses markup you need (e.g. `<br>`/`<p>` that delimit
lines/blocks within one cell), reconstruct from **`cell.inner_html()`** — it
returns the cell's markup *including its leading text node* — then transform
the string (`<br>`→`\n`, block separators → boundaries, strip tags, unescape).
`query_strings` can't substitute here: it returns only string values (text
nodes / attributes), so structural markers are already gone from its result.

---

## 10. HTTP status handling

The framework classifies status codes into SUCCESSFUL / TRANSIENT (retry) /
PERSISTENT (fail-fast). Override only per-site oddities by shadowing
`HTTP_CODE_TYPES = {...}` on the class (a code there wins over the default). For
"200 with an error in the body" (soft-404s, session-timeout pages), override
`actually_successful(self, response) -> bool`.

---

## 11. Migrating an old scraper

Checklist to bring a pre-v0.1.0 scraper to this standard:

1. **Imports** → `jkent.common.decorators`, `jkent.data_types`,
   `jkent.common.page_element`, `jkent.common.parser`
   (full imports map in [`JKENT_REFERENCE.md`](JKENT_REFERENCE.md) §1).
2. **Annotate Selectors** Every selector must specify if it is CSS or XPath.
3. **Normalize** model field names to align with CL_MODELS.md examples where possible
4. **Rename entry points** to the §4 scheme; make `court_ids: set[str]` the
   first arg (or `court_id: str` for the single-record lookup).
5. **Split `parsers.py` → `parsers/` package** (one module per page-type +
   `_common.py`), parsers subclassing `JKentParser[T]`. Replace any
   `._element`/raw-lxml access with the public `PageElement` API — usually
   `inner_html()` when you need markup `text_content()` collapses (see §9,
   "Stay on the `PageElement` API").
6. **Fill the full metadata block** (§3), including `last_verified`.
7. **Normalize `deduplication_key`s** to the §6 format; drop court-id prefixes.
8. **Audit priorities**: descending-by-depth, downloads at 0–1, flow ≥ 2.
9. **Add/refresh `CC_NOTES.md`** with entry points and flow description.
  Rename DESIGN.md or README.md to CC_NOTES.md to standardize the name.


---

## Ongoing maintenance of this file

If you need to consult another codebase for information, either inline the
information you gather in this document if it can be condensed to fit, put it in
one of the existing linked reference documents as appropriate, or make another
reference document and link to it from this one.