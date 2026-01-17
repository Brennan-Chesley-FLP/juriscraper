---
name: debug-scraper
description: Debug scrapers using the LocalDevDriver web API. Use when debugging a scraper run, inspecting XPath issues, viewing responses, analyzing errors, or diagnosing why a scraper isn't returning expected results.
allowed-tools: WebFetch, Read, Bash(curl:*)
---

# Debug Scraper with LocalDevDriver

The LocalDevDriver provides a REST API for debugging scrapers at `http://127.0.0.1:8001`.

## API Reference

### Run Management

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

### Requests

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/requests` | GET | List requests (filters: `status`, `continuation`) |
| `/api/runs/{run_id}/requests/summary` | GET | Request counts by continuation |
| `/api/runs/{run_id}/requests/{id}` | GET | Get request details |
| `/api/runs/{run_id}/requests/{id}/cancel` | POST | Cancel pending request |
| `/api/runs/{run_id}/requests/{id}/requeue` | POST | Requeue failed request |

### Responses

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/responses` | GET | List responses (filters: `continuation`, `request_id`) |
| `/api/runs/{run_id}/responses/{id}` | GET | Get response metadata |
| `/api/runs/{run_id}/responses/{id}/content` | GET | Get decompressed content |

### Results

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/results` | GET | List results (filters: `result_type`, `is_valid`, `request_id`) |
| `/api/runs/{run_id}/results/summary` | GET | Valid/invalid counts by type |
| `/api/runs/{run_id}/results/{id}` | GET | Get result with data |
| `/api/runs/{run_id}/results/export.jsonl` | GET | Export as JSONL |

### Errors

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/errors` | GET | List errors (filters: `error_type`, `unresolved_only`) |
| `/api/runs/{run_id}/errors/summary` | GET | Error counts by type |
| `/api/runs/{run_id}/errors/{id}` | GET | Get error details |
| `/api/runs/{run_id}/errors/{id}/resolve` | POST | Mark resolved |
| `/api/runs/{run_id}/errors/{id}/requeue` | POST | Requeue error's request |

### Debug

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runs/{run_id}/debug/diagnose/{response_id}` | GET | Re-run continuation with XPath observation |

### Scrapers

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scrapers` | GET | List available scrapers |
| `/api/scrapers/{path}` | GET | Get scraper schema |
| `/api/scrapers/rescan` | POST | Rescan for scrapers |

## Common Debug Workflows

### 1. Diagnose Zero Results

When a scraper returns no results:

```bash
# Get the response ID from the responses list
curl "http://127.0.0.1:8001/api/runs/{run_id}/responses"

# Run diagnosis on a specific response
curl "http://127.0.0.1:8001/api/runs/{run_id}/debug/diagnose/{response_id}"
```

The diagnose endpoint returns:
- `yields`: What the continuation yielded
- `simple_tree`: Simplified HTML tree
- `observer_json`: XPath queries made and their match counts

### 2. Inspect Failed Requests

```bash
# List failed requests
curl "http://127.0.0.1:8001/api/runs/{run_id}/requests?status=failed"

# Get error details
curl "http://127.0.0.1:8001/api/runs/{run_id}/errors?unresolved_only=true"

# Requeue a failed request
curl -X POST "http://127.0.0.1:8001/api/runs/{run_id}/errors/{error_id}/requeue"
```

### 3. View Response Content

```bash
# Get response content (decompressed HTML)
curl "http://127.0.0.1:8001/api/runs/{run_id}/responses/{response_id}/content"
```

### 4. Check Request Progress

```bash
# Get summary of request status by continuation
curl "http://127.0.0.1:8001/api/runs/{run_id}/requests/summary"
```

### 5. Export Results

```bash
# Export all valid results as JSONL
curl "http://127.0.0.1:8001/api/runs/{run_id}/results/export.jsonl?is_valid=true"
```

## Error Types

| Type | Description |
|------|-------------|
| `structural` | HTML structure doesn't match XPath expectations |
| `validation` | Data doesn't match Pydantic model |
| `transient` | HTTP errors (5xx, timeout) that might succeed on retry |

## Creating a Run

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

## Starting the Server

```bash
cd juriscraper/scraper_driver/driver/dev_driver
uvicorn web.app:app --reload --port 8001
```
