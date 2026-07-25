# Voice

How Khavion sounds in writing. The drafter loads this file whole; the fenced
JSON at the bottom is the machine-checked banned list (`draft_outreach.py`
rejects and retries on any hit, then marks `DRAFT_FAILED`).

## Rules

1. **No em-dashes.** Use periods or commas. (The checker rejects the character.)
2. **Lead with the observation, not the introduction.** The first sentence is
   about them, never "I'm Zohaib" or "Khavion is".
3. **One ask per email.** A single question, answerable with one word.
4. **Short sentences.** If a sentence needs a breath, split it.
5. **No fake familiarity.** No invented mutual connections, no "love what
   you're building", no pretending to have used their product unless true.
6. **No superlatives.** "Cut hold time from 94 to 22 minutes" beats
   "incredible results". Numbers or nothing.
7. **Attribution stays attached.** Proof from employer/context work names the
   context in the same sentence (see `proof.md`).
8. **Plain words.** "Use" not "leverage". "Help" not "empower". "Talk" not
   "connect".
9. Subject lines: 2 to 5 words, lowercase except proper nouns, no clickbait,
   no "quick question".

## Banned (machine-checked)

```json
{
  "banned_phrases": [
    "i hope this finds you well",
    "hope you're doing well",
    "i wanted to reach out",
    "wanted to touch base",
    "circling back",
    "just checking in",
    "quick question",
    "picking your brain",
    "synergy",
    "leverage",
    "empower",
    "cutting-edge",
    "best-in-class",
    "world-class",
    "state-of-the-art",
    "game-changing",
    "game changer",
    "revolutionary",
    "incredible",
    "amazing opportunity",
    "huge fan",
    "love what you're building",
    "big fan of what",
    "we may have met",
    "mutual connection",
    "friend of a friend",
    "as a fellow",
    "i know you're busy",
    "don't want to take up",
    "at your earliest convenience",
    "per my last email",
    "delve",
    "furthermore",
    "moreover"
  ],
  "banned_characters": ["—"],
  "banned_patterns": [
    "(?i)\\bdear (sir|madam)\\b",
    "(?i)\\bto whom it may concern\\b",
    "(?i)\\bworld[- ]class\\b"
  ],
  "max_words": 120,
  "max_asks": 1
}
```

## Calibration examples

Bad: "Hi John, I hope this finds you well! I wanted to reach out because I'm
incredibly passionate about helping companies like yours leverage cutting-edge
AI."

Good: "John, saw Acme closed a $12M Series A last month. Post-raise AWS bills
usually jump 30 to 50% before anyone owns them. My guess: your EKS nodes are
over-provisioned for the traffic you actually serve."
