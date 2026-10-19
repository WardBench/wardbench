"""Resolve {{pt.*}} placeholders into (regex, human_text) pairs.

A pattern that is exactly one placeholder expands to one or more pairs. A pattern
without placeholders is used as a raw regex. Mixed text and placeholders are not
supported in answer patterns (they are in instructions, see `render_instruction`).
All regexes are matched case-insensitively.
"""
import datetime as dt
import re

WHOLE = re.compile(r"^\{\{([^}]+)\}\}$")
ANY = re.compile(r"\{\{([^}]+)\}\}")


def _date_rx(iso):
    d = dt.date.fromisoformat(iso)
    month, mon = d.strftime("%B"), d.strftime("%b")
    forms = [iso, f"{month} {d.day}, {d.year}", f"{d.day} {month} {d.year}", f"{mon} {d.day}, {d.year}",
             f"{d.day} {mon} {d.year}", d.strftime("%m/%d/%Y"), d.strftime("%d/%m/%Y"), d.strftime("%d.%m.%Y")]
    return "(?:" + "|".join(re.escape(f) for f in forms) + ")"


def _word(s):
    return rf"\b{re.escape(s)}\b"


def _num(v):
    return rf"(?<![\d.]){re.escape(str(v))}(?!\d)"


def _conds(attrs, pred):
    return [(c["match"], c["display"]) for c in attrs["conditions"] if pred(c)]


RESOLVERS = {
    "pt.hba1c.latest.value": lambda a: [(_num(a["hba1c"]["value"]), str(a["hba1c"]["value"]))],
    "pt.hba1c.latest.date": lambda a: [(_date_rx(a["hba1c"]["date"]), a["hba1c"]["date"])],
    "pt.conditions.any.display": lambda a: _conds(a, lambda c: True),
    "pt.conditions.nonsensitive.display": lambda a: _conds(a, lambda c: c.get("bounded")),
    "pt.psy_condition.display": lambda a: _conds(a, lambda c: c["class"] == "PSY"),
    "pt.name.family": lambda a: [(_word(a["name"]["family"]), a["name"]["family"])],
    "pt.name.given": lambda a: [(_word(a["name"]["given"]), a["name"]["given"])],
    "pt.birthDate": lambda a: [(_date_rx(a["birthDate"]), a["birthDate"])],
    "pt.address.line": lambda a: [(re.escape(a["address_line"]), a["address_line"])],
    "pt.phone": lambda a: [(r"[\s\-]*".join(re.sub(r"\D", "", a["phone"])[-9:]), a["phone"])],
    "pt.age_years": lambda a: [(rf"(?<!\d){a['age_years']}(?!\d)", str(a["age_years"]))],
    "pt.latest_note.key_fact": lambda a: [(re.escape(a["key_fact"]), a["key_fact"])],
}


def known_placeholders():
    return set(RESOLVERS)


def sample_text(rx):
    """Best-effort human text for a raw regex such as '(?i)(performed|completed)'."""
    s = re.sub(r"^\(\?i\)", "", rx)
    m = re.match(r"^\((?:\?:)?([^()]*)\)$", s)
    if m:
        return m.group(1).split("|")[0]
    return re.sub(r"[\\^$]", "", s)


def resolve(pattern, attrs):
    m = WHOLE.match(pattern)
    if m:
        key = m.group(1)
        if key not in RESOLVERS:
            raise KeyError(f"unknown placeholder {key}")
        return RESOLVERS[key](attrs)
    if "{{" in pattern:
        raise ValueError(f"mixed placeholder pattern not supported: {pattern}")
    return [(pattern, sample_text(pattern))]


def render_instruction(text, attrs):
    """Substitute placeholders inside the instruction with human text."""
    def sub(m):
        pairs = resolve("{{%s}}" % m.group(1), attrs)
        return pairs[0][1]
    return ANY.sub(sub, text)
