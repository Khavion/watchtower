# Proof points

Verified proof only. Every entry carries `verified: true|false`. **Anything not
traceable to a stated source is `verified: false` and may never appear in
generated output**: the drafter only ever loads `verified: true` entries into
context, and the post-check rejects drafts citing anything else.

## The rule that shapes this whole file (owner directive, 2026-07-25)

**No employer names. The work is the proof, not the logo.**

Zohaib was explicit: he does not want to lean on "I worked at X" for
credibility, and he has no clearance to publish customer names or performance
metrics from any employer. Both constraints point the same way, so this file
follows one rule:

> Claims describe **what Zohaib can personally do and has personally built**.
> They never name an employer, never name a client, and never quote a metric
> produced inside someone else's business.

This is a real tightening, and it costs something. A recognizable employer name
does credibility work in a cold email that a capability claim has to earn
through specificity instead. The honest trade is that everything here is
genuinely his and nothing can be disputed by a former employer.

Two things that ARE allowed, because Zohaib approved them explicitly:

- **The teaching role**, named. It is his own current side role, not borrowed.
- **Generic industry labels** — "a healthcare provider", "a large cloud
  vendor" — for context, with no company identified.

Note the distinction the drafter must preserve: these are claims about
**Zohaib's personal hands-on experience**, which travels with him. They are not
claims about *Khavion's* client portfolio, which is currently empty and must
never be implied to be otherwise.

Technology and product names (Kubernetes, Karpenter, Bedrock, Azure OpenAI) are
fine. They describe what he knows, not who paid for it.

```yaml
proof_points:
  - id: solutions_architect_years
    claim: "Four years as a partner-facing solutions architect at a large cloud vendor, 2021 to 2025"
    attribution: "generic industry label only; employer deliberately unnamed"
    verified: true
    use_for: [credibility, cloud_cost, architecture_review]

  - id: foundation_model_integration
    claim: "Hands-on delivery experience integrating commercial foundation models into Amazon Bedrock"
    attribution: "personal hands-on experience; technology named, employer not"
    verified: true
    use_for: [bedrock, llm_delivery, genai_readiness]

  - id: kubernetes_autoscaling
    claim: "Kubernetes autoscaling redesign with Karpenter, including co-development of a commercial autoscaling product"
    attribution: "personal hands-on experience; partner deliberately unnamed"
    verified: true
    use_for: [cloud_cost, kubernetes_autoscaling]

  - id: healthcare_voice_intake
    claim: "Built a HIPAA-eligible AI voice intake system for a healthcare provider, cutting patient wait times substantially"
    attribution: "generic industry label only; client unnamed, no metric quoted"
    verified: true
    use_for: [ai_agents, llm_delivery, genai_readiness]

  - id: adjunct_faculty
    claim: "Adjunct AI faculty, Houston City College"
    attribution: "Houston City College (own side role, naming approved 2026-07-25)"
    verified: true
    use_for: [credibility, genai_readiness]

  - id: workshop_author
    claim: "Author of published cloud training workshops used by practising engineers"
    attribution: "personal authorship; publisher deliberately unnamed"
    verified: true
    use_for: [credibility, bedrock, llmops]
```

## Industry-typical figures (NOT personal results)

These are stated ranges about the field, not claims about work Zohaib did. The
drafter may use them only with explicit hedging ("typically", "usually lands"),
never as "I achieved".

```yaml
industry_ranges:
  - id: autoscaling_savings_range
    statement: "Autoscaling redesign typically lands a 20 to 70% reduction on compute-heavy workloads"
    kind: industry_typical
    verified: true
```

## What was removed on 2026-07-25, and why

- The employer names (a large cloud vendor, a healthcare consultancy) — owner
  directive above.
- The specific patient hold-time figure (94 to 22 minutes). It is a real result
  but it was produced inside a client's business under an employer's contract,
  and Zohaib has no explicit permission to publish it. Replaced with the
  unquantified form.
- The 20 to 70% cost reduction as a *personal* claim. It survives above as a
  stated industry-typical range, which is what it can honestly be without
  naming the partnership it came from.

## Not yet usable

Placeholders for future Khavion-branded engagements. Nothing goes here without
a real, completed engagement and client permission to reference it.

```yaml
unverified_pool: []
```

If Zohaib later gets written clearance for a specific metric or a partner name,
it moves back into `proof_points` with the clearance noted in `attribution`.
