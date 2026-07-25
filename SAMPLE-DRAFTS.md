# Sample drafts — judge the local model here

Five real touch-one drafts from five real Apollo accounts, generated
2026-07-24 by `llama3.1:8b@46e0c10c039e` through the full pipeline
(enrich → score → draft with voice + fabrication checks). Total Apollo spend
for the batch: 8 credits (8 accounts matched; drafting itself is free).
Nothing was sent, no Zoho writes happened, and buyer emails are deliberately
omitted from this file (they live in the local `data/accounts/` records).

**The decision this file exists for:** is this quality good enough to be
worth your editing time before you hit send? If not, switching to a hosted
model is one line in `config/providers.yaml` (after implementing
`providers/hosted.py`, which is intentionally unwired).

---

## 1. Circuit — circuit.ai (score 69)

- Buyer: VP Engineering (Patrick O'Keeffe) · 42 employees · Angel stage
- Trigger: funding_recent (Angel closed 2026-02-01) · variant A · 1 attempt

> **Subject:** circuit.ai's post-funding cloud costs
>
> Patrick, saw Circuit close Angel funding on 2026-02-01. Congrats.
>
> Post-fund is usually when SES spend jumps 30 to 50% before anyone owns it:
> new hires ship fast, autoscaling defaults stay stock, and the bill compounds quietly.
> My guess for Circuit: SES usage will grow 40% in the next quarter due to increased email volume from new customers.
>
> I run cloud cost work for funded B2B teams (co-created Smart Karpenter with Avesha; engagements typically land 20 to 70% reduction on compute-heavy workloads).
> Happy to pressure-test that guess on a free 30-minute architecture review. Worth a look?

## 2. Vita Inclinata — vitatech.co (score 66)

- Buyer: CTO & EVP of Engineering (Derek Sikora) · 45 employees · Debt financing
- Trigger: funding_recent (closed 2026-05-01) · variant A · 1 attempt

> **Subject:** aws spend after debt financing
>
> Derek, saw Vita Inclinata close debt financing 2026-05-01. Congrats.
>
> Post-funding is usually when AWS spend jumps 30 to 50% before anyone owns it:
> new hires ship fast, autoscaling defaults stay stock, and the bill compounds quietly.
> My guess for Vita Inclinata: you're now paying $150k per month on EKS and EC2.
>
> I run cloud cost work for funded B2B teams (co-created Smart Karpenter with Avesha; engagements typically land 20 to 70% reduction on compute-heavy workloads).
> Happy to pressure-test that guess on a free 30-minute architecture review. Worth a look?

## 3. Blockstream — blockstream.com (score 64)

- Buyer: CTO & EVP of Engineering (Naji Bekhazi) · 130 employees · Convertible note
- Trigger: none observed → stack-grounded opener enforced · 1 attempt

> **Subject:** aws costs at 130 headcount
>
> I see you're running AWS CloudFormation and Amazon CloudWatch, which can add up quickly at your scale. My guess is you're spending around $250,000 to $500,000 per year on these services alone.
>
> Would you be open to a free 30-minute cloud architecture review to discuss optimization opportunities?

## 4. Zengines — zengines.ai (score 64)

- Buyer: VP Engineering (Vasudha Raju) · 20 employees · Seed
- Trigger: none observed → stack-grounded opener enforced · 1 attempt

> **Subject:** aws trusted advisor review
>
> My guess is that your AWS Trusted Advisor setup could be optimized, given your company's size and technology stack including Kubernetes and Docker. A 30-minute cloud architecture review might help identify areas to reduce costs and improve efficiency.
>
> Let me know if you'd like to schedule a call.

## 5. RelationalAI — relational.ai (score 60)

- Buyer: CTO, SVP of Engineering (Hakan Hacigumus) · 170 employees · Venture
- Trigger: none observed → stack-grounded opener enforced · 1 attempt

> **Subject:** aws costs at 170 employees
>
> I've worked with similar AWS stacks at this scale and my guess is that you're spending around $250k to $500k per month on cloud infrastructure alone.
>
> Would a free 30-minute review of your cloud architecture help identify areas for cost optimization?

---

## Honest quality read (so you don't have to reverse-engineer it)

What the guardrails caught and fixed during this batch:

- The FIRST generation invented observations on the three trigger-less
  accounts ("noticed Blockstream is hiring a Cloud Engineer" — no such req in
  our data). A deterministic fabrication check now rejects any reference to
  hiring/funding/exec-change/migration events that were not actually
  observed, and trigger-less accounts get a stack-grounded instruction
  instead of an event template. The drafts above are post-fix.

What the checks cannot fix (the model's actual ceiling, your call):

- **Made-up-sounding numbers inside "my guess" framing.** "$150k per month on
  EKS", "$250k to $500k per month". Technically guesses, but they read like
  claimed telemetry; a sharp CTO may find them off-putting rather than
  intriguing. The trigger-backed drafts (1, 2) survive this better than the
  cold ones.
- **Trigger-less drafts are generic.** Drafts 3-5 lost the name-first opener
  and read like decent-but-forgettable cold email. The system is honest now;
  it is not clever.
- **Occasional context bleed:** draft 4 mentions "Kubernetes and Docker",
  which are in Khavion's pitch context, not in Zengines' observed stack.
- Drafts 1-2 follow the sequence template closely and are genuinely usable
  with 1-2 minutes of your editing.

Suggested read: trigger-backed drafts ~7/10 usable, cold stack-based drafts
~4/10. If that editing burden is acceptable, keep the local model. If not,
`providers.yaml` is the one-line lever.
