"""Phase 6 (P6-4): real, static scanning -- never an LLM-judge call that
could itself be fooled, and never a block/allow decision made silently.

Two genuinely different concerns, both found NOT IMPLEMENTED at all by
`audit/06-SECURITY_AND_GOVERNANCE_AUDIT.md` (Sections 4 and 10):

`scan_prompt_for_injection` looks at text this backend is about to hand an
agent as *context* (the RAG excerpts pulled from ingested documents in
`document_retrieval.py`) for the well-known phrasing that tries to get a
model to treat retrieved data as a new instruction instead. It is a
heuristic pattern match, not a guarantee -- it flags for the audit trail
and for a safety note folded into the prompt; it never silently drops or
rewrites the task's own real instruction.

`scan_output_for_secrets` looks at an agent's real completed output for
strings shaped like live credentials (so a prompt that tricked an agent
into pasting a real key back doesn't silently reach a persisted task row
and a reviewer's screen unflagged). Also heuristic: it flags, it never
redacts -- altering a completed task's real recorded output would itself
be a form of fabrication this project's standing rule rejects.
"""

import re

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ignore_instructions", re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I)),
    ("disregard_instructions", re.compile(r"disregard (all )?(previous|prior|above)", re.I)),
    ("new_instructions", re.compile(r"\bnew instructions?\s*:", re.I)),
    ("system_prompt_override", re.compile(r"(you are now|act as|pretend to be) (a |an )?(system|admin|root)", re.I)),
    ("reveal_system_prompt", re.compile(r"(reveal|print|show) (the |your )?(system prompt|instructions)", re.I)),
    ("end_of_context_claim", re.compile(r"\[?end of (document|context|data)\]?.{0,40}(now|instead) (do|run|execute)", re.I)),
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("generic_api_key_assignment", re.compile(r"(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}", re.I)),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
)


def scan_prompt_for_injection(text: str) -> list[dict]:
    """Returns one finding per distinct pattern that genuinely matched
    `text` -- `[]` when nothing matched. Never raises on arbitrary input."""
    if not text:
        return []
    findings = []
    for name, pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                {
                    "kind": "prompt_injection",
                    "pattern": name,
                    "detail": f"Matched '{name}' near: {text[max(0, match.start() - 20): match.end() + 20]!r}",
                }
            )
    return findings


def scan_output_for_secrets(text: str) -> list[dict]:
    """Returns one finding per distinct credential-shaped pattern that
    genuinely matched `text` -- `[]` when nothing matched. The matched
    value itself is never included in the finding (only its pattern name
    and a position), so the finding row can't itself leak the secret."""
    if not text:
        return []
    findings = []
    for name, pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                {
                    "kind": "output_secret",
                    "pattern": name,
                    "detail": f"Matched '{name}' at offset {match.start()} (value withheld)",
                }
            )
    return findings
