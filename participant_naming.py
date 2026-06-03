"""
Human display names: explicit session.participant_names, or single letters after bot names.
"""

import string
from typing import List, Optional, Set

LETTER_NAMES: List[str] = list(string.ascii_lowercase)


def bot_reserved_names(session) -> Set[str]:
    """Bot display names (humans must not auto-reuse these in letter mode)."""
    out: Set[str] = set()
    for bot in getattr(session, "bots", None) or []:
        name = (bot.get("name") or "").strip()
        if name:
            out.add(name)
    return out


def uses_explicit_participant_names(session) -> bool:
    return bool(getattr(session, "participant_names", None))


def auto_letter_names(reserved: Set[str], count: int) -> List[str]:
    """Next `count` lowercase letters not in `reserved`."""
    names: List[str] = []
    for letter in LETTER_NAMES:
        if letter in reserved:
            continue
        names.append(letter)
        reserved = reserved | {letter}
        if len(names) >= count:
            break
    return names


def participant_name_pool(session, min_slots: int) -> List[str]:
    """
    Ordered pool for human display names.
    Explicit Admin list when set; otherwise letters after bot names (a,b → c,d,…).
    """
    explicit = [
        str(n).strip()
        for n in (getattr(session, "participant_names", None) or [])
        if str(n).strip()
    ]
    if explicit:
        return explicit
    reserved = bot_reserved_names(session)
    return auto_letter_names(set(reserved), max(1, min_slots))


def pick_human_display_name(session, taken: Set[str]) -> Optional[str]:
    """Next name for one human; None → caller should fall back to uid."""
    pool = list(getattr(session, "participant_names", None) or [])
    pool = [str(n).strip() for n in pool if str(n).strip()]
    if pool:
        for name in pool:
            if name not in taken:
                return name
        return None
    reserved = bot_reserved_names(session) | taken
    letters = auto_letter_names(reserved, 1)
    return letters[0] if letters else None
