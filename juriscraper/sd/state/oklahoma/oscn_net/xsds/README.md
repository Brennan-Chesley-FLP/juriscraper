# Oklahoma OSCN Scraper XSDs

This directory contains XSD documentation for the page structures processed by the Oklahoma OSCN scraper.

## Files

### parse_opinion_index.xsd

Documents the opinion index pages at:
- `https://www.oscn.net/applications/oscn/Index.asp?ftdb={database}&year={year}&level=1`

Database codes:
- `STOKCSSC`: Oklahoma Supreme Court Cases
- `STOKCSCR`: Oklahoma Court of Criminal Appeals Cases
- `STOKCSCV`: Oklahoma Court of Civil Appeals Cases

## Page Structure Summary

### Opinion Index Page

The index page lists opinions as paragraphs containing links:

```html
<p>
  <a href="DeliverDocument.asp?CiteID=551118">
    2026 OK 1, 01/13/2026, TOBACCO SETTLEMENT ENDOWMENT TRUST FUND v. STITT, ET AL.
  </a>
</p>
```

Link text format: `{CITATION}, [{P.3d cite},] {MM/DD/YYYY}, {CASE NAME}`

Citation formats:
- Supreme Court: `YYYY OK N`
- Criminal Appeals: `YYYY OK CR N`
- Civil Appeals: `YYYY OK CIV APP N`
