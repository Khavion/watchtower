"""Shared pydantic records. Everything the pipeline passes between stages."""

from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RawSolicitation(BaseModel):
    """One solicitation as fetched from a source adapter, before any pipeline stage."""

    source_id: str
    native_id: str
    dedupe_key: str
    title: str
    url: str = ""
    agency: str | None = None
    agency_number: str | None = None
    status: str | None = None
    notice_type: str | None = None
    posted_date: date | None = None
    due_date: date | None = None
    due_time: str | None = None
    description: str = ""
    nigp_codes: list[str] = Field(default_factory=list)
    naics_codes: list[str] = Field(default_factory=list)
    # Set-aside language is stored verbatim and never interpreted (HUB/VetHUB
    # rules are mid-litigation through 2026; gonogo routes any of it to NEEDS_HUMAN).
    set_aside_text: str | None = None
    attachments: list[str] = Field(default_factory=list)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    eligibility_flag: str | None = None  # e.g. "NOT_YET_ELIGIBLE"
    suspicious_content: bool = False
    fetched_at: datetime = Field(default_factory=utcnow)
    raw: dict = Field(default_factory=dict)


class Account(BaseModel):
    """One outbound prospect account (company + best buyer contact) from Apollo."""

    domain: str
    company_name: str
    apollo_org_id: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    locations: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    funding_stage: str | None = None
    latest_funding_date: date | None = None
    latest_funding_amount: float | None = None
    triggers: dict[str, str] = Field(default_factory=dict)  # trigger_id -> observed detail
    buyer_name: str | None = None
    buyer_title: str | None = None
    buyer_seniority: str | None = None
    buyer_apollo_id: str | None = None
    buyer_email: str | None = None          # revealed only at draft time (1 credit)
    buyer_email_status: str | None = None   # from search, free
    suspicious_content: bool = False
    fetched_at: datetime = Field(default_factory=utcnow)
    last_touched: datetime | None = None
    raw: dict = Field(default_factory=dict)


class ScoreBreakdown(BaseModel):
    rubric_version: str
    total: int
    hard_fails: list[str] = Field(default_factory=list)
    criteria: dict[str, dict] = Field(default_factory=dict)  # name -> {weight, criterion_score, weighted, signals}


class Disqualifier(BaseModel):
    kind: str                 # bonding | insurance | years_in_business | past_performance | ...
    requirement_quote: str    # verbatim from the solicitation
    location: str             # where it was found (field/section + offset)


class GoNoGoVerdict(BaseModel):
    verdict: str              # GO | NO_GO | NEEDS_HUMAN
    disqualifiers: list[Disqualifier] = Field(default_factory=list)
    set_aside_text: str | None = None
    incumbent: str | None = None
    estimated_hours: float | None = None
    fits_capacity: bool | None = None
    deadline_days: int | None = None
    reasons: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=utcnow)
