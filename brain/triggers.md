# Buying triggers

Ranked signals that a company is about to spend on what Khavion sells. Weights
feed `rubric.json` (trigger criteria); "observable where" tells the pipeline
which source can actually see the signal. A prospect with zero triggers is a
cold list entry, not a lead.

| Rank | Trigger | Weight | Observable where |
|---|---|---|---|
| 1 | Funding round closed in the last 6 months | 30 | Apollo `latest_funding_date` / org enrichment (`funding_events`) |
| 2 | Open req for platform / DevOps / SRE engineer | 25 | Apollo job-posting filters (`q_organization_job_titles`), org job_postings endpoint |
| 3 | Open req for ML or AI engineer | 25 | Same job-posting signals, AI/ML title keywords |
| 4 | New CTO or VP Engineering in the last 90 days | 20 | Apollo person `employment_history` start dates on matched buyers |
| 5 | Public cloud migration or replatforming announcement | 15 | Org keywords/news fields in enrichment; engineering blog if linked |

## Interpretation rules

- Triggers stack: funding + platform req is the classic wedge moment for the
  cloud cost audit (spend just jumped, nobody owns it yet).
- Trigger **recency** matters more than existence: a 5-month-old round scores
  lower than a 5-week-old round. `score.py` decays trigger weight linearly to 0
  at the trigger's horizon (6 months for funding, 90 days for new-exec).
- A job req for "DevOps" plus AWS in the stack = they feel the pain now; the
  outreach hypothesis (sequences.md touch 1) should name that req.
- New-CTO trigger: first 90 days is when they audit everything. Offer the
  architecture review, not the audit, as the first touch.
- Migration announcements are the weakest signal (often already vendored).
  Never the sole basis for a draft.

## Machine-readable

```yaml
triggers:
  funding_recent:      {weight: 30, horizon_days: 180}
  hiring_platform:     {weight: 25, horizon_days: 60}
  hiring_ai_ml:        {weight: 25, horizon_days: 60}
  new_technical_exec:  {weight: 20, horizon_days: 90}
  cloud_migration:     {weight: 15, horizon_days: 120}

hiring_platform_title_keywords:
  ["platform engineer", "devops", "sre", "site reliability", "infrastructure engineer", "cloud engineer"]
hiring_ai_ml_title_keywords:
  ["machine learning", "ml engineer", "ai engineer", "llm", "data scientist", "genai"]
```
