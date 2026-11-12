from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from semanticchecker.cli import compare_mcrl2, main
from semanticchecker.equivalence import weak_bisimilar, weak_trace_equivalent
from semanticchecker.lts import LTS, TAU, TICK, normalize_time
from semanticchecker.statespace import read_observables, read_statespace

ROOT = Path(__file__).resolve().parents[1]


def graph(states, edges, initial=0):
    return LTS(initial, states, tuple(edges))


def reference_weak_bisimilar(left, right):
    """Independent cross-product greatest-fixed-point oracle for tiny graphs."""
    def weak_steps(lts):
        closures = []
        for state in range(lts.num_states):
            seen = {state}
            pending = [state]
            while pending:
                source = pending.pop()
                for s, label, target in lts.transitions:
                    if s == source and label == TAU and target not in seen:
                        seen.add(target)
                        pending.append(target)
            closures.append(seen)
        steps = []
        for source in range(lts.num_states):
            outgoing = {TAU: set(closures[source])}
            for middle in closures[source]:
                for s, label, target in lts.transitions:
                    if s == middle and label != TAU:
                        outgoing.setdefault(label, set()).update(closures[target])
            steps.append(outgoing)
        return steps
    a, b = weak_steps(left), weak_steps(right)
    relation = {(s, t) for s in range(left.num_states) for t in range(right.num_states)}
    while True:
        def matches(first, second, s, t, converse=False):
            return all(
                any(((u, v) if not converse else (v, u)) in relation for v in second[t].get(label, set()))
                for label, targets in first[s].items() for u in targets
            )
        refined = {(s, t) for s, t in relation
                   if matches(a, b, s, t) and matches(b, a, t, s, True)}
        if refined == relation:
            return (left.initial, right.initial) in relation
        relation = refined


class EquivalenceTests(unittest.TestCase):
    def assert_both(self, left, right, expected):
        left, right = normalize_time(left), normalize_time(right)
        self.assertEqual(weak_bisimilar(left, right).equivalent, expected)
        self.assertEqual(weak_trace_equivalent(left, right).equivalent, expected)

    def test_accumulated_time_through_internal_action(self):
        self.assert_both(
            graph(4, [(0, "time +=3", 1), (1, TAU, 2), (2, "time +=7", 3), (3, "a.fire", 3)]),
            graph(2, [(0, "time +=10", 1), (1, "a.fire", 1)]), True,
        )

    def test_different_time(self):
        self.assert_both(graph(2, [(0, "time +=3", 1)]), graph(2, [(0, "time +=4", 1)]), False)

    def test_visible_action_interrupts_time_accumulation(self):
        self.assert_both(
            graph(3, [(0, "time +=1", 1), (1, "a.fire", 2), (2, "time +=1", 2)]),
            graph(2, [(0, "time +=2", 1), (1, "a.fire", 1)]), False,
        )

    def test_positive_time_cycle_is_not_dropped(self):
        self.assert_both(graph(1, [(0, "time +=2", 0)]), graph(1, []), False)
        self.assert_both(graph(1, [(0, "time +=2", 0)]), graph(1, [(0, TICK, 0)]), True)

    def test_zero_time_and_tau_divergence(self):
        self.assert_both(graph(2, [(0, "time +=0", 1), (1, TAU, 0)]), graph(1, []), True)

    def test_tau_prefix_suffix_and_cycles(self):
        self.assert_both(
            graph(4, [(0, TAU, 1), (1, TAU, 0), (1, "a.fire", 2), (2, TAU, 3)]),
            graph(2, [(0, "a.fire", 1)]), True,
        )

    def test_trace_equivalence_does_not_imply_bisimulation(self):
        left = graph(4, [(0, "a", 1), (1, "b", 2), (1, "c", 3)])
        right = graph(5, [(0, "a", 1), (0, "a", 2), (1, "b", 3), (2, "c", 4)])
        self.assertTrue(weak_trace_equivalent(left, right).equivalent)
        self.assertFalse(weak_bisimilar(left, right).equivalent)

    def test_internal_commitment_is_preserved(self):
        left = graph(2, [(0, "a", 1), (0, "b", 1)])
        right = graph(4, [(0, TAU, 1), (0, TAU, 2), (1, "a", 3), (2, "b", 3)])
        self.assertTrue(weak_trace_equivalent(left, right).equivalent)
        self.assertFalse(weak_bisimilar(left, right).equivalent)

    def test_branching_action_at_an_intermediate_time_is_preserved(self):
        left = graph(3, [(0, TICK, 1), (1, "a", 2), (1, TICK, 2)])
        right = graph(2, [(0, "time +=2", 1)])
        self.assert_both(left, right, False)

    def test_roots_and_unreachable_states(self):
        self.assert_both(graph(3, [(2, "a", 1), (0, "b", 0)], 2), graph(2, [(0, "a", 1)]), True)

    def test_shortest_distinguishing_trace(self):
        left = graph(3, [(0, "a", 1), (1, "b", 2)])
        right = graph(2, [(0, "a", 1)])
        self.assertEqual(weak_trace_equivalent(left, right).counterexample, ("a", "b"))

    def test_resource_limits_are_errors(self):
        with self.assertRaisesRegex(ValueError, "expansion"):
            normalize_time(graph(2, [(0, "time +=1000000000", 1)]), 100)
        with self.assertRaisesRegex(ValueError, "pairs"):
            weak_trace_equivalent(graph(2, [(0, "a", 1)]), graph(2, [(0, "a", 1)]), 1)

    def test_random_graphs_against_independent_bisimulation_oracle(self):
        rng = random.Random(2407)
        for _ in range(250):
            spaces = []
            for _ in (1, 2):
                n = rng.randint(1, 5)
                edges = [(s, label, t) for s in range(n) for t in range(n)
                         for label in (TAU, TICK, "a", "b") if rng.random() < 0.12]
                spaces.append(graph(n, edges, rng.randrange(n)))
            with self.subTest(spaces=spaces):
                self.assertEqual(weak_bisimilar(*spaces).equivalent, reference_weak_bisimilar(*spaces))


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, text, name="input.statespace"):
        path = self.root / name
        path.write_text(text, encoding="utf-8-sig")
        return path

    def parse(self, xml, **kwargs):
        return read_statespace(self.write(xml), **kwargs)

    def test_sparse_and_suffix_ids_are_distinct(self):
        lts = self.parse('<transitionsystem initial="7_1"><state id="7_0"/><state id="7_1"/>'
                         '<transition source="7_1" destination="7_0"><time value="2"/></transition></transitionsystem>')
        self.assertEqual((lts.num_states, lts.initial), (2, 1))

    def test_afra_initial_state_is_independent_of_xml_order(self):
        lts = self.parse('<transitionsystem><state id="2_0"/><state id="1_0"/></transitionsystem>')
        self.assertEqual(lts.initial, 1)

    def test_selector_exactness_and_shift_metadata(self):
        xml = '<transitionsystem><state id="1_0"/><state id="2_0"/>'
        xml += '<transition source="1_0" destination="2_0" shift="50" executionTime="100">'
        xml += '<messageserver owner="Second" title="UPDATE"/></transition></transitionsystem>'
        lts = self.parse(xml, observables=frozenset({"first.update"}))
        self.assertEqual(lts.transitions, ((0, TAU, 1),))
        self.assertEqual(normalize_time(lts).num_states, 2)

    def test_time_is_observed_even_when_not_in_selector_file(self):
        lts = self.parse('<transitionsystem><state id="1_0"/>'
                         '<transition source="1_0" destination="1_0"><time value="2"/></transition></transitionsystem>',
                         observables=frozenset({"a.fire"}))
        self.assertEqual(lts.transitions[0][1], "time +=2")

    def test_arguments_come_from_executing_owner_and_exact_message(self):
        xml = '''<transitionsystem><state id="1_0">
        <rebec name="other"><queue><message>fire(99)</message></queue></rebec>
        <rebec name="a"><queue><message>prefire(88)</message>
        <message sender="b" arrival="0">fire(1, 2)</message>
        <message sender="b" arrival="5">fire(3, 4)</message></queue><now>0</now></rebec></state>
        <transition source="1_0" destination="1_0"><messageserver owner="a" title="FIRE" sender="b"/></transition>
        </transitionsystem>'''
        self.assertEqual(self.parse(xml, include_arguments=True).transitions[0][1], "a.fire[1,2]")
        self.assertEqual(self.parse(xml).transitions[0][1], "a.fire")

    def test_ambiguous_arguments_are_not_guessed(self):
        xml = '''<transitionsystem><state id="1_0"><rebec name="a"><queue>
        <message>fire(1)</message><message>fire(2)</message></queue></rebec></state>
        <transition source="1_0" destination="1_0"><messageserver owner="a" title="FIRE"/></transition>
        </transitionsystem>'''
        with self.assertRaisesRegex(ValueError, "unique arguments"):
            self.parse(xml, include_arguments=True)

    def test_argument_string_case_and_whitespace_are_preserved(self):
        xml = '''<transitionsystem><state id="1_0"><rebec name="a"><queue>
        <message>fire(&quot;Red Blue&quot;, 2)</message></queue></rebec></state>
        <transition source="1_0" destination="1_0"><messageserver owner="a" title="FIRE"/></transition>
        </transitionsystem>'''
        self.assertEqual(self.parse(xml, include_arguments=True).transitions[0][1], 'a.fire["Red Blue",2]')

    def test_invalid_xml_and_graphs_are_errors(self):
        for xml in (
            '<broken>', '<wrong/>', '<transitionsystem/>',
            '<transitionsystem><state id="1"/><state id="1"/></transitionsystem>',
            '<transitionsystem><state id="1"/><transition source="1" destination="missing"><tau/></transition></transitionsystem>',
            '<transitionsystem><state id="1"/><transition source="1" destination="1"><time value="-1"/></transition></transitionsystem>',
            '<transitionsystem><state id="1"/><transition source="1" destination="1"><unknown/></transition></transitionsystem>',
        ):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.parse(xml)

    def test_observable_file_validation(self):
        self.assertEqual(read_observables(self.write("A.fire, b.update\ntime", "o.txt")), frozenset({"a.fire", "b.update", "time"}))
        for text in ("", "fire", "a.fire,A.FIRE", "time +=2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_observables(self.write(text, "o.txt"))


class CLITests(unittest.TestCase):
    def test_real_afra_examples_both_relations(self):
        observable = read_observables(ROOT / "examples/observable_messages.txt")
        left = normalize_time(read_statespace(ROOT / "examples/heater-v1.statespace", observable))
        for variant in (2, 3):
            right = normalize_time(read_statespace(ROOT / f"examples/heater-v{variant}.statespace", observable))
            self.assertTrue(weak_bisimilar(left, right).equivalent)
            self.assertTrue(weak_trace_equivalent(left, right).equivalent)

    def test_yes_no_and_error_exit_codes(self):
        sample = ROOT / "examples/heater-v1.statespace"
        with tempfile.TemporaryDirectory() as directory:
            deadlock = Path(directory) / "deadlock.statespace"
            deadlock.write_text('<transitionsystem><state id="1_0"/></transitionsystem>')
            for argv, expected_code, expected_output in (
                ([str(sample), str(sample)], 0, "YES"),
                ([str(sample), str(deadlock)], 1, "NO"),
                ([str(sample), str(deadlock), "--equivalence", "weak-trace"], 1, "NO"),
            ):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(argv), expected_code)
                self.assertEqual(stdout.getvalue().strip(), expected_output)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main([str(sample), "missing.statespace"]), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Error:", stderr.getvalue())

    def test_module_entry_point(self):
        sample = str(ROOT / "examples/heater-v1.statespace")
        result = subprocess.run([os.sys.executable, "-m", "semanticchecker", sample, sample],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "YES")

    def test_json_includes_distinguishing_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = [Path(directory) / f"{name}.statespace" for name in ("first", "second")]
            first.write_text('<transitionsystem><state id="1_0"/><transition source="1_0" destination="1_0"><time value="1"/></transition></transitionsystem>')
            second.write_text('<transitionsystem><state id="1_0"/></transitionsystem>')
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main([str(first), str(second), "-e", "weak-trace", "--json"]), 1)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["equivalent"])
            self.assertEqual(result["counterexample"], [TICK])

    def test_mcrl2_failure_is_not_inequivalence(self):
        lts = graph(1, [])
        with self.assertRaisesRegex(ValueError, "not found"):
            compare_mcrl2(lts, lts, "weak-bisim", "nonexistent-ltscompare-executable")
        with patch("semanticchecker.cli.shutil.which", return_value="ltscompare"):
            with patch("semanticchecker.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("ltscompare", 1)):
                with self.assertRaisesRegex(ValueError, "timed out"):
                    compare_mcrl2(lts, lts, "weak-bisim")
            for code, output in ((1, "false"), (0, "unexpected")):
                with patch("semanticchecker.cli.subprocess.run", return_value=subprocess.CompletedProcess([], code, output, "failure")):
                    with self.assertRaises(ValueError):
                        compare_mcrl2(lts, lts, "weak-bisim")


MCRL2 = shutil.which("ltscompare")
if MCRL2 is None and Path("C:/Program Files/mCRL2/bin/ltscompare.exe").is_file():
    MCRL2 = "C:/Program Files/mCRL2/bin/ltscompare.exe"


@unittest.skipUnless(MCRL2, "optional mCRL2 ltscompare is not installed")
class MCRL2DifferentialTests(unittest.TestCase):
    def test_random_normalized_graphs_match_both_mcrl2_relations(self):
        rng = random.Random(1611)
        for _ in range(75):
            spaces = []
            for _ in (1, 2):
                n = rng.randint(1, 5)
                edges = [(s, label, t) for s in range(n) for t in range(n)
                         for label in (TAU, "time +=0", "time +=2", "a", "b") if rng.random() < 0.08]
                spaces.append(normalize_time(graph(n, edges, rng.randrange(n))))
            for equivalence, function in (("weak-bisim", weak_bisimilar), ("weak-trace", weak_trace_equivalent)):
                with self.subTest(equivalence=equivalence, spaces=spaces):
                    self.assertEqual(function(*spaces).equivalent,
                                     compare_mcrl2(*spaces, equivalence, MCRL2).equivalent)

    def test_real_afra_examples_match_mcrl2(self):
        obs = read_observables(ROOT / "examples/observable_messages.txt")
        left = normalize_time(read_statespace(ROOT / "examples/heater-v1.statespace", obs))
        for variant in (2, 3):
            right = normalize_time(read_statespace(ROOT / f"examples/heater-v{variant}.statespace", obs))
            for equivalence in ("weak-bisim", "weak-trace"):
                self.assertTrue(compare_mcrl2(left, right, equivalence, MCRL2).equivalent)


if __name__ == "__main__":
    unittest.main()
