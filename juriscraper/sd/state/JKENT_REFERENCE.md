# jkent API reference (for `juriscraper/sd/state/` scrapers)

The jkent framework surface a scraper author needs, so writing or migrating a
scraper under `juriscraper/sd/state/` doesn't require reading the jkent source.

Companion to [`SCRAPER_STANDARDS.md`](SCRAPER_STANDARDS.md) (the conventions),
[`CL_MODELS.md`](CL_MODELS.md) (what to name model fields), and
[`ENTRY_METHODS.md`](../../../ENTRY_METHODS.md) (entry-naming taxonomy). This doc
is **what jkent gives you**; the standards doc is **how we use it**.

> Snapshot of **jkent v0.1.0**, taken 2026-06. Symbols and signatures below are
> the source of truth at that version; if something here disagrees with the
> installed `jkent`, trust the installed package and update this doc. Paths like
> `jkent/data_types.py` are pointers into the jkent checkout for verification.

---

## 1. Imports — what comes from where

```python
# Decorators that mark entry points and parse steps
from jkent.common.decorators import entry, step

# The base class every scraper subclasses, plus the request/response/value types
from jkent.data_types import (
    BaseScraper,            # Generic[YieldType]; subclass this
    Request,                # what entries/steps yield to fetch a page
    HTTPRequestParams,      # the HTTP params inside a Request
    HttpMethod,             # GET/POST/...
    ParsedData,             # wrap a finished record: yield ParsedData(data=model)
    Response,               # injectable into a step
    ScraperStatus,          # IN_DEVELOPMENT / ... for the `status` ClassVar
    DriverRequirement,      # the `driver_requirements` ClassVar values (see §7)
    XPath, CSS,             # selector wrappers (also via Selector.XPath/.CSS)
    SkipDeduplicationCheck, # opt out of dedup for non-idempotent requests
)

# Entry-parameter value types (the args the driver seeds — see §2)
from jkent.common.param_models import (
    DateRange,              # {start: date, end: date}, both required
    SpeculativeRange,       # flat integer ID space to probe
)
from juriscraper.state.common.params import (
    YearlySpeculativeRange, # year-partitioned ID space (+ [key] persistence)
)

# Page-extraction API for HTML steps/parsers (see §6)
from jkent.common.page_element import PageElement

# Model base + deferred-validation helper (see §5)
from jkent.common.data_models import ScrapedData

# Parser base for offline-testable extraction (see SCRAPER_STANDARDS §9)
from jkent.common.parser import JKentParser
```

---

## 2. Entry points — the driver seeds the arguments

`@entry(ReturnModel)` marks a generator method as an entry point
(`jkent/common/decorators.py`). The decorator inspects the signature and builds a
per-entry pydantic model from the parameter annotations; **the driver validates
and seeds those parameters** from its run config. The scraper does **not** read
`self._params` for them — declare what you need as typed arguments and the driver
supplies them.

- The first argument is the court set: **`court_ids: set[str]`** (or
  `court_id: str` for a single-record lookup). See SCRAPER_STANDARDS §4 for the
  naming scheme.
- Subsequent arguments are any type pydantic can validate: `str`, `int`, `date`,
  `set[str]`, a pydantic `BaseModel`, or one of the param types below. A bare,
  untyped `tuple` is rejected — use `tuple[int, str]` or a model.
- A parameter whose type subclasses `Speculative` (e.g. `SpeculativeRange`) makes
  the entry **speculative**: the driver seeds, tracks, and extends the probe
  range itself.

### Param value types (`jkent/common/param_models.py`)

| Type | Fields | Use for |
| --- | --- | --- |
| `DateRange` | `start: date`, `end: date` (both **required**, inclusive) | date-window entries (`*_by_filing_date`, `*_by_argument_date`) |
| `SpeculativeRange` | `min: int`, `soft_max: int = 0`, `gap: int = 10` | walking a flat integer ID space |
| `YearlySpeculativeRange` | adds a per-year `year`; one template per year | year-partitioned IDs |

Because `DateRange.start`/`.end` are always populated by the driver, an entry
never needs a "default date range" fallback — a full-history pull is just a wide
range the driver seeds.

### Searchable fields do **not** post-filter (important)

Declaring a field searchable on a model lets the driver **seed entries** from it
— it does **not** make the driver filter your yielded records. So any in-scraper
filtering (restricting an all-courts feed to `court_ids`, a date window the
server didn't enforce, etc.) must be done **inside the scraper** and the filter
values must travel down the request chain via `accumulated_data` (seeded in the
entry from its arguments), not re-read from params in a later step. This is why
the TR scrapers carry `accumulated_data["target_courts"]`.

---

## 3. Steps — injection is by parameter name

`@step(...)` wraps a parse method. At runtime the wrapper receives the
`Response` and injects arguments **by parameter name** — declare only what you
use (`jkent/common/decorators.py`):

| Param | Injected value |
| --- | --- |
| `page` | `PageElement` (enables selector observation — see §6) |
| `json_content` | parsed JSON body |
| `text` | decoded body string |
| `lxml_tree` | parsed lxml tree (when you want raw lxml instead of `PageElement`) |
| `response` | the `Response` |
| `request` | the current `Request` |
| `previous_request` | the parent `Request` |
| `accumulated_data` | the dict carried down the request chain |
| `local_filepath` | downloaded file path on archive responses; `None` otherwise |

`@step` accepts only: `priority`, `encoding` (default `"utf-8"`), `await_list`,
`auto_await_timeout`. There is **no `xsd=`** (removed in v0.1.0). See
SCRAPER_STANDARDS §5 for priorities and §6 for `deduplication_key`.

**Testing implication:** because the wrapper expects a real `Response` and
injects from it, you **cannot** unit-test a `@step` method by calling it with a
plain dict. Test either (a) the underlying logic if you factored it into a plain
helper (the `TRPortalMixin._tr_handle_*` methods are written this way precisely
so they're callable with `(json_content, accumulated_data)` directly), or (b) an
HTML parser via `JKentParser.from_string` / `from_file` (§6).

---

## 4. Requests, downloads & dedup (`Request`, `HTTPRequestParams`)

Yield a `Request` to fetch a page; yield `ParsedData` to emit a finished record.

```python
Request(
    request=HTTPRequestParams(method=HttpMethod.GET, url=url,
                              headers={"Accept": "application/json"}),
    continuation=self.parse_next,        # bound method or its name; priority inherited
    accumulated_data={...},              # deep-copied per request; safe to fan out
    deduplication_key="continuation:ids",# stable key — see SCRAPER_STANDARDS §6
)
```

`Request` fields you'll use (`jkent/data_types.py`):

| Field | Meaning |
| --- | --- |
| `request` | the `HTTPRequestParams` |
| `continuation` | next step: bound method (auto-resolved to its name; inherits the target's priority) or a name string |
| `accumulated_data` | dict carried to the continuation (deep-copied per request) |
| `priority` | queue order, lower runs sooner; usually set on `@step` instead |
| `deduplication_key` | `str` for a stable key, or `SkipDeduplicationCheck()` to opt out (pagination postbacks, session warmups only) |
| `archive` | `True` to download the body to disk; auto-assigns priority 1; continuation gets `local_filepath` |
| `expected_type` | hint for archive downloads (`"pdf"`, `"audio"`, `"video"`, ...) |
| `nonnavigating` | `True` for a fetch that isn't a page navigation (e.g. an API pagination call under a browser driver) |
| `via` | `ViaLink`/`ViaFormSubmit` metadata; set for you by `link.follow()` / `form.submit()` |
| `bypass_rate_limit` | skip the rate limiter for this one request |

`HTTPRequestParams` fields (`jkent/data_types.py`): `method`, `url`, `params`,
`data`, `json`, `headers`, `cookies`, `files`, `auth`, `timeout`,
`allow_redirects` (default `True`), `proxies`, `verify` (default `True` — set
`False` for a host with a broken cert chain), `stream`, `cert`.

---

## 5. Models (`ScrapedData`, `Model.raw`)

Models subclass `ScrapedData` (a pydantic `BaseModel`, in
`jkent/common/data_models.py`). Field naming follows
[`CL_MODELS.md`](CL_MODELS.md) — `docket_number`, `court` (a CourtListener
court-id string), `date_*`, etc.

Two ways to build a record in a step:

- **`Model(**fields)`** — validates immediately. Fine when you have all fields.
- **`Model.raw(**fields)`** — returns a `DeferredValidation[Model]`; validation
  is deferred to `.confirm()` (the framework confirms at emit time). Prefer this
  for page-parsed records so a partial parse surfaces as a validation error at
  confirm time rather than crashing mid-run. `request_url=` is a **reserved**
  argument of `.raw()` (used for error reporting) — a model with its own
  `request_url` field must be constructed directly.

Emit with `yield ParsedData(data=model)` (or `ParsedData(deferred_validation)`).

---

## 6. `PageElement` query API (HTML steps/parsers)

`PageElement` (`jkent/common/page_element.py`) is the preferred HTML interface;
injecting `page` enables selector observation. Every query takes a human
description and `min_count`/`max_count`; a mismatch raises
`HTMLStructuralAssumptionException`, which is how structural drift is detected —
lean on it.

```python
rows  = page.query(XPath("//table[@id='results']//tr"), "result rows", min_count=1)
links = page.find_links(Selector.XPath("//a[@class='case']"), "case links", min_count=0)
form  = page.find_form(CSS("#search"), "search form")
yield link.follow(continuation=self.parse_detail)      # attaches via= metadata
yield form.submit(data={...}, continuation=self.parse_results)
```

Selectors must be explicitly typed: `XPath(...)` / `CSS(...)` (or
`Selector.XPath` / `Selector.CSS`). Use `min_count=0` only when genuinely-empty
is valid. Heavy XPath extraction belongs in a `JKentParser[T]` subclass
(SCRAPER_STANDARDS §9), which you can exercise offline with
`JKentParser.from_string(html)` / `from_file(path)`.

---

## 7. `driver_requirements` values (`DriverRequirement`)

Scraper-wide and **binary** — the whole scraper runs under HTTP or under
Playwright; never reason about it per-step (see SCRAPER_STANDARDS §3). `[]` means
plain HTTP (this is correct for pure JSON/REST or plain-HTML sites). Members
(`jkent/data_types.py`):

| Member | When |
| --- | --- |
| `JS_EVAL` | site needs JavaScript executed (SPA / JS-rendered content) |
| `FF_ALIKE` / `CHROME_ALIKE` | requires a Firefox-like / Chrome-like browser profile |
| `HCAP_HANDLER` / `RCAP_HANDLER` / `CFCAP_HANDLER` | hCaptcha / reCAPTCHA / Cloudflare challenge handling |
| `IMAGE_CAPTCHA_HANDLER` | image-captcha solving |
| `FOLLOW_REDIRECTS` | driver should follow redirects |
| `STRICTLY_SERIAL` | ViewState/session sites that must run one request at a time |

---

## 8. HTTP status handling

The framework classifies status codes SUCCESSFUL / TRANSIENT (retry) /
PERSISTENT (fail-fast). Override per-site oddities by shadowing
`HTTP_CODE_TYPES = {...}` on the scraper class (an entry there wins over the
default). For "200 with an error body" (soft-404s, session-timeout pages),
override `actually_successful(self, response) -> bool`. See SCRAPER_STANDARDS
§10.

---

## 9. CourtListener target models

The downstream database your records merge into. Field names and semantics are
documented in [`CL_MODELS.md`](CL_MODELS.md) — match them so the merge is
mechanical (e.g. `docket_number` not `case_number`; `court` is a court-id
string; dates are `date` objects named `date_*`). Capture useful fields even
when CL has no column yet; add the field to the model rather than dropping data.
