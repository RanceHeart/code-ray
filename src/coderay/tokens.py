from __future__ import annotations

from typing import Optional


def estimate_tokens_from_chars(chars: int) -> int:
    if chars <= 0:
        return 0
    return (chars + 3) // 4


def chars_from_token_budget(tokens: Optional[int]) -> Optional[int]:
    if tokens is None:
        return None
    if tokens <= 0:
        return 0
    return tokens * 4
