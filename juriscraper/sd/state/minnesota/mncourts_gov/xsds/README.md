# Minnesota Courts XSD Documentation

This directory contains XSD schemas documenting the page structure for each step function in the Minnesota appellate courts scraper.

## Files

| File | Step Function | URL |
|------|---------------|-----|
| `parse_supreme_court_opinions.xsd` | `parse_supreme_court_opinions` | https://mncourts.gov/supremecourt/recentopinions/minnesota-supreme-court-opinion |
| `parse_coa_precedential_opinions.xsd` | `parse_coa_precedential_opinions` | https://mncourts.gov/courtofappeals/recentopinions/precedential-opinions |
| `parse_coa_nonprecedential_opinions.xsd` | `parse_coa_nonprecedential_opinions` | https://mncourts.gov/courtofappeals/recentopinions/nonprecedential-opinions |

## Common Page Structure

All Minnesota courts pages share a common layout:

```
+------------------------------------------+
| Header (logo, navigation)                 |
+------------------------------------------+
| Breadcrumb (Home > Court > Section)       |
+------------------------------------------+
| Page Heading                              |
+------------------------------------------+
| Sidebar      | Main Content              |
| (sub-nav)    | - Date/Release notice     |
|              | - Opinion entries         |
|              |                           |
+------------------------------------------+
| Footer                                    |
+------------------------------------------+
```

## Key XPath Patterns

### Common across all pages

```xpath
# Main content area
//main

# All PDF links in content
//main//a[contains(@href, '.pdf')]
```

### Supreme Court

```xpath
# Release date text
# Look for: "RELEASED JANUARY 21, 2026"
//main//text()[contains(., 'RELEASED')]
```

### Court of Appeals

```xpath
# Filing date text
# Look for: "FILED TUESDAY, JANUARY 20, 2026"
//main//text()[contains(., 'FILED')]
```

## PDF URL Patterns

### Supreme Court
```
https://mncourts.gov/_media/migration/appellate/supreme-court/standard-opinions/{date}/OP{docket}-{mmddyy}.pdf
```
- Date folder format: `21jan26` (day + month abbreviation + 2-digit year)
- Filename: `OPA231738-012126.pdf` (OP + docket without hyphen + date in MMDDYY)

### Court of Appeals
```
https://mncourts.gov/_media/migration/appellate/court-of-appeals/standard-opinions/{date}/OPa{docket}-{mmddyy}.pdf
```
- Same pattern but with lowercase 'a' for Court of Appeals

## Docket Number Format

Format: `A{YY}-{NNNN}`
- `A` = Appeal
- `YY` = 2-digit year
- `NNNN` = 4-digit sequence number

Examples:
- `A25-0268` - Appeal from 2025, sequence 0268
- `A23-1738` - Appeal from 2023, sequence 1738

## Release Schedule

| Court | Day | Time |
|-------|-----|------|
| Supreme Court | Wednesday | 10:00 AM |
| Court of Appeals | Monday | 10:00 AM |

Note: Court of Appeals releases on Tuesday if Monday is a holiday.
