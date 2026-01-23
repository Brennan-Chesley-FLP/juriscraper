# Florida Courts Scraper - API Documentation

This directory documents the JSON API structure used by the Florida appellate courts scraper.

## API Endpoint

**URL**: `https://flcourts-media.flcourts.gov/_search/opinions`

**Method**: GET

## Request Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `siteaccess` | string | Court identifier (supreme2, 1dca, 2dca, etc.) |
| `searchtype` | string | Always "opinions" |
| `query` | string | Search text (empty for all opinions) |
| `offset` | integer | Pagination offset (0-based) |
| `limit` | integer | Results per page (default 10, scraper uses 50) |
| `sort` | string | Sort order |
| `startDate` | date | Filter: opinions on or after this date (YYYY-MM-DD) |
| `endDate` | date | Filter: opinions on or before this date (YYYY-MM-DD) |
| `types[]` | array | Opinion types: "Written", "PCA", "Citation" |

### Siteaccess Values

| Court | Siteaccess Value |
|-------|------------------|
| Florida Supreme Court | `supreme2` |
| 1st District Court of Appeal | `1dca` |
| 2nd District Court of Appeal | `2dca` |
| 3rd District Court of Appeal | `3dca` |
| 4th District Court of Appeal | `4dca` |
| 5th District Court of Appeal | `5dca` |
| 6th District Court of Appeal | `6dca` |

## Response Structure

See `parse_opinions_api.xsd` for the JSON schema.
