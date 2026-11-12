"""Small dependency-free LTS primitives, inspired by TiniActor (MIT)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

TAU = "tau"
TICK = "time +=1"
TIME_RE = re.compile(r"time\s*\+=\s*(\d+)\Z", re.IGNORECASE)
Transition = tuple[int, str, int]


@dataclass(frozen=True)
class LTS:
    initial: int
    num_states: int
    transitions: tuple[Transition, ...]

    def __post_init__(self) -> None:
        if self.num_states < 1 or not 0 <= self.initial < self.num_states:
            raise ValueError("Invalid LTS state count or initial state")
        for source, label, target in self.transitions:
            if not (0 <= source < self.num_states and 0 <= target < self.num_states):
                raise ValueError("Transition refers to an unknown state")
            if not label:
                raise ValueError("Transition label cannot be empty")


def reachable(lts: LTS) -> LTS:
    outgoing: list[set[tuple[str, int]]] = [set() for _ in range(lts.num_states)]
    for source, label, target in lts.transitions:
        outgoing[source].add((label, target))
    ids = {lts.initial: 0}
    pending = deque([lts.initial])
    edges: list[Transition] = []
    while pending:
        source = pending.popleft()
        for label, target in sorted(outgoing[source]):
            if target not in ids:
                ids[target] = len(ids)
                pending.append(target)
            edges.append((ids[source], label, ids[target]))
    return LTS(0, len(ids), tuple(edges))


def normalize_time(lts: LTS, max_states: int = 1_000_000) -> LTS:
    """Realize discrete continuity: d becomes d visible unit ticks.

    Zero time is silent. Shift-equivalence metadata is NOT elapsed time.
    Positive time cycles remain cycles; no maximal-path enumeration is used.
    """
    if max_states < 1:
        raise ValueError("max_states must be positive")
    lts = reachable(lts)
    count = lts.num_states
    if count > max_states:
        raise ValueError(f"State limit exceeded ({max_states}); increase --max-states")
    edges: list[Transition] = []
    for source, label, target in lts.transitions:
        match = TIME_RE.fullmatch(label)
        if match is None:
            edges.append((source, label, target))
            continue
        duration = int(match.group(1))
        if count + max(0, duration - 1) > max_states:
            raise ValueError(f"Time expansion exceeds {max_states} states; increase --max-states")
        if duration == 0:
            edges.append((source, TAU, target))
            continue
        previous = source
        for _ in range(duration - 1):
            edges.append((previous, TICK, count))
            previous = count
            count += 1
        edges.append((previous, TICK, target))
    return LTS(lts.initial, count, tuple(edges))


def disjoint_union(left: LTS, right: LTS) -> tuple[LTS, int, int]:
    offset = left.num_states
    edges = left.transitions + tuple(
        (s + offset, label, t + offset) for s, label, t in right.transitions
    )
    return LTS(left.initial, offset + right.num_states, edges), left.initial, right.initial + offset


def condense_tau(lts: LTS) -> tuple[LTS, list[int]]:
    """Collapse tau SCCs using iterative Kosaraju, as in TiniActor.

    Return the original-to-component map, retaining both input roots.
    """
    outgoing: list[set[int]] = [set() for _ in range(lts.num_states)]
    incoming: list[set[int]] = [set() for _ in range(lts.num_states)]
    for source, label, target in lts.transitions:
        if label == TAU:
            outgoing[source].add(target)
            incoming[target].add(source)
    visited: set[int] = set()
    order: list[int] = []
    for root in range(lts.num_states):
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, iter(outgoing[root]))]
        while stack:
            state, children = stack[-1]
            target = next(children, None)
            if target is None:
                order.append(state)
                stack.pop()
            elif target not in visited:
                visited.add(target)
                stack.append((target, iter(outgoing[target])))
    component = [-1] * lts.num_states
    count = 0
    for root in reversed(order):
        if component[root] >= 0:
            continue
        component[root] = count
        pending = [root]
        while pending:
            state = pending.pop()
            for target in incoming[state]:
                if component[target] < 0:
                    component[target] = count
                    pending.append(target)
        count += 1
    edges = {
        (component[s], label, component[t]) for s, label, t in lts.transitions
        if label != TAU or component[s] != component[t]
    }
    return LTS(component[lts.initial], count, tuple(sorted(edges))), component


def tau_dag(lts: LTS) -> tuple[list[set[int]], list[int]]:
    outgoing: list[set[int]] = [set() for _ in range(lts.num_states)]
    indegree = [0] * lts.num_states
    for source, label, target in lts.transitions:
        if label == TAU and target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    pending = deque(s for s, degree in enumerate(indegree) if degree == 0)
    order: list[int] = []
    while pending:
        source = pending.popleft()
        order.append(source)
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    if len(order) != lts.num_states:
        raise ValueError("Internal error: tau graph must be condensed first")
    return outgoing, list(reversed(order))


def format_aut(lts: LTS) -> str:
    lines = [f"des ({lts.initial},{len(lts.transitions)},{lts.num_states})"]
    for source, label, target in lts.transitions:
        escaped = label.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'({source},"{escaped}",{target})')
    return "\n".join(lines) + "\n"
