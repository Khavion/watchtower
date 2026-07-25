# Cold sequences

Three touches, 8 to 10 days apart, offering the **free cloud architecture
review** (the paid $249 version exists for inbound; cold outreach gives it
away). Under 120 words each. One ask per email. Lead with the observation,
never the introduction. `draft_outreach.py` generates **touch one only**;
touches two and three are templates Zohaib personalizes when he sends them
manually.

Rules the drafter enforces (from `voice.md`): no em-dashes, no banned phrases,
short sentences, no invented familiarity, cite only `verified: true` proof with
its attribution.

Placeholders: `{{first_name}}`, `{{company}}`, `{{trigger_detail}}` (the
observed fact, specific), `{{hypothesis}}` (one concrete guess about their
cloud spend), `{{req_title}}`, `{{exec_name}}`.

---

## Variant A: trigger: funding closed in last 6 months

**Touch 1**
> {{first_name}}, saw {{company}} closed {{trigger_detail}}. Congrats.
>
> Post-raise is usually when AWS spend jumps 30 to 50% before anyone owns it:
> new hires ship fast, autoscaling defaults stay stock, and the bill compounds
> quietly. My guess for {{company}}: {{hypothesis}}.
>
> I run cloud cost work for funded B2B teams (co-created Smart Karpenter with
> Avesha; engagements typically land 20 to 70% reduction on compute-heavy
> workloads). Happy to pressure-test that guess on a free 30-minute
> architecture review. Worth a look?

**Touch 2**
> {{first_name}}, one data point behind my note: the Smart Karpenter work I
> co-created with Avesha cut Kubernetes compute cost 20 to 70% across
> deployments, mostly from right-sizing and consolidation the defaults never
> do.
>
> If {{company}}'s EKS bill grew since the raise, the same three checks apply.
> The free review takes 30 minutes and you keep the findings either way. Want
> me to send times?

**Touch 3**
> {{first_name}}, last note from me. If cloud cost review is useful this
> quarter, reply and I'll send times; if not, reply "pass" and I won't email
> again.

---

## Variant B: trigger: open platform / DevOps / SRE req

**Touch 1**
> {{first_name}}, noticed {{company}} is hiring a {{req_title}}. That req
> usually means the platform pain arrived before the platform team.
>
> My guess: {{hypothesis}}, and the new hire will spend their first quarter
> firefighting it instead of building.
>
> I do fixed-scope cloud cost and Kubernetes autoscaling work for teams your
> size (Smart Karpenter co-creator, with Avesha). A free 30-minute architecture
> review before the hire starts often changes what you hire for. Open to it?

**Touch 2**
> {{first_name}}, quick proof point behind my last note: Smart Karpenter,
> which I co-created with Avesha, produced 20 to 70% cloud cost reductions by
> fixing exactly the autoscaling defaults most teams inherit.
>
> Your {{req_title}} posting suggests {{company}} is at that stage. The free
> review would give the new hire a day-one map. Want times?

**Touch 3**
> {{first_name}}, closing the loop. Free architecture review: reply and I'll
> send times. Not useful? Reply "pass" and this is my last email.

---

## Variant C: trigger: open ML / AI engineer req

**Touch 1**
> {{first_name}}, saw {{company}} hiring {{req_title}}. Most teams at your
> stage get the model working and then stall on the unglamorous part: VPC
> deployment, guardrails, eval, and run-cost. My guess: {{hypothesis}}.
>
> I ship LLM applications on AWS Bedrock and Azure OpenAI (at AWS I worked on
> the Cohere integration into Bedrock). A free 30-minute architecture review
> of your AI plan could save your new hire their first month. Interested?

**Touch 2**
> {{first_name}}, one concrete example behind my note: at Nordic Global I
> delivered a HIPAA-eligible AI voice intake that cut patient hold time from
> 94 minutes to 22.
>
> The hard part was not the model. It was the production wrapper, which is
> where {{company}}'s {{req_title}} will live or die. Free review offer
> stands. Send times?

**Touch 3**
> {{first_name}}, last one. If a second set of eyes on the AI buildout helps,
> reply for times. If not, "pass" ends it here.

---

## Variant D: trigger: new CTO / VP Engineering in last 90 days

**Touch 1**
> {{first_name}}, congrats on the new role at {{company}}.
>
> First 90 days usually include one uncomfortable discovery in the AWS bill.
> My guess for {{company}}: {{hypothesis}}.
>
> I do independent architecture and cost reviews for funded B2B teams
> (ex-AWS Partner Solutions Architect, 2021 to 2025). A free 30-minute review
> gives you an outside read before you commit your first-quarter plan. Useful?

**Touch 2**
> {{first_name}}, adding one proof point: in my AWS years I closed partner
> contracts and influenced revenue across exactly the stack {{company}} runs,
> and the Smart Karpenter work I co-created with Avesha cut cluster costs 20
> to 70%.
>
> New-leader audits go faster with an outside baseline. The free review offer
> stands. Want times this week?

**Touch 3**
> {{first_name}}, final note. Free architecture review while you build the
> 90-day plan: reply for times, or reply "pass" and I'm gone.

---

## Variant E: trigger: public cloud migration announcement

**Touch 1**
> {{first_name}}, read that {{company}} is {{trigger_detail}}.
>
> Migrations are where cost architecture gets set for the next three years,
> and the defaults are expensive. My guess: {{hypothesis}}.
>
> I run cloud cost and architecture reviews for B2B teams mid-migration
> (ex-AWS PSA, Smart Karpenter co-creator with Avesha). A free 30-minute
> review now is cheaper than a re-architecture later. Want a look?

**Touch 2**
> {{first_name}}, one number behind my note: autoscaling and right-sizing work
> I co-created (Smart Karpenter, with Avesha) lands 20 to 70% compute savings,
> and mid-migration is the cheapest moment to bake that in.
>
> Free 30-minute review, you keep the findings. Send times?

**Touch 3**
> {{first_name}}, last email. Review before the migration hardens: reply for
> times. Otherwise "pass" closes the thread.

---

## Cadence

- Touch 1: day 0. Touch 2: day 8 to 10. Touch 3: day 17 to 20.
- One thread, replies stay in-thread.
- A "pass" or any negative reply: mark rejected in CRM, add domain to
  suppression (min_days_between_touches applies permanently via PERSONAL
  blocklist entry if they ask never again).
