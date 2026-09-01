"""A deliberately restricted YAML-subset parser, stdlib only.

qkt-guardrails watches real money and ships with zero runtime dependencies by
design (see README) — pulling in PyYAML for a config file this small would
trade a supply-chain surface for convenience. This parser handles exactly the
shape a guardian config needs and nothing more:

  - two-level nesting via 2-space indentation (`section:` then `  key: value`)
  - scalar values only: strings, ints, floats, bools — no lists, no anchors,
    no multi-line strings, no flow style (`{...}`/`[...]`)
  - `#` starts a comment (unless inside a quoted string)
  - blank lines are ignored

Anything outside that shape raises `SimpleYamlError` with the offending line
number rather than silently misparsing — a config-loading bug in safety
software should fail loud, not guess.
"""
from __future__ import annotations

from dataclasses import dataclass


class SimpleYamlError(ValueError):
    pass


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    key: str
    raw_value: str | None


def _strip_comment(line: str) -> str:
    in_quote: str | None = None
    for i, ch in enumerate(line):
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _parse_scalar(raw: str) -> object:
    s = raw.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", "none"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _tokenize(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent % 2 != 0:
            raise SimpleYamlError(f"line {lineno}: indentation must be a multiple of 2 spaces")
        body = stripped.strip()
        if ":" not in body:
            raise SimpleYamlError(f"line {lineno}: expected 'key:' or 'key: value'")
        key, _, value = body.partition(":")
        key = key.strip()
        if not key:
            raise SimpleYamlError(f"line {lineno}: empty key")
        value = value.strip()
        lines.append(_Line(lineno, indent, key, value or None))
    return lines


def parse(text: str) -> dict[str, object]:
    """Parses a two-level `section:` / `  key: value` document into nested dicts."""
    lines = _tokenize(text)
    root: dict[str, object] = {}
    current_section: dict[str, object] | None = None
    current_indent: int | None = 0
    for line in lines:
        if line.indent == 0:
            if line.raw_value is not None:
                root[line.key] = _parse_scalar(line.raw_value)
                current_section = None
                continue
            current_section = {}
            root[line.key] = current_section
            current_indent = None
            continue
        if current_section is None:
            raise SimpleYamlError(f"line {line.number}: indented key with no open section")
        if current_indent is None:
            current_indent = line.indent
        elif line.indent != current_indent:
            raise SimpleYamlError(f"line {line.number}: inconsistent indentation")
        if line.raw_value is None:
            raise SimpleYamlError(f"line {line.number}: nesting deeper than 2 levels is not supported")
        current_section[line.key] = _parse_scalar(line.raw_value)
    return root
