"""Exact finite-state weak bisimulation and finite weak-trace equality.

Callers pass unit-time-normalized LTSs. Time ticks remain visible actions.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .lts import LTS, TAU, condense_tau, disjoint_union, tau_dag


@dataclass(frozen=True)
class Comparison:
    equivalent: bool
    explored_pairs: int | None = None
    counterexample: tuple[str, ...] | None = None


def weak_bisimilar(left: LTS, right: LTS) -> Comparison:
    """Refine the disjoint union modulo strong bisimulation of saturation.

    Each signature represents tau* and tau* a tau* target blocks. Propagating
    signatures over the tau DAG avoids materializing all saturated edges.
    Tau* includes identity, so internal branching commitments are preserved.
    """
    joined, left_root, right_root = disjoint_union(left, right)
    lts, component = condense_tau(joined)
    left_root, right_root = component[left_root], component[right_root]
    tau, reverse_order = tau_dag(lts)
    visible: list[list[tuple[str, int]]] = [[] for _ in range(lts.num_states)]
    for source, label, target in lts.transitions:
        if label != TAU:
            visible[source].append((label, target))
    blocks = [0] * lts.num_states
    while True:
        closures: list[set[int]] = [{blocks[s]} for s in range(lts.num_states)]
        for source in reverse_order:
            for target in tau[source]:
                closures[source].update(closures[target])
        weak = [defaultdict(set) for _ in range(lts.num_states)]
        for source in reverse_order:
            for label, target in visible[source]:
                weak[source][label].update(closures[target])
            for target in tau[source]:
                for label, targets in weak[target].items():
                    weak[source][label].update(targets)
        signatures: dict[tuple, int] = {}
        refined: list[int] = []
        for state in range(lts.num_states):
            signature = (
                blocks[state], frozenset(closures[state]),
                frozenset((label, frozenset(targets)) for label, targets in weak[state].items()),
            )
            refined.append(signatures.setdefault(signature, len(signatures)))
        if refined[left_root] != refined[right_root]:
            return Comparison(False)
        if refined == blocks:
            return Comparison(True)
        blocks = refined


class _WeakSteps:
    def __init__(self, lts: LTS):
        self.lts, component = condense_tau(lts)
        self.initial_state = component[lts.initial]
        tau, reverse_order = tau_dag(self.lts)
        self.closures = [1 << state for state in range(self.lts.num_states)]
        for source in reverse_order:
            for target in tau[source]:
                self.closures[source] |= self.closures[target]
        self.visible: list[list[tuple[str, int]]] = [[] for _ in range(self.lts.num_states)]
        for source, label, target in self.lts.transitions:
            if label != TAU:
                self.visible[source].append((label, target))
        self.initial = self.closures[self.initial_state]

    def steps(self, subset: int) -> dict[str, int]:
        targets: dict[str, int] = {}
        while subset:
            bit = subset & -subset
            subset ^= bit
            for label, target in self.visible[bit.bit_length() - 1]:
                targets[label] = targets.get(label, 0) | self.closures[target]
        return targets


def weak_trace_equivalent(left: LTS, right: LTS, max_pairs: int = 100_000) -> Comparison:
    """Explore reachable pairs of tau-closed subsets, without a depth cutoff.

    Every state accepts the empty trace. An enabled-label difference yields
    a shortest distinguishing finite trace. Resource exhaustion raises an
    error; it is never reported as either YES or NO.
    """
    if max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    first, second = _WeakSteps(left), _WeakSteps(right)
    initial = (first.initial, second.initial)
    pending = deque([initial])
    parents: dict[tuple[int, int], tuple[tuple[int, int], str] | None] = {initial: None}
    while pending:
        pair = pending.popleft()
        first_steps, second_steps = first.steps(pair[0]), second.steps(pair[1])
        difference = first_steps.keys() ^ second_steps.keys()
        if difference:
            trace = [min(difference)]
            cursor = pair
            while parents[cursor] is not None:
                cursor, label = parents[cursor]
                trace.append(label)
            return Comparison(False, len(parents), tuple(reversed(trace)))
        for label in sorted(first_steps):
            target_pair = (first_steps[label], second_steps[label])
            if target_pair not in parents:
                if len(parents) >= max_pairs:
                    raise ValueError(f"Trace exploration exceeds {max_pairs} pairs; increase --max-pairs")
                parents[target_pair] = (pair, label)
                pending.append(target_pair)
    return Comparison(True, len(parents))
