#!/usr/bin/env python3
"""Sync court data from courts-db repository.

This script fetches the latest court definitions from the freelawproject/courts-db
repository and generates the local data/courts.toml file used for coverage tracking.

Usage:
    python -m scripts.sync_courts_db

Output:
    data/courts.toml - Master court table with all known courts
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tomli_w  # noqa: E402

COURTS_DB_URL = (
    "https://raw.githubusercontent.com/freelawproject/courts-db/"
    "refs/heads/main/courts_db/data/courts.json"
)

# Mapping from courts-db jurisdiction codes to our 2-letter codes
# Courts-db uses "A.L." format, we use "AL" format
JURISDICTION_CODE_MAP: dict[str, str] = {
    "A.K.": "AK",
    "A.L.": "AL",
    "A.R.": "AR",
    "A.S.": "AS",
    "A.Z.": "AZ",
    "C.A.": "CA",
    "C.O.": "CO",
    "C.T.": "CT",
    "D.C.": "DC",
    "D.E.": "DE",
    "F.L.": "FL",
    "G.A.": "GA",
    "G.U.": "GU",
    "H.I.": "HI",
    "I.A.": "IA",
    "I.D.": "ID",
    "I.L.": "IL",
    "I.N.": "IN",
    "K.S.": "KS",
    "K.Y.": "KY",
    "L.A.": "LA",
    "M.A.": "MA",
    "M.D.": "MD",
    "M.E.": "ME",
    "M.I.": "MI",
    "M.N.": "MN",
    "M.O.": "MO",
    "M.P.": "MP",
    "M.S.": "MS",
    "M.T.": "MT",
    "N.C.": "NC",
    "N.D.": "ND",
    "N.E.": "NE",
    "N.H.": "NH",
    "N.J.": "NJ",
    "N.M.": "NM",
    "N.V.": "NV",
    "N.Y.": "NY",
    "O.H.": "OH",
    "O.K.": "OK",
    "O.R.": "OR",
    "P.A.": "PA",
    "P.R.": "PR",
    "R.I.": "RI",
    "S.C.": "SC",
    "S.D.": "SD",
    "T.N.": "TN",
    "T.X.": "TX",
    "U.T.": "UT",
    "V.A.": "VA",
    "V.I.": "VI",
    "V.T.": "VT",
    "W.A.": "WA",
    "W.I.": "WI",
    "W.V.": "WV",
    "W.Y.": "WY",
    "U.S.": "FED",
}

# Mapping from location names to 2-letter codes
LOCATION_TO_JURISDICTION: dict[str, str] = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Washington D.C.": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Guam": "GU",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Northern Mariana Islands": "MP",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Puerto Rico": "PR",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virgin Islands": "VI",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "American Samoa": "AS",
}

# Map court level codes to our level names
LEVEL_MAP: dict[str, str] = {
    "colr": "supreme",  # Court of last resort
    "iac": "appellate",  # Intermediate appellate court
    "gjc": "trial",  # General jurisdiction court
    "ljc": "trial",  # Limited jurisdiction court
    "trial": "trial",
    "gjc & iac": "appellate",  # Combined - treat as appellate
}

# Data types we track - based on what juriscraper can collect
# All courts can potentially have all data types
DATA_TYPES_BY_LEVEL: dict[str, list[str]] = {
    "supreme": ["opinions", "oral_arguments", "dockets"],
    "appellate": ["opinions", "oral_arguments", "dockets"],
    "trial": ["opinions", "oral_arguments", "dockets"],
}


def fetch_courts_db() -> list[dict]:
    """Fetch the courts database from GitHub."""
    print(f"Fetching courts from {COURTS_DB_URL}...")
    with urllib.request.urlopen(COURTS_DB_URL) as response:
        data = json.loads(response.read().decode("utf-8"))
    print(f"  Fetched {len(data)} courts")
    return data


def normalize_jurisdiction(
    jur: str | None, location: str | None = None
) -> str | None:
    """Convert courts-db jurisdiction code to our 2-letter code.

    Args:
        jur: Jurisdiction code from courts-db (e.g., "A.L.", "T.X.")
        location: Location name as fallback (e.g., "Alabama", "Texas")

    Returns:
        2-letter state/territory code (e.g., "AL", "TX") or None if unknown.
    """
    # Try jurisdiction code first
    if jur:
        result = JURISDICTION_CODE_MAP.get(jur)
        if result:
            return result

    # Fall back to location name
    if location:
        return LOCATION_TO_JURISDICTION.get(location)

    return None


def is_active_court(court: dict) -> bool:
    """Check if a court is currently active (not historical)."""
    dates = court.get("dates", [])
    if not dates:
        return True  # No date info, assume active

    # Check if any date range has no end date (still active)
    return any(date_range.get("end") is None for date_range in dates)


def get_court_level(court: dict) -> str:
    """Get normalized court level."""
    level = court.get("level", "")
    court_type = court.get("type", "")

    # First try the level field
    if level and level in LEVEL_MAP:
        return LEVEL_MAP[level]

    # Fall back to type field for courts with empty level
    if court_type == "appellate":
        return "appellate"

    return "trial"


def should_include_court(court: dict) -> bool:
    """Determine if a court should be included in our registry.

    We include all active courts. We exclude:
    - Historical courts (no longer active)
    - Colonial courts
    - International courts
    """
    system = court.get("system", "")

    # Exclude certain systems
    if system in ("colonial", "international"):
        return False

    # Must be active
    return is_active_court(court)


def get_data_types(court: dict) -> list[str]:
    """Determine what data types a court could produce."""
    level = get_court_level(court)

    # All courts can potentially have all data types
    return DATA_TYPES_BY_LEVEL.get(
        level, ["opinions", "oral_arguments", "dockets"]
    )


def get_circuit(court: dict) -> str | None:
    """Get federal circuit designation if applicable."""
    court_id = court.get("id", "")

    # Map court IDs to circuits
    if court_id == "scotus":
        return "SCOTUS"
    if court_id.startswith("ca"):
        # ca1, ca2, ..., ca11, cadc, cafc
        suffix = court_id[2:].upper()
        return f"CA{suffix}"

    # District courts belong to circuits based on their jurisdiction
    # This would require more complex mapping - skip for now
    return None


def process_courts(courts: list[dict]) -> dict:
    """Process courts into our TOML structure."""
    result: dict[str, dict] = {
        "meta": {
            "version": date.today().isoformat(),
            "description": "Master court table for juriscraper coverage tracking",
            "source": COURTS_DB_URL,
        },
        "courts": {},
        "jurisdictions": {
            "unknown": {"codes": []},
        },
    }

    unknown_jurisdictions: set[str] = set()
    included_count = 0
    excluded_count = 0

    for court in courts:
        if not should_include_court(court):
            excluded_count += 1
            continue

        court_id = court.get("id", "")
        if not court_id:
            continue

        # Get jurisdiction
        raw_jur = court.get("jurisdiction")
        location = court.get("location")
        system = court.get("system", "")

        jur: str
        if system == "federal":
            jur = "FED"
        else:
            jur_result = normalize_jurisdiction(raw_jur, location)
            if not jur_result:
                # Track unknown jurisdictions/locations
                if raw_jur:
                    unknown_jurisdictions.add(f"jur:{raw_jur}")
                elif location:
                    unknown_jurisdictions.add(f"loc:{location}")
                continue
            jur = jur_result

        # Build court entry
        court_entry = {
            "name": court.get("name", court_id),
            "jurisdiction": jur,
            "level": get_court_level(court),
            "data_types": get_data_types(court),
        }

        # Add circuit for federal courts
        circuit = get_circuit(court)
        if circuit:
            court_entry["circuit"] = circuit

        # Add court URL if available
        court_url = court.get("court_url")
        if court_url:
            court_entry["court_url"] = court_url

        result["courts"][court_id] = court_entry
        included_count += 1

    # Track unknown jurisdictions
    if unknown_jurisdictions:
        result["jurisdictions"]["unknown"]["codes"] = sorted(
            unknown_jurisdictions
        )

    print(f"  Included: {included_count} courts")
    print(f"  Excluded: {excluded_count} courts")
    if unknown_jurisdictions:
        print(f"  Unknown jurisdictions: {sorted(unknown_jurisdictions)}")

    return result


def write_courts_toml(data: dict, output_path: Path) -> None:
    """Write courts data to TOML file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with nice formatting
    with open(output_path, "wb") as f:
        tomli_w.dump(data, f)

    print(f"Wrote {output_path}")


def main() -> int:
    """Main entry point."""
    try:
        # Fetch courts database
        courts = fetch_courts_db()

        # Process into our format
        data = process_courts(courts)

        # Write output
        output_path = PROJECT_ROOT / "docs" / "data" / "courts.toml"
        write_courts_toml(data, output_path)

        # Print summary
        courts_by_jur: dict[str, int] = {}
        courts_data: dict[str, dict] = data["courts"]  # type: ignore[assignment]
        for court in courts_data.values():
            jur: str = court["jurisdiction"]
            courts_by_jur[jur] = courts_by_jur.get(jur, 0) + 1

        print("\nCourts by jurisdiction:")
        for jur, count in sorted(courts_by_jur.items()):
            print(f"  {jur}: {count}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
