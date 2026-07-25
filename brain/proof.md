# Proof points

Verified proof only. Every entry carries `attribution` (the employer or context
where the work happened) and `verified: true|false`. **Anything not traceable
to a stated source is `verified: false` and may never appear in generated
output**: the drafter only ever loads `verified: true` entries into context,
and the post-check rejects drafts citing anything else.

Attribution is not optional politeness: claiming employer work as Khavion work
is both dishonest and a firewall violation. Drafts must attribute in-line
("in my time at AWS…", "on an engagement at Nordic Global…").

```yaml
proof_points:
  - id: aws_psa
    claim: "AWS Partner Solutions Architect, 2021 to 2025: partner contracts closed, revenue influenced"
    attribution: "Amazon Web Services (employment, 2021-2025)"
    verified: true
    use_for: [credibility, cloud_cost, architecture_review]
    # TODO(zohaib): if you want specific contract counts or revenue figures used
    # in drafts, state the exact numbers you are comfortable claiming publicly.
    # Until then, drafts use the qualitative form only.

  - id: cohere_bedrock
    claim: "Cohere model integration into Amazon Bedrock"
    attribution: "Amazon Web Services (performed at AWS)"
    verified: true
    use_for: [bedrock, llm_delivery, genai_readiness]

  - id: smart_karpenter
    claim: "Smart Karpenter co-creation with Avesha; 20 to 70% cloud cost reduction range"
    attribution: "Co-created with Avesha"
    verified: true
    use_for: [cloud_cost, kubernetes_autoscaling]

  - id: hipaa_voice_intake
    claim: "HIPAA-eligible AI voice intake; patient hold time reduced from 94 to 22 minutes"
    attribution: "Work performed at Nordic Global"
    verified: true
    use_for: [ai_agents, llm_delivery, genai_readiness]

  - id: adjunct_faculty
    claim: "Adjunct AI faculty, Houston City College"
    attribution: "Houston City College"
    verified: true
    use_for: [credibility, genai_readiness]

  - id: aws_workshop_author
    claim: "Official AWS workshop author"
    attribution: "Amazon Web Services"
    verified: true
    use_for: [credibility, bedrock, llmops]
```

## Not yet usable

Placeholders for future Khavion-branded engagements. Nothing goes here without
a real, completed engagement and client permission to reference it.

```yaml
unverified_pool: []
# TODO(zohaib): after the first Khavion engagements close, add entries here
# with verified: false until the client approves reference use, then flip.
```
