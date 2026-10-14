#!/usr/bin/env python3
"""Finish migrating an old California (appellatecases.courtinfo.ca.gov) run DB.

The old databases were produced by the pre-rewrite scraper that lived at
``juriscraper.sd.state.california...`` (commit 78a8808). Two things changed in
the rewrite and must be brought forward in any run DB we want to reuse as a
replay source for the new scraper:

1. ``run_metadata.scraper_name`` — the module moved out of ``sd.`` and the old
   trailing ``|`` is gone. The new name is just ``f"{module}:{ClassName}"``.

2. ``requests.deduplication_key`` — the old scraper let almost every request
   fall back to the framework default (a SHA-256 of method+URL) and left the
   speculative entry probes with a NULL key. The new scraper assigns explicit,
   human-meaningful keys. We reconstruct each request's *new* key from its
   ``continuation`` and its URL.

Why the URL, not ``accumulated_data['docket_id']``
--------------------------------------------------
A search by case number does not always redirect to a single case. When the
searched number is shared by several appeals — e.g. a trial-court number that
multiple habeas petitions reference, or an appellate case that also has related
cases — ``searchResults.cfm`` returns a multi-row table and the scraper fans
out one chain per row. Those sibling chains are *different cases* with
different real case numbers, but the old scraper left ``docket_id`` set to the
*searched* number on every sibling (it never read each row's real number back
in). Keying off ``docket_id`` would therefore collapse genuinely-distinct cases
onto one ``parse_*:{docket_id}`` key and drop all but one on replay.

The real, per-row appellate case number is the ``doc_no`` query param that
rides in every tab URL (``dockets.cfm?...&doc_no=A126046&...``). For ordinary
single-result chains ``doc_no == docket_id``; for fan-out siblings it is the
distinct truth. So we key every per-case step off ``doc_no``. This matches the
companion scraper fix in ``_fan_out_multi_result``, which now writes each row's
``doc_no`` into ``docket_number`` so a live run emits the same distinct keys.

New-key rules (must match juriscraper/state/california/.../scraper.py):

    parse_docket          -> f"parse_docket:{doc_no}"
    parse_briefs          -> f"parse_briefs:{doc_no}"
    parse_disposition     -> f"parse_disposition:{doc_no}"
    parse_parties         -> f"parse_parties:{doc_no}"
    parse_trial_court     -> f"parse_trial_court:{doc_no}"
    parse_case_summary    -> NEVER rewritten to a per-case value. Two probe
                             kinds are matched differently on replay:
                               - speculative entry probes are stored with a
                                 NULL key and matched by a URL+body fallback;
                                 the source row must STAY NULL to stay in that
                                 fallback index (a prior buggy migration that
                                 set "parse_case_summary:{docket_id}" is
                                 reverted to NULL here).
                               - multi-result fan-out children already carry
                                 "parse_case_summary:{doc_id}" on both sides —
                                 left as-is.
    archive_opinion_file  -> f"{doc_no}-{filename}", where doc_no is taken from
                             the archive's *parent* parse_case_summary request
                             (the case page the opinion was linked from), and
                             filename is the last path segment of source_url
                             without its query string. (The opinion URL itself
                             carries no doc_no.)

The migration is idempotent: re-running recomputes the same keys, sees they
already match, and does nothing.

Usage:
    uv run python migrate_california.py path/to/run.db
    uv run python migrate_california.py path/to/run.db --dry-run
    uv run python migrate_california.py path/to/run.db --scraper-name "mod:Cls"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from urllib.parse import parse_qs, urlparse

# Fallback if the scraper class can't be imported in this environment.
DEFAULT_SCRAPER_NAME = (
    "juriscraper.state.california.appellatecases_courtinfo_ca_gov"
    ".scraper:CaAppScraper"
)

# Per-case steps whose new key is f"{continuation}:{doc_no}".
PREFIXED_STEPS = frozenset(
    {
        "parse_docket",
        "parse_briefs",
        "parse_disposition",
        "parse_parties",
        "parse_trial_court",
    }
)

# Every continuation we expect to see in an old CA run DB.
KNOWN_CONTINUATIONS = PREFIXED_STEPS | {
    "parse_case_summary",
    "archive_opinion_file",
}


def resolve_scraper_name(override: str | None) -> str:
    """The name a fresh run of the new scraper would record.

    Prefer importing the class (ground truth); fall back to the constant.
    """
    if override:
        return override
    try:
        from juriscraper.state.california.appellatecases_courtinfo_ca_gov.scraper import (  # noqa: E501
            CaAppScraper,
        )

        return f"{CaAppScraper.__module__}:{CaAppScraper.__name__}"
    except Exception as exc:  # pragma: no cover - env-dependent
        print(
            f"  (could not import CaAppScraper: {exc!r}; using default name)",
            file=sys.stderr,
        )
        return DEFAULT_SCRAPER_NAME


def doc_no_from(*urls: str | None) -> str | None:
    """Return the ``doc_no`` query param from the first URL that has one."""
    for url in urls:
        if not url:
            continue
        values = parse_qs(urlparse(url).query).get("doc_no")
        if values and values[0]:
            return values[0]
    return None


def filename_from_url(url: str) -> str:
    """Last path segment of ``url`` with any query string stripped.

    Mirrors ``url.rsplit("/", 1)[-1].split("?")[0]`` in the scraper's
    ``_yield_opinion_archives``.
    """
    return url.rsplit("/", 1)[-1].split("?")[0]


def build_parent_doc_no(conn: sqlite3.Connection) -> dict[int, str]:
    """Map each parse_case_summary request id -> its real ``doc_no``.

    Used to give an opinion archive the case number of the page it was
    linked from. The speculative probe's request URL is ``searchResults.cfm``
    (no doc_no), so read the redirected ``response_url`` first.
    """
    parent: dict[int, str] = {}
    cur = conn.execute(
        "SELECT id, response_url, url FROM requests "
        "WHERE continuation = 'parse_case_summary'"
    )
    for req_id, response_url, url in cur:
        dn = doc_no_from(response_url, url)
        if dn:
            parent[req_id] = dn
    return parent


def migrate(
    db_path: str, dry_run: bool, scraper_name_override: str | None
) -> int:
    new_name = resolve_scraper_name(scraper_name_override)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        # --- Safety check: is this actually a CA run DB? -------------------
        row = conn.execute(
            "SELECT scraper_name FROM run_metadata WHERE id = 1"
        ).fetchone()
        if row is None:
            print("ERROR: no run_metadata row (id=1) found.", file=sys.stderr)
            return 2
        old_name = row[0]
        print(f"scraper_name: {old_name!r}")
        print(f"          ->  {new_name!r}")
        lname = (old_name or "").lower()
        if "california" not in lname and "caapp" not in lname:
            print(
                "ERROR: this does not look like a California run DB "
                "(scraper_name has no 'california'/'CaApp'). Refusing. Pass "
                "--scraper-name to override the target name if the source "
                "name is unusual, or re-check the database.",
                file=sys.stderr,
            )
            return 2

        # Opinion archives borrow their case number from the parent page.
        parent_doc_no = build_parent_doc_no(conn)

        # --- Scan requests and compute new keys ----------------------------
        cur = conn.execute(
            """
            SELECT id,
                   continuation,
                   deduplication_key,
                   is_speculative,
                   parent_request_id,
                   url,
                   response_url,
                   json_extract(accumulated_data_json, '$.docket_id'),
                   json_extract(accumulated_data_json, '$.source_url')
            FROM requests
            ORDER BY id
            """
        )

        unknown_continuations: Counter[str] = Counter()
        skipped_missing: Counter[str] = Counter()
        unchanged = 0
        # new_key -> winning (lowest) request id.
        winners: dict[str, int] = {}
        updates: list[tuple[str, int]] = []  # (new_key, id)
        revert_to_null: list[int] = []  # ids to reset to a NULL key
        collisions: Counter[str] = Counter()  # continuation -> losers
        collision_samples: list[str] = []
        per_continuation_changed: Counter[str] = Counter()

        for (
            req_id,
            continuation,
            old_key,
            is_speculative,
            parent_request_id,
            url,
            response_url,
            docket_id,
            source_url,
        ) in cur:
            if continuation not in KNOWN_CONTINUATIONS:
                unknown_continuations[continuation] += 1
                continue

            if continuation == "parse_case_summary":
                # parse_case_summary keys are NEVER rewritten to a per-case
                # value, because the two kinds of probe are matched on replay
                # by two different mechanisms:
                #
                #   * Speculative entry probes (the driver-seeded
                #     ``searchResults.cfm`` requests) are stored with a NULL
                #     key and matched by a URL+body fallback (SourceIndex
                #     routes NULL-key rows under ``fallback_replay_key``). The
                #     live seed also carries no usable key, so the source row
                #     MUST stay NULL to land in that fallback index. Giving it
                #     ``parse_case_summary:{docket_id}`` moves it under the
                #     dedup-key index and the seed can never find it.
                #   * Multi-result fan-out children are ordinary yielded
                #     requests keyed ``parse_case_summary:{doc_id}`` on both
                #     sides — already correct.
                #
                # So: leave fan-out rows alone, and ensure speculative rows are
                # NULL (reverting any a prior buggy migration set).
                if is_speculative and old_key:
                    revert_to_null.append(req_id)
                else:
                    unchanged += 1
                    if old_key:
                        winners.setdefault(old_key, req_id)
                continue

            if continuation in PREFIXED_STEPS:
                real = doc_no_from(url, response_url) or docket_id
                new_key = f"{continuation}:{real}" if real else None
            else:  # archive_opinion_file
                real = (
                    parent_doc_no.get(parent_request_id)
                    or doc_no_from(url, response_url)
                    or docket_id
                )
                if real and source_url:
                    new_key = f"{real}-{filename_from_url(source_url)}"
                else:
                    new_key = None

            if new_key is None:
                skipped_missing[continuation] += 1
                continue

            if new_key == old_key:
                unchanged += 1
                winners.setdefault(new_key, req_id)
                continue

            if new_key in winners:
                # doc_no is the canonical case id, so a collision is the same
                # case reached by >1 discovery path (e.g. surfaced as a
                # related-case sibling of two different searches). The new
                # scraper dedups these identically; we keep the first and
                # leave the duplicate on its old key. No distinct case is lost.
                collisions[continuation] += 1
                if len(collision_samples) < 10:
                    collision_samples.append(
                        f"id={req_id} {continuation} -> {new_key!r} "
                        f"(held by id={winners[new_key]})"
                    )
                continue

            winners[new_key] = req_id
            updates.append((new_key, req_id))
            per_continuation_changed[continuation] += 1

        # --- Report --------------------------------------------------------
        print()
        print(f"requests to re-key:        {len(updates):>8,}")
        for cont in sorted(per_continuation_changed):
            print(f"    {cont:<22} {per_continuation_changed[cont]:>8,}")
        print(f"already correct (skip):    {unchanged:>8,}")
        if revert_to_null:
            print(
                f"speculative keys -> NULL:  {len(revert_to_null):>8,}  "
                f"(restores URL-fallback replay match)"
            )
        if collisions:
            total = sum(collisions.values())
            print(f"same-case duplicates (deduped, kept first): {total:>8,}")
            for cont in sorted(collisions):
                print(f"    {cont:<22} {collisions[cont]:>8,}")
            for s in collision_samples:
                print(f"      {s}")
        if skipped_missing:
            total = sum(skipped_missing.values())
            print(f"skipped (missing field):   {total:>8,}  <-- INSPECT")
            for cont in sorted(skipped_missing):
                print(f"    {cont:<22} {skipped_missing[cont]:>8,}")
        if unknown_continuations:
            print("UNKNOWN continuations (left untouched):", file=sys.stderr)
            for cont, n in unknown_continuations.most_common():
                print(f"    {cont:<22} {n:>8,}", file=sys.stderr)

        if dry_run:
            print()
            print("--dry-run: no changes written.")
            return 0

        # --- Apply ---------------------------------------------------------
        with conn:  # single transaction; rolls back on error
            conn.execute(
                "UPDATE run_metadata SET scraper_name = ? WHERE id = 1",
                (new_name,),
            )
            conn.executemany(
                "UPDATE requests SET deduplication_key = ? WHERE id = ?",
                updates,
            )
            conn.executemany(
                "UPDATE requests SET deduplication_key = NULL WHERE id = ?",
                [(req_id,) for req_id in revert_to_null],
            )

        print()
        print(
            f"committed. rows touched (incl. metadata): {conn.total_changes:,}"
        )
        leftover = conn.execute(
            """
            SELECT count(*) FROM requests
            WHERE continuation IN
                  ('parse_docket','parse_briefs','parse_disposition',
                   'parse_parties','parse_trial_court')
              AND deduplication_key NOT LIKE continuation || ':%'
            """
        ).fetchone()[0]
        print(
            f"prefixed-step rows still on a non-conforming key: {leftover:,} "
            f"(expected {sum(collisions[c] for c in collisions if c in PREFIXED_STEPS):,} "
            f"from collisions)"
        )
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", help="path to the California run .db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    parser.add_argument(
        "--scraper-name",
        default=None,
        help="override the new scraper_name (default: import CaAppScraper)",
    )
    args = parser.parse_args()
    return migrate(args.db_path, args.dry_run, args.scraper_name)


if __name__ == "__main__":
    raise SystemExit(main())
