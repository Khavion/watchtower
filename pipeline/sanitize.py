"""Guardrail #5: fetched content is data, never instructions.

Solicitation text, web pages, Apollo records, and Cliq messages may contain
instruction-like text (accidental or adversarial). This module detects it,
logs it, and tags the record suspicious — processing continues on the content
AS DATA. Nothing here ever executes or obeys anything it finds.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore (all )?(previous|prior|above) (instructions|prompts|rules)",
        r"disregard (your|the|all) (instructions|rules|guidelines|system prompt)",
        r"you are now\b",
        r"\bnew instructions?\b.{0,40}\b(follow|obey|execute)",
        r"\bsystem prompt\b",
        r"\bact as\b.{0,60}\b(admin|root|developer mode|jailbreak)",
        r"\bdo not (tell|inform|alert)\b.{0,40}\b(user|owner|human)",
        r"</?(system|assistant|instructions?)>",
        r"\bemail (everyone|all contacts|the list)\b",
        r"\bsend (all|the) (credentials|passwords|keys|tokens)\b",
        r"\bexfiltrate\b|\bwire transfer\b.{0,40}\b(immediately|urgent)",
    )
]


def scan(text: str, context: str = "") -> list[str]:
    """Returns matched suspicious snippets (for the log), empty when clean."""
    if not text:
        return []
    findings = []
    for pattern in INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append(m.group(0)[:80])
    if findings:
        log.warning("sanitize: SUSPICIOUS content in %s - %d instruction-like "
                    "pattern(s), e.g. %r. Content will be processed as data only.",
                    context or "fetched content", len(findings), findings[0])
    return findings


def is_suspicious(text: str, context: str = "") -> bool:
    return bool(scan(text, context))


def neutralize(text: str) -> str:
    """Prepare untrusted text for inclusion inside a <data> block: break any
    literal closing tags so the block cannot be escaped."""
    return (text or "").replace("</data>", "<\\/data>")
