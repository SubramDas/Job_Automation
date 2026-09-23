# Source Feasibility Review

Status: initial Phase 01 review. No live adapter is enabled.

Date checked: 2026-09-23.

Updated: 2026-09-24 for Phase 05E read-only discovery candidates.

## Sources

| Source | Current Phase 01 status | Notes |
| --- | --- | --- |
| Manual import | Synthetic/manual enabled | User supplies job text and URL. This is the MVP fallback. |
| LinkedIn | Manual handoff only | LinkedIn Help says third-party software that scrapes, modifies, or automates website activity is not permitted. LinkedIn User Agreement Section 8 also contains automation and scraping restrictions. Use pasted descriptions, saved links, or a specifically permitted integration only. |
| Naukri | Unknown/manual pending review | The planning doc noted that the official terms page could not be retrieved during planning. No automation is enabled until current official terms and access permissions are verified. |
| Employer career sites / ATS postings | Candidate for future adapter | Each site needs a separate capability contract. Public postings or APIs do not by themselves authorize applicant submission. |
| Workday-backed sites | Candidate for future adapter | Workday developer/admin documentation confirms recruiting/job-posting capabilities exist, but tenant access, candidate-flow permissions, and submit APIs require site-specific verification. |
| Jobicy public API/MCP | Read-only discovery enabled | Public API does not require authentication. Preserve Jobicy attribution/canonical URL, cache reasonably, and do not poll more than hourly. |
| Remotive public API/RSS | Candidate pending final adapter | Public API exists; documentation requires linking back to Remotive and mentioning Remotive as source. Terms restrict redistributing/making listings available to third parties, so keep use personal/local unless separately approved. |
| Adzuna API | Candidate requiring account/API key | Register for `app_id` and `app_key`; search API supports job ads by country/page/query. Enable only after credentials and accepted terms are configured. |
| USAJOBS API | Candidate requiring account/API key | Requires API key, `User-Agent` email, and `Authorization-Key` header. Mostly relevant for US federal roles. |
| JobsPipe / other MCP job servers | Candidate pending review | Treat as external data providers behind our own `jobs.*` MCP wrapper. Verify terms, authentication, rate limits, and source attribution before use. |
| JobSpy MCP server | Candidate pending per-site review | Self-hosted MCP wrapping JobSpy; README claims Indeed, LinkedIn, ZipRecruiter, Glassdoor, Google, Bayt, and Naukri support. Treat as scraper-backed and disabled until each target site's permission and reliability are reviewed. |

## Official Sources Consulted

- LinkedIn Help, "Prohibited software and extensions":
  https://www.linkedin.com/help/linkedin/answer/a1341387
- LinkedIn User Agreement:
  https://oa.linkedin.com/legal/user-agreement
- OpenAI MCP guide:
  https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- Workday developer API overview:
  https://developer.workday.com/api-overview
- Jobicy remote jobs API and fair use:
  https://github.com/Jobicy/remote-jobs-api
- Remotive public API:
  https://remotive.com/remote-jobs/api
- Remotive terms:
  https://support.remotive.com/en/article/terms-of-service-u4kbkf/
- Adzuna developer overview:
  https://developer.adzuna.com/overview
- USAJOBS authentication and API reference:
  https://developer.usajobs.gov/guides/authentication
  https://developer.usajobs.gov/api-reference/
- JobSpy MCP server:
  https://github.com/borgius/jobspy-mcp-server

## Rule

Discovery permission, description retrieval permission, draft fill permission, upload
permission, submission permission, and reconciliation permission are separate capability
flags. Unsupported sources remain useful through manual import and manual handoff.
