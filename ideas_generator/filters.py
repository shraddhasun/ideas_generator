from __future__ import annotations

import re

# Block healthcare-vertical content (not exhaustive; tune with your data).
_HEALTH_PATTERNS = [
    re.compile(r"\bpatient\b", re.I),
    re.compile(r"\bclinical\b", re.I),
    re.compile(r"\bHIPAA\b"),
    re.compile(r"\bEHR\b|\bEMR\b"),
    re.compile(r"\bICD-10\b|\bCPT\b"),
    re.compile(r"\bphysician\b|\bsurgeon\b|\bnurse\b", re.I),
    re.compile(r"\bhospital\b|\bclinic\b", re.I),
    re.compile(r"\bmedical\s+records?\b", re.I),
    re.compile(r"\bhealthcare\s+provider\b", re.I),
]

# Subreddit/site hints when present in URL or metadata.
_BLOCKED_SUBSTRINGS = [
    "healthcare",
    "medical",
    "medicine",
    "physician",
    "nursing",
]


def is_healthcare_related(text: str, url: str = "") -> bool:
    hay = f"{text}\n{url}".lower()
    if any(s in hay for s in _BLOCKED_SUBSTRINGS):
        return True
    return any(p.search(text) or p.search(url) for p in _HEALTH_PATTERNS)
