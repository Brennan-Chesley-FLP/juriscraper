---
name: debug-scraper
description: Debug scrapers using the LocalDevDriver web API. Use when debugging a scraper run, inspecting XPath issues, viewing responses, analyzing errors, or diagnosing why a scraper isn't returning expected results.
allowed-tools: WebFetch, Read, Bash(uv run ldd-debug:*, curl:*, jq:*)
---

# Debug Scraper with LocalDevDriver

## Tools Available

- **`uv run ldd-debug`** - CLI for inspecting run databases (preferred)
- **`jq`** - JSON processor for filtering and transforming JSON output
- **Web API** - REST API at `http://127.0.0.1:8001` (requires server running)

## CLI Reference (Preferred)

The `uv run ldd-debug` CLI provides direct database access without needing the web server.

### Basic Usage

```bash
# All commands support --format table|json|jsonl
uv run ldd-debug <command> <db-path> [options]
```

### Commands

| Command | Description |
|---------|-------------|
| `uv run ldd-debug info <db>` | Show run metadata and statistics |
| `uv run ldd-debug requests list <db>` | List requests (filters: `--status`, `--continuation`) |
| `uv run ldd-debug requests show <db> <id>` | Show request details |
| `uv run ldd-debug requests summary <db>` | Request counts by status and continuation |
| `uv run ldd-debug responses list <db>` | List responses (filter: `--continuation`) |
| `uv run ldd-debug responses show <db> <id>` | Show response metadata |
| `uv run ldd-debug responses content <db> <id>` | Get decompressed response content |
| `uv run ldd-debug responses search <db>` | Search response content (see below) |
| `uv run ldd-debug results list <db>` | List results (filters: `--type`, `--valid/--invalid`) |
| `uv run ldd-debug results show <db> <id>` | Show result with data |
| `uv run ldd-debug results summary <db>` | Result counts by type and validity |
| `uv run ldd-debug errors list <db>` | List errors (filters: `--type`, `--resolved/--unresolved`) |
| `uv run ldd-debug errors show <db> <id>` | Show error details |
| `uv run ldd-debug errors summary <db>` | Error counts by type |
| `uv run ldd-debug errors resolve <db> <id>` | Mark error as resolved |
| `uv run ldd-debug errors requeue <db> <id>` | Requeue error's request |
| `uv run ldd-debug requeue request <db> <id>` | Requeue a request |
| `uv run ldd-debug requeue continuation <db> <name>` | Requeue all requests for continuation |
| `uv run ldd-debug requeue errors <db>` | Batch requeue errors |
| `uv run ldd-debug cancel request <db> <id>` | Cancel pending request |
| `uv run ldd-debug cancel continuation <db> <name>` | Cancel all pending for continuation |
| `uv run ldd-debug compression stats <db>` | Show compression statistics |
| `uv run ldd-debug diagnose <db> <error-id>` | Re-run XPath observation on error |
| `uv run ldd-debug compare <db> <continuation>` | Compare stored vs dry-run output (see below) |
| `uv run ldd-debug export jsonl <db> <output>` | Export results to JSONL |
| `uv run ldd-debug export warc <db> <output>` | Export responses to WARC |

### Response Search

Search through response content with text, regex, or XPath:

```bash
# Text search (case-insensitive)
uv run ldd-debug responses search run.db --text "error message"

# Regex search
uv run ldd-debug responses search run.db --regex "case.*\d{4}"

# XPath search (matches if any nodes found)
uv run ldd-debug responses search run.db --xpath "//div[@class='opinion']"

# With continuation filter and JSON output
uv run ldd-debug responses search run.db --text "verdict" --continuation step1 --format json
```

### Compare Command

Compare continuation output between stored results and current code (dry-run). Useful for testing scraper changes without making network requests:

```bash
# Compare specific request
uv run ldd-debug compare run.db parse_opinions --request-id 123

# Sample 10 terminal requests randomly
uv run ldd-debug compare run.db parse_docket_entries --sample 10

# Detailed output showing field-level diffs
uv run ldd-debug compare run.db parse_opinions --sample 5 --output-mode detail

# JSON output for programmatic analysis
uv run ldd-debug compare run.db parse_opinions --sample 5 --output-mode json

# Show only request tree changes (not data changes)
uv run ldd-debug compare run.db parse_opinions --show-requests

# Limit comparisons
uv run ldd-debug compare run.db parse_opinions --limit 50

# Specify scraper class explicitly (otherwise auto-discovered from run metadata)
uv run ldd-debug compare run.db parse_case_parties --sample 3 \
  --scraper-class juriscraper.sd.state.alabama.publicportal_alappeals_gov.scraper.AlabamaScraper
```

Output modes:
- `summary` (default): Aggregate statistics across all comparisons
- `detail`: Show individual changes per request
- `json`: Machine-readable JSON output

## Using jq for JSON Processing

The `jq` command is available for processing JSON output:

```bash
# Get all failed request URLs
uv run ldd-debug requests list run.db --status failed --format json | jq -r '.items[].url'

# Count errors by type
uv run ldd-debug errors list run.db --format json | jq '.items | group_by(.type) | map({type: .[0].type, count: length})'

# Extract specific fields from results
uv run ldd-debug results list run.db --format json | jq '.items[] | {id, type: .result_type, valid: .is_valid}'

# Filter responses by status code
uv run ldd-debug responses list run.db --format json | jq '.items | map(select(.status_code != 200))'
```

## Common Debug Workflows

### 1. Diagnose Zero Results

```bash
# Check run stats first
uv run ldd-debug info run.db

# List responses to find one to diagnose
uv run ldd-debug responses list run.db --format json | jq '.items[0].id'

# View the response content
uv run ldd-debug responses content run.db <response_id>

# Search for expected content
uv run ldd-debug responses search run.db --xpath "//table[@class='results']"

# Diagnose an error
uv run ldd-debug diagnose run.db <error_id>
```

### 2. Inspect Failed Requests

```bash
# List failed requests
uv run ldd-debug requests list run.db --status failed

# Get error summary
uv run ldd-debug errors summary run.db

# View specific error details
uv run ldd-debug errors show run.db <error_id>

# Requeue a failed request
uv run ldd-debug requeue request run.db <request_id>
```

### 3. Check Request Progress

```bash
# Get summary of request status by continuation
uv run ldd-debug requests summary run.db

# List pending requests
uv run ldd-debug requests list run.db --status pending
```

### 4. Export Results

```bash
# Export all valid results as JSONL
uv run ldd-debug export jsonl run.db results.jsonl --valid

# Export specific result type
uv run ldd-debug export jsonl run.db opinions.jsonl --type CourtOpinion
```

### 5. Test Scraper Changes (Compare)

Verify scraper code changes work correctly without making network requests:

```bash
# After modifying scraper code, compare against stored run
uv run ldd-debug compare run.db parse_opinions --sample 20 --output-mode detail

# Check summary to see overall impact
uv run ldd-debug compare run.db parse_opinions --limit 100

# Focus on specific problematic request
uv run ldd-debug compare run.db parse_opinions --request-id 12345 --output-mode detail
```

---

## Web API Reference (Alternative)

The LocalDevDriver also provides a REST API at `http://127.0.0.1:8001` when the server is running.

### Starting the Server

```bash
cd juriscraper/scraper_driver/driver/dev_driver
uvicorn web.app:app --reload --port 8001
```

### API Endpoints

#### Run Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs` | GET | List all runs |
| `/api/runs` | POST | Create new run |
| `/api/runs/{run_id}` | GET | Get run details |
| `/api/runs/{run_id}/load` | POST | Load existing run |
| `/api/runs/{run_id}/start` | POST | Start/resume run |
| `/api/runs/{run_id}/stop` | POST | Stop running run |
| `/api/runs/{run_id}/unload` | POST | Unload run |
| `/api/runs/{run_id}` | DELETE | Delete run |
| `/api/runs/scan` | POST | Rescan for runs |

#### Requests

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/requests` | GET | List requests (filters: `status`, `continuation`) |
| `/api/runs/{run_id}/requests/summary` | GET | Request counts by continuation |
| `/api/runs/{run_id}/requests/{id}` | GET | Get request details |
| `/api/runs/{run_id}/requests/{id}/cancel` | POST | Cancel pending request |
| `/api/runs/{run_id}/requests/{id}/requeue` | POST | Requeue failed request |

#### Responses

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/responses` | GET | List responses (filters: `continuation`, `request_id`) |
| `/api/runs/{run_id}/responses/{id}` | GET | Get response metadata |
| `/api/runs/{run_id}/responses/{id}/content` | GET | Get decompressed content |

#### Results

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/results` | GET | List results (filters: `result_type`, `is_valid`, `request_id`) |
| `/api/runs/{run_id}/results/summary` | GET | Valid/invalid counts by type |
| `/api/runs/{run_id}/results/{id}` | GET | Get result with data |
| `/api/runs/{run_id}/results/export.jsonl` | GET | Export as JSONL |

#### Errors

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/errors` | GET | List errors (filters: `error_type`, `unresolved_only`) |
| `/api/runs/{run_id}/errors/summary` | GET | Error counts by type |
| `/api/runs/{run_id}/errors/{id}` | GET | Get error details |
| `/api/runs/{run_id}/errors/{id}/resolve` | POST | Mark resolved |
| `/api/runs/{run_id}/errors/{id}/requeue` | POST | Requeue error's request |

#### Debug

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/debug/diagnose/{response_id}` | GET | Re-run continuation with XPath observation |

#### Scrapers

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scrapers` | GET | List available scrapers |
| `/api/scrapers/{path}` | GET | Get scraper schema |
| `/api/scrapers/rescan` | POST | Rescan for scrapers |

### Creating a Run via API

```bash
curl -X POST "http://127.0.0.1:8001/api/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "my-test-run",
    "scraper_path": "juriscraper.sd.state.connecticut.jud_ct_gov.scraper:CTGovScraper",
    "params": {
      "models": {
        "CTDocket": {
          "enabled": true,
          "fields": {
            "crn": {"value": "AC-123456"}
          }
        }
      }
    },
    "base_delay": 10.0,
    "jitter": 2.0
  }'
```

## Error Types

| Type | Description |
|------|-------------|
| `structural` | HTML structure doesn't match XPath expectations |
| `validation` | Data doesn't match Pydantic model |
| `transient` | HTTP errors (5xx, timeout) that might succeed on retry |