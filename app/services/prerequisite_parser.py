"""Parse and evaluate UOW handbook prerequisite / corequisite expressions."""

from __future__ import annotations

import re
from dataclasses import dataclass


SUBJECT_CODE_RE = re.compile(r"\b([A-Z]{3,5}\s?\d{2,3})\b", re.IGNORECASE)
CP_LEVEL_RE = re.compile(
    r"(?:(\d+)\s*(?:cp|credit points?)|another\s+(\d+)\s*cp).*?(100|200|300)\s*-?\s*level|"
    r"(100|200|300)\s*-?\s*level.*?(?:(\d+)\s*(?:cp|credit points?))",
    re.IGNORECASE,
)


def _parse_prefixes(term: str) -> frozenset[str] | None:
    if re.search(r"CSCI/CSIT/ISIT", term, re.I):
        return frozenset({"CSCI", "CSIT", "ISIT"})
    if re.search(r"CSCI/CSIT", term, re.I):
        return frozenset({"CSCI", "CSIT"})
    if re.search(r"CSCI/ISIT", term, re.I):
        return frozenset({"CSCI", "ISIT"})
    found = {match.group(0).upper() for match in re.finditer(r"\b(CSCI|CSIT|ISIT)\b", term, re.I)}
    return frozenset(found) if found else None


def normalize_code(code: str) -> str:
    return code.upper().replace(" ", "")


def expand_held(
    codes: set[str],
    satisfies: dict[str, frozenset[str]] | None = None,
) -> set[str]:
    """Include equivalency alternates when evaluating satisfaction."""
    if satisfies is None:
        from app.services.course_rules import load_course_rules

        satisfies = load_course_rules("766", "Wollongong").satisfies

    expanded = {normalize_code(c) for c in codes}
    changed = True
    while changed:
        changed = False
        for base, alts in satisfies.items():
            base_n = normalize_code(base)
            if base_n in expanded:
                for alt in alts:
                    alt_n = normalize_code(alt)
                    if alt_n not in expanded:
                        expanded.add(alt_n)
                        changed = True
            for alt in alts:
                if normalize_code(alt) in expanded and base_n not in expanded:
                    expanded.add(base_n)
                    changed = True
    return expanded


def subject_level_from_code(code: str) -> int | None:
    match = re.search(r"\d", normalize_code(code))
    if not match:
        return None
    return int(match.group()) * 100


def split_top_level(expr: str, sep: str) -> list[str]:
    """Split *expr* on *sep* only outside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    sep_lower = sep.lower()
    expr_lower = expr.lower()
    i = 0
    while i < len(expr):
        char = expr[i]
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif depth == 0 and expr_lower[i : i + len(sep_lower)] == sep_lower:
            chunk = "".join(current).strip()
            if chunk:
                parts.append(chunk)
            current = []
            i += len(sep_lower) - 1
        else:
            current.append(char)
        i += 1
    chunk = "".join(current).strip()
    if chunk:
        parts.append(chunk)
    return parts


@dataclass(frozen=True)
class CpLevelRequirement:
    min_cp: int
    level: int
    prefixes: frozenset[str] | None


def _parse_cp_level(term: str) -> CpLevelRequirement | None:
    match = CP_LEVEL_RE.search(term)
    if not match:
        return None
    groups = match.groups()
    min_cp = next((int(g) for g in groups if g and str(g).isdigit() and int(g) >= 6), 0)
    level = next((int(g) for g in groups if g in {"100", "200", "300"}), None)
    if level is None:
        return None
    if min_cp == 0:
        min_cp = 6
    prefixes = _parse_prefixes(term)
    return CpLevelRequirement(min_cp=min_cp, level=level, prefixes=prefixes)


def _cp_at_level_satisfied(
    req: CpLevelRequirement,
    held_codes: set[str],
    cp_by_code: dict[str, int],
    level_by_code: dict[str, int | None],
) -> bool:
    total = 0
    for code in held_codes:
        norm = normalize_code(code)
        level = level_by_code.get(norm) or subject_level_from_code(norm)
        if level != req.level:
            continue
        if req.prefixes and not any(norm.startswith(p) for p in req.prefixes):
            continue
        total += cp_by_code.get(norm, 6)
    return total >= req.min_cp


def _subject_code_satisfied(
    code: str,
    held: set[str],
    satisfies: dict[str, frozenset[str]] | None = None,
) -> bool:
    norm = normalize_code(code)
    expanded = expand_held(held, satisfies)
    return norm in expanded


def _evaluate_term(
    term: str,
    held: set[str],
    cp_by_code: dict[str, int],
    level_by_code: dict[str, int | None],
    satisfies: dict[str, frozenset[str]] | None = None,
) -> bool:
    cleaned = term.strip().strip("()").strip()
    if not cleaned:
        return True

    if cleaned.startswith("(") and cleaned.endswith(")"):
        return _evaluate_term(cleaned[1:-1], held, cp_by_code, level_by_code, satisfies)

    or_parts = split_top_level(cleaned, " or ")
    if len(or_parts) > 1:
        return any(
            _evaluate_term(part, held, cp_by_code, level_by_code, satisfies) for part in or_parts
        )

    cp_req = _parse_cp_level(cleaned)
    codes = SUBJECT_CODE_RE.findall(cleaned)
    has_only_cp = cp_req is not None and not codes

    if has_only_cp:
        return _cp_at_level_satisfied(cp_req, held, cp_by_code, level_by_code)

    if cp_req and codes:
        code_ok = all(_subject_code_satisfied(c, held, satisfies) for c in codes)
        return code_ok and _cp_at_level_satisfied(cp_req, held, cp_by_code, level_by_code)

    if codes and len(codes) == 1 and not cp_req:
        return _subject_code_satisfied(codes[0], held, satisfies)

    if "+" in cleaned or re.search(r"\bplus\b", cleaned, re.I):
        subparts = re.split(r"\s*\+\s*|\s+plus\s+", cleaned, flags=re.I)
        return all(
            _evaluate_term(part, held, cp_by_code, level_by_code, satisfies)
            for part in subparts
            if part.strip()
        )

    comma_parts = split_top_level(cleaned.replace(",", " and "), " and ")
    if len(comma_parts) > 1:
        return all(
            _evaluate_term(part, held, cp_by_code, level_by_code, satisfies)
            for part in comma_parts
        )

    if cp_req:
        return _cp_at_level_satisfied(cp_req, held, cp_by_code, level_by_code)

    if codes:
        return all(_subject_code_satisfied(c, held, satisfies) for c in codes)

    return True


def evaluate_expression(
    expression: str,
    held: set[str],
    cp_by_code: dict[str, int],
    level_by_code: dict[str, int | None],
    satisfies: dict[str, frozenset[str]] | None = None,
) -> bool:
    """Return True when *expression* is satisfied by *held* subject codes."""
    expr = (expression or "").strip()
    if not expr or expr.lower() == "none":
        return True

    or_parts = split_top_level(expr, " or ")
    if len(or_parts) > 1:
        return any(
            evaluate_expression(part, held, cp_by_code, level_by_code, satisfies)
            for part in or_parts
        )

    and_parts = split_top_level(expr, " and ")
    if len(and_parts) > 1:
        return all(
            _evaluate_term(part, held, cp_by_code, level_by_code, satisfies)
            for part in and_parts
        )

    return _evaluate_term(expr, held, cp_by_code, level_by_code, satisfies)


def expressions_satisfied(
    expressions: list[str],
    held: set[str],
    cp_by_code: dict[str, int],
    level_by_code: dict[str, int | None],
    satisfies: dict[str, frozenset[str]] | None = None,
) -> bool:
    if not expressions:
        return True
    return all(
        evaluate_expression(expr, held, cp_by_code, level_by_code, satisfies)
        for expr in expressions
    )
