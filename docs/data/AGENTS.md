# Court Site Research Agent Guide

This guide instructs agents on how to research court websites and generate site reports.

## Mission

Research court websites and produce structured reports in `docs/data/site_reports/` using the `_TEMPLATE.toml` schema.

## Task Assignment

You will receive a beads task specifying which court website to research. The task will include:
- The court URL to investigate
- The court_id(s) that use this website
- Any relevant context from `docs/data/courts.toml`

**Do not pick your own courts** - work on the task assigned to you.

## Available Tools

### Browser (Playwright MCP)
You have full browser access via Playwright. Use it to:
- Navigate to court websites
- Inspect page structure and JavaScript requirements
- Check for login walls, captchas, and paywalls
- Explore site navigation and available data types
- Check robots.txt files

### File Operations
- Read `docs/data/site_reports/_TEMPLATE.toml` for the report schema
- Write completed reports to `docs/data/site_reports/{domain_name}.toml`

### Code Search
- Search existing scrapers in `juriscraper/` to check for existing coverage
- Check GitHub issues for known problems with specific courts

## Output Naming

Reports are named by **domain name** (not court_id) to handle cases where multiple courts share a website:
```
docs/data/site_reports/{domain_name}.toml
```

Examples:
- `judicial.alabama.gov.toml`
- `ecf.ca9.uscourts.gov.toml`
- `www.courts.state.ny.us.toml`

Extract the domain from the court URL. The `[meta]` section of the report should list all `court_id` values that this domain serves.

## Research Workflow

### 1. Understand Your Assignment
Read the beads task to understand:
- Which URL you're researching
- Which court_id(s) this site serves
- Any special context or priority notes

### 2. Initial Reconnaissance
1. **Check robots.txt first** - Navigate to `{domain}/robots.txt`
   - Note any Disallow rules
   - Note any Crawl-delay directives
   - Record findings in `[robots]` section

2. **Load the main page** - Navigate to the court URL
   - Does it load without JavaScript? Try with JS disabled if possible
   - Is there a login wall or registration requirement?
   - Are there captchas?
   - What platform/vendor appears to power the site? (Look for Tyler, Thomson Reuters, etc.)

### 3. Discover Hidden APIs via Network Inspection
Many modern court websites are Single Page Applications (SPAs) that fetch data from JSON APIs. These APIs are often easier to scrape than the HTML frontend.

**Using Playwright to discover APIs:**
1. Navigate to the site and use `browser_network_requests` to see all XHR/fetch calls
2. Look for requests to API subdomains (e.g., `api.`, `publicportal-api.`)
3. Look for requests returning `application/json` content type
4. Note the URL patterns, query parameters, and pagination structure

**Common API patterns to look for:**
- `/api/v1/`, `/api/`, `/rest/` path prefixes
- Separate API subdomain (e.g., `api.courts.gov` vs `www.courts.gov`)
- Query parameters like `page=`, `size=`, `sort=`, `fields=`
- HATEOAS-style responses with `_embedded`, `_links`, `page` fields
- GraphQL endpoints (`/graphql`)

**What to document:**
- Base API URL
- Key endpoints for opinions, cases, documents
- Pagination parameters
- Any required headers or authentication
- Document download URL patterns

**Example workflow:**
```
1. browser_navigate to court portal
2. browser_network_requests to capture API calls
3. WebFetch on discovered API endpoints to examine JSON structure
4. Document endpoints in [technical] section with comments
```

### 4. Explore Available Content
For each content type in the template, try to determine:
- Is this data type available on the site?
- What URL pattern leads to this data?
- Is it behind a paywall or login?
- **Collect 1-3 example URLs** for each available content type

**Priority content types to investigate:**
1. Opinions (court decisions)
2. Oral arguments (audio/video)
3. Dockets (case listings)
4. Docket entries (filings within cases)

**How to find content:**
- Look for navigation menus: "Opinions", "Decisions", "Cases", "Dockets", "Calendar"
- Look for search functionality
- Check for RSS feeds or "Recent" sections
- Look for bulk download or data export options

**Collecting Example URLs:**
For each content type marked as "available" or "partial", provide 1-3 real example URLs in the `example_urls` field. These should be:
- Actual working URLs to real content (not placeholders)
- Representative examples showing typical URL patterns
- Different examples if the site has multiple URL formats

### 5. Check for Existing Scrapers
Search the codebase for existing coverage:
```
juriscraper/opinions/united_states/state/{state_abbrev}*.py
juriscraper/oral_args/united_states/state/{state_abbrev}*.py
```

If a scraper exists, note:
- What data types it covers
- When it was last updated (check git history)
- Any known issues (search GitHub issues)

### 6. Assess Technical Requirements
Determine what would be needed to scrape the site:
- **Simple**: Static HTML, no auth, standard pagination
- **Moderate**: Requires JavaScript, has search forms, session management
- **Complex**: Requires login, has captchas, JavaScript-heavy SPA, rate limiting

### 7. Write the Report
Fill out all sections of the template. Key guidelines:
- Use `"unknown"` for content types you couldn't verify
- Use `"unavailable"` only if you confirmed the data doesn't exist
- Use `"partial"` if only some records are available (e.g., only recent years)
- Include 1-3 real example URLs in `example_urls` for each available content type
- Be specific in notes - future agents/humans will rely on this
- In `[meta]`, list ALL court_ids served by this domain

### 8. Prioritize
Assign priority based on:
- **High**: Public access, opinions available, no major blockers, existing scraper is broken/missing
- **Medium**: Some barriers but workable, partial data available
- **Low**: Significant barriers, limited data, or good existing coverage
- **Skip**: Paywall, invitation-only, or no useful data

## Example Research Session

```
Task: Research judicial.alabama.gov
Court IDs: ala, alacivapp, alacrimapp

1. Browser: Navigate to https://judicial.alabama.gov/robots.txt
   - Record findings

2. Browser: Navigate to https://judicial.alabama.gov
   - Observe: Static HTML, no login required
   - Find: "Opinions" link in navigation
   - Find: Search functionality for cases
   - Note: Site serves multiple Alabama courts

3. Browser: Navigate to opinions portal (publicportal.alappeals.gov)
   - Use browser_network_requests to capture API calls
   - Discover: API at publicportal-api.alappeals.gov
   - Document key endpoints:
     * GET /courts?size=500 - returns court UUIDs
     * GET /courts/cms/publications?page=0&size=25 - opinion releases
     * GET /courts/{courtUUID}/cms/publication/{pubUUID} - publication details
   - Use WebFetch to examine JSON structure

4. Browser: Navigate to opinions section
   - Note URL pattern for opinion pages
   - Check date range of available opinions
   - Check document formats (PDF, HTML)

5. Search codebase for existing scrapers:
   - Found: juriscraper/opinions/united_states/state/ala.py
   - Check what it covers, last update

6. Write report to docs/data/site_reports/judicial.alabama.gov.toml
   - In [meta], list court_ids = ["ala", "alacivapp", "alacrimapp"]
   - Document discovered API endpoints in [technical] section
```

## Important Notes

### Be Respectful
- Don't hammer sites with rapid requests
- If you encounter rate limiting, note it and back off
- Don't attempt to bypass security measures

### Be Thorough but Efficient
- You don't need to catalog every page
- Focus on understanding what's available and how to access it
- Note patterns that would apply to similar content

### Handle Errors Gracefully
- If a site is down, note it and move on
- If a URL redirects, follow and note the new location
- If you hit a paywall, note it - don't try to bypass

### Federal Courts (PACER)
Federal courts often use PACER, which requires payment. Note:
- PACER sites have specific patterns (ecf.*.uscourts.gov)
- Mark `requires_payment = true`
- Note PACER case locator availability

### Shared Infrastructure
When you identify that a site uses a common platform (Tyler Odyssey, Thomson Reuters, etc.):
- Note this in `[technical].platform`
- Note other court_ids using the same system in `[technical].shared_infrastructure`
- This helps identify patterns that can be reused across scrapers

## Completing the Task

When you finish researching a site:
1. Write the report to `docs/data/site_reports/{domain_name}.toml`
2. Update your beads task with completion notes
3. Note any follow-up tasks that should be created (e.g., "scraper needs update")
