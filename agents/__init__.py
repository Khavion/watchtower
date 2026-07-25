"""The agents.

All of them share ONE resident model and take turns using it, one at a time,
enforced by the dispatcher's lock. None of them acts: each produces something
Zohaib approves. Nothing in this package sends email, posts to LinkedIn, or
submits a bid, and nothing here is permitted to grow that ability.

Each agent is a module exposing `run(log) -> str`, where the returned string is
a short plain-English summary stored in the run history and, where it makes
sense, posted to Cliq. Plain English is a hard requirement, not a preference: a
non-technical VA reads these, so no JSON, no tracebacks, no jargon.
"""
