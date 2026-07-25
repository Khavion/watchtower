# Scope guardrails

Per-offer in/out lines, and the standard discount response: **reduce scope,
never price.** A price cut says the price was fiction; a scope cut says the
scope was real. Drafters and bid outlines must never offer a discount.

## In / out per offer

| Offer | In scope | Out of scope |
|---|---|---|
| Architecture review call | Review of existing architecture, risk ranking, fix sequence | Any implementation; written designs beyond the one-pager |
| Cloud cost audit | Spend analysis, savings plan, runbook; Tier 3: one cluster's autoscaling | Implementing the full plan; org-wide rollout; negotiation with AWS on your behalf |
| GenAI readiness assessment | Use-case ranking, run-cost estimates, gap list; Tier 3: one PoC | Building production systems; data cleanup; vendor contract negotiation |
| RAG / LLM pilot | One use case end to end, evaluation, staging/production per tier | Additional use cases; fine-tuning from scratch; GPU provisioning; 24/7 support |
| Production rollout | Hardening the piloted system to agreed SLOs | Net-new features mid-rollout; unrelated infra rescue work |
| AI ops retainer | The tiered activities listed in offers.md | Anything resembling staff augmentation; being the on-call pager for non-AI infra |

Universal out-of-scope (from `boundaries.md`): GPU provisioning, pre-training /
from-scratch fine-tuning, low-level ML infra, staff augmentation, on-site,
hourly billing, unheld-certification work.

## Worked examples: the three largest offers

### 1. RAG / LLM pilot (Tier 2, $28,000): "Can you do it for $20K?"

> "I don't discount, but I can fit $20K: we keep the production VPC deployment
> and guardrails, and cut the custom evaluation harness down to the standard
> eval set: you lose per-release regression scoring, which we can add later
> under a retainer. Same quality bar, smaller surface. Want me to re-paper it
> that way?"

Scope removed: custom evaluation harness. Price integrity intact; the ladder
(retainer) absorbs the deferred piece.

### 2. Production rollout ($45,000 floor): "Budget is $35K, can you sharpen your pencil?"

> "The floor exists because production means SLOs, security review, and
> handoff: the parts that make it safe to depend on. At $35K we'd have to drop
> one of those, and I won't ship you something you can't safely run. What I can
> do: reduce the scope to fit the rigor, a single workload in a single region,
> or hold the full scope until next quarter's budget."

Scope removed: breadth (workloads/regions), never rigor. If they push again,
the answer is the smaller engagement, not the smaller price.

### 3. Cloud cost audit (Tier 3, $18,000): "We'll sign at $12K."

> "$12K buys Tier 2: the full multi-account spend map and the savings plan,
> without the Karpenter autoscaling implementation: you'd implement from the
> runbook yourselves. If the audit finds what I expect on your EKS spend, the
> implementation typically pays for itself in a quarter; you can add it after
> as a fixed piece."

Scope removed: the implementation. The tier table *is* the negotiation: moves
happen between tiers, not between prices.

## Red lines in negotiation

- Never trade price for "future work" promises.
- Never accept payment terms beyond net-30 on offers under $45K.
- Never begin work before a signed SOW and (for audits+) first payment.
- TODO(zohaib): confirm the net-30 line and prepayment split you actually want
  on each tier.
