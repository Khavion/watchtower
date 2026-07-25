# Ideal Customer Profile

The one profile watchtower hunts for. Anything outside this scores low or
hard-fails; do not widen it to make the pipeline look busy.

## Target

- **US B2B SaaS and IT services companies**
- **20–200 employees**
- **Series A or Series B** (or equivalent recent institutional funding)
- **Running AWS and/or Kubernetes** (cloud footprint must be observable:
  job posts, tech-stack signals, engineering blog, case studies)

## Buyer titles (in priority order)

1. CTO
2. VP Engineering
3. Head of Platform
4. Head of Infrastructure
5. Director of Engineering

Seniority floor: director. Managers and ICs are not buyers; founders/CEOs count
only when the company has no technical executive.

## Why this profile

Companies at Series A/B with 20–200 people have real cloud spend and real AI
pressure but no platform team to absorb it. They buy outcomes from specialists.
Below 20 employees there is no budget; above 200 there is procurement friction
and an internal platform org.

## Hard disqualifiers (rubric `hard_fail` feeds from here)

- Under 20 employees
- No cloud footprint (no AWS/Azure/GCP/Kubernetes signal anywhere)
- Agencies reselling consulting
- Staffing firms
- On-site requirement
- W2 requirement

## Machine-readable Apollo filters

Parameter names verified against Apollo People API Search docs 2026-07-24.
`enrich.py` reads this block verbatim. Search is people-first
(`mixed_people/api_search`, 0 credits); funding stage has no search filter, so
`latest_funding_date_range` proxies recency and enrichment confirms the stage.

```yaml
apollo_filters:
  person_titles:
    - "cto"
    - "chief technology officer"
    - "vp engineering"
    - "vp of engineering"
    - "head of platform"
    - "head of infrastructure"
    - "director of engineering"
  include_similar_titles: false
  person_seniorities: ["c_suite", "vp", "head", "director"]
  person_locations: ["united states"]
  organization_locations: ["united states"]
  organization_num_employees_ranges: ["20,200"]
  # Technology UIDs validated against /v1/auth/supported_technologies_csv at
  # enrich time; enrich.py fails loudly if a UID stops resolving.
  currently_using_any_of_technology_uids: ["amazon_aws", "kubernetes"]
  # Series A/B proxy: institutional round in the last 24 months. Enrichment
  # confirms actual stage before drafting.
  latest_funding_date_range:
    min: "2024-07-01"
  q_organization_keyword_tags: ["saas", "software", "information technology & services"]
  contact_email_status: ["verified", "likely to engage"]
  per_page: 100
```

## Disqualifier keywords (matched against org descriptions and job posts)

```yaml
disqualifier_keywords:
  - "staffing"
  - "recruiting agency"
  - "talent acquisition services"
  - "consulting firm"        # they sell what Khavion sells
  - "managed service provider"
  - "reseller"
  - "on-site required"
  - "onsite required"
  - "w2 only"
  - "w-2 only"
```
