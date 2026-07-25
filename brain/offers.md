# The offer ladder

Fixed scope, fixed price, **calendar duration only: internal hours are never
stated anywhere, including in drafts**. Each offer names its deliverable,
acceptance criteria, and the next rung up. The wedge is the cloud cost audit:
cheapest way for a buyer to experience Khavion producing money.

| Offer | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| Architecture review call | $249 | | |
| Cloud cost audit | $6,500 | $11,000 | $18,000 |
| GenAI readiness assessment | $4,500 | $7,500 | $12,000 |
| RAG / LLM pilot | $18,000 | $28,000 | $40,000 |
| Production rollout | $45,000 floor | | |
| AI operations retainer | $2,500/mo | $5,000/mo | $8,500/mo |

---

## Architecture review call: $249

- **Deliverable:** 60-minute recorded review of your cloud/AI architecture plus
  a one-page written summary: top three risks, sequenced fixes.
- **Duration:** scheduled within 1 week; summary within 2 business days after.
- **Acceptance:** you have the recording and the one-pager.
- **Next rung:** cloud cost audit (fee credited if booked within 30 days).
- Note: the *cold-outreach* version of this is free (see `sequences.md`); $249
  is the standing public price.

## Cloud cost audit: $6,500 / $11,000 / $18,000

- **Tier 1 ($6,500):** single AWS account, compute + storage focus.
  **Tier 2 ($11,000):** multi-account org or EKS-heavy estate.
  **Tier 3 ($18,000):** multi-account plus Kubernetes autoscaling redesign
  (Karpenter) implemented on one production cluster.
- **Deliverable:** line-item spend map, ranked savings plan with projected
  dollar ranges, implementation runbook; Tier 3 adds the autoscaling change
  shipped.
- **Duration:** Tier 1: 2 weeks. Tier 2: 3 weeks. Tier 3: 5 weeks.
- **Acceptance:** savings plan identifies annualized savings ≥ 2× the fee, or
  the written finding that spend is already efficient (rare, and worth knowing).
- **Next rung:** production rollout (implement the plan) or AI ops retainer
  (keep it optimized).

## GenAI readiness assessment: $4,500 / $7,500 / $12,000

- **Tier 1:** one business unit, up to 3 candidate use cases.
  **Tier 2:** company-wide, up to 8 use cases, data-readiness review.
  **Tier 3:** Tier 2 plus a clickable proof-of-concept of the top use case.
- **Deliverable:** ranked use-case portfolio with per-case run-cost estimates,
  data/security gap list, build/buy recommendation; Tier 3 adds the PoC.
- **Duration:** 2 / 3 / 5 weeks.
- **Acceptance:** an executive can pick the first AI investment from the
  document alone.
- **Next rung:** RAG / LLM pilot on the top-ranked use case.

## RAG / LLM pilot: $18,000 / $28,000 / $40,000

- **Tier 1:** one corpus, one workflow, evaluation harness, deployed to staging.
  **Tier 2:** production deployment in your VPC (Bedrock or Azure OpenAI) with
  guardrails and cost controls.
  **Tier 3:** Tier 2 plus agentic workflow (multi-step, human checkpoints) and
  handoff training for your engineers.
- **Deliverable:** the working system, evaluation report with quality numbers,
  runbook, and a go/no-go recommendation for rollout.
- **Duration:** 4 / 6 / 8 weeks.
- **Acceptance:** evaluation meets the quality bar agreed in week 1, measured
  on your data, reproducible by your team.
- **Next rung:** production rollout.

## Production rollout: from $45,000

- **Deliverable:** pilot hardened to production: SLOs, observability, cost
  ceilings, security review passed, on-call runbook, team handoff.
- **Duration:** scoped per engagement, floor 8 weeks; priced at $45,000 minimum,
  quoted after a pilot or audit (never cold).
- **Acceptance:** system running in production for 2 consecutive weeks inside
  agreed SLO and cost ceiling.
- **Next rung:** AI operations retainer.

## AI operations retainer: $2,500 / $5,000 / $8,500 per month

- **Tier 1 ($2,500):** monthly cost + quality review, model/prompt updates,
  2 advisory sessions.
  **Tier 2 ($5,000):** Tier 1 plus continuous evaluation pipeline ownership and
  quarterly optimization sprint.
  **Tier 3 ($8,500):** Tier 2 plus new-feature LLM work (one workstream at a
  time) and vendor/model selection on demand.
- **Duration:** month-to-month, 3-month initial term, cancel with 30 days
  notice.
- **Acceptance:** monthly written report delivered; spend and quality inside
  agreed bounds or flagged with a plan.
- **Next rung:** none: this is the top of the ladder; expansion is more
  workstreams.
