"""Parse Afra XML without inventing observations from destination variables."""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .lts import LTS, TAU

SELECTOR_RE = re.compile(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\Z", re.I)
MESSAGE_RE = re.compile(r"\s*([a-z_][a-z0-9_]*)\s*(?:\((.*)\))?\s*\Z", re.I | re.S)
ARGUMENT_SPACE_RE = re.compile(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|\s+''')


def read_observables(path: str | Path) -> frozenset[str]:
    text = Path(path).read_text(encoding="utf-8-sig")
    entries = [s.strip().lower() for s in re.split(r"[,\r\n]+", text) if s.strip()]
    if not entries:
        raise ValueError("Observable-message file is empty")
    invalid = [s for s in entries if s != "time" and not SELECTOR_RE.fullmatch(s)]
    if invalid:
        raise ValueError("Use exact owner.message selectors (or time): " + ", ".join(invalid))
    if len(entries) != len(set(entries)):
        raise ValueError("Duplicate observable selector")
    return frozenset(entries)


def _natural(raw: str | None, context: str, default: str | None = None) -> int:
    value = raw if raw is not None else default
    if value is None or re.fullmatch(r"\d+", value.strip()) is None:
        raise ValueError(f"{context} must be a nonnegative integer, found {value!r}")
    return int(value)


def _argument_label(state: ET.Element, server: ET.Element, title: str) -> str:
    """Read only eligible messages in the executing owner's queue.

    Afra exports can omit which queued message was taken. Ambiguity is an
    error in argument-observing mode rather than a guessed first match.
    """
    owner = (server.get("owner") or "").lower()
    candidates: set[str] = set()
    for rebec in state.findall("rebec"):
        if (rebec.get("name") or "").lower() != owner:
            continue
        now = (rebec.findtext("now") or "").strip()
        for message in rebec.findall("queue/message"):
            match = MESSAGE_RE.fullmatch(message.text or "")
            if match is None or match.group(1).lower() != title:
                continue
            sender = server.get("sender")
            if sender is not None and message.get("sender") is not None:
                if sender.lower() != message.get("sender", "").lower():
                    continue
            arrival = message.get("arrival")
            if now and arrival is not None:
                if _natural(arrival, "Message arrival") > _natural(now, "Rebec time"):
                    continue
            arguments = ARGUMENT_SPACE_RE.sub(lambda part: part.group(1) or "", match.group(2) or "")
            candidates.add(arguments)
    if len(candidates) != 1:
        raise ValueError(
            f"Cannot identify unique arguments for {owner}.{title}: "
            f"{len(candidates)} eligible argument lists; compare message names instead"
        )
    return "[" + next(iter(candidates)) + "]"


def read_statespace(
    path: str | Path,
    observables: frozenset[str] | None = None,
    *,
    include_arguments: bool = False,
    initial_state: str | None = None,
) -> LTS:
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"Invalid XML in {path}: {error}") from error
    if root.tag != "transitionsystem":
        raise ValueError(f"Expected <transitionsystem> in {path}")
    states: dict[str, ET.Element] = {}
    for state in root.findall("state"):
        identifier = state.get("id")
        if not identifier or identifier in states:
            raise ValueError(f"Missing or duplicate state ID: {identifier!r}")
        states[identifier] = state
    if not states:
        raise ValueError(f"No states found in {path}")
    # IDs are opaque: suffixes are not discarded and need not be consecutive.
    ids = {identifier: index for index, identifier in enumerate(states)}
    if initial_state is None:
        initial_state = root.get("initial") or root.get("initialState")
    if initial_state is None:
        if "1_0" in ids:
            initial_state = "1_0"
        elif "0" in ids:
            initial_state = "0"
        else:
            initial_state = next(iter(ids))
    if initial_state not in ids:
        raise ValueError(f"Unknown initial state: {initial_state!r}")
    edges: set[tuple[int, str, int]] = set()
    for index, edge in enumerate(root.findall("transition"), start=1):
        source, target = edge.get("source"), edge.get("destination")
        if source not in ids or target not in ids:
            raise ValueError(f"Transition {index} refers to an unknown state ({source!r} -> {target!r})")
        # shift is a coordinate change in Afra's finite quotient, not a delay.
        _natural(edge.get("shift"), f"Transition {index} shift", "0")
        _natural(edge.get("executionTime"), f"Transition {index} executionTime", "0")
        children = list(edge)
        if len(children) != 1:
            raise ValueError(f"Transition {index} must have exactly one label child")
        child = children[0]
        if child.tag == "time":
            label = f"time +={_natural(child.get('value'), f'Transition {index} time')}"
        elif child.tag in {"tau", "internal"}:
            label = TAU
        elif child.tag == "messageserver":
            owner, title = child.get("owner"), child.get("title")
            if not owner or not title:
                raise ValueError(f"Transition {index} messageserver needs owner and title")
            title = title.strip().lower()
            selector = f"{owner.strip()}.{title}".lower()
            if title in {"tau", "τ"}:
                label = TAU
            elif SELECTOR_RE.fullmatch(selector) is None:
                raise ValueError(f"Invalid message label: {selector!r}")
            elif observables is not None and selector not in observables:
                label = TAU
            else:
                label = selector
                if include_arguments:
                    label += _argument_label(states[source], child, title)
        else:
            raise ValueError(f"Unsupported transition label <{child.tag}> at transition {index}")
        edges.add((ids[source], label, ids[target]))
    return LTS(ids[initial_state], len(ids), tuple(sorted(edges)))
