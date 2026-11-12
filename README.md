# SemanticChecker

Compare two Timed Rebeca / Afra `.statespace` files using **weak timed
bisimulation** or **weak timed trace equivalence**, with discrete time.
Runs on Python 3.10 or newer with no external Python packages.

The pipeline follows the design of **TiniActor**: parse Afra XML, select
observable messages, account for elapsed time, then apply a weak equivalence.
The default backend is Python. `--mcrl2` uses an installed mCRL2 `ltscompare`
with the same normalized inputs.

## Run

Two state spaces are the only required inputs. All message-server names are
observable by default, and time is always observable:

```bash
python semantic_checker.py first.statespace second.statespace
```

Supply a third file to select observable messages, as in TiniActor:

```bash
python semantic_checker.py \
    examples/heater-v1.statespace examples/heater-v3.statespace \
    examples/observable_messages.txt
```

This example prints `YES`. On Windows the same command can be written on one
line; `py` can replace `python` when the Python launcher is installed.

Choose the relation with `-e` / `--equivalence`:

```bash
python semantic_checker.py first.statespace second.statespace observable_messages.txt --equivalence weak-bisim
python semantic_checker.py first.statespace second.statespace observable_messages.txt --equivalence weak-trace
```

`weak-bisim` is the default. Both relations are divergence-insensitive: internal
`tau` loops alone do not distinguish two systems. Bisimulation preserves
branching commitments; trace equivalence compares the sets of finite timed
traces. Trace equivalence can hold when bisimulation does not.

The module entry point also works from the repository directory:

```bash
python -m semanticchecker first.statespace second.statespace
```

## Results

| Standard output | Exit code | Meaning |
|---|---:|---|
| `YES` | 0 | Equivalent for the selected relation |
| `NO` | 1 | Non-equivalent for the selected relation |
| No verdict; error on stderr | 2 | Invalid input, resource limit, or backend failure |

`--json` prints the verdict, backend, relation, state/transition counts, and a
shortest distinguishing finite trace when the Python trace checker finds one.
The JSON trace includes unit time ticks; consecutive ticks can be summed.
Bisimulation failures and mCRL2 results do not currently include a witness.
An error never produces a semantic `NO` verdict.

## Observable messages

The optional observable file contains comma-separated or line-separated entries:

```text
controller.getsense
hc_unit.activateh
hc_unit.switchoff
time
```

Entries must have the exact `owner.message` form; the owner is the **rebec
instance** written in the XML `messageserver` element. Matching is
case-insensitive. For example, `first.update` selects that instance's handler;
`second.update` is a separate observation. Unqualified message names and
duplicate entries are rejected. Selected messages may be absent in an input,
which is useful when a revision removes an observable handler execution.

Every unselected handler becomes `tau`. The reserved entry `time` is accepted
for compatibility with TiniActor observable files. Time remains visible when
this entry is omitted, because these are timed equivalences.

By default observations contain **only the qualified message-server name**,
matching the benchmark's handler-execution semantics. State variables and
nondeterministic branch results are not added to action labels.

To also observe message argument values, add `--include-arguments`. Arguments
are read from eligible messages in the executing owner's queue, with exact
message-name and sender matching. If the export does not identify a unique
argument list, the checker reports an error. This option defines a stronger
observation policy than the default benchmark policy.

## Time and weak semantics

Each explicit XML `<time value="d"/>` edge advances time by a nonnegative
integer `d`. A positive delay is expanded into `d` transitions labeled
`time +=1` through fresh intermediate states; zero delay becomes `tau`.
Consequently, a delay of `10` matches delays of `3` and `7` separated by hidden
actions. Observable actions interrupt the time sequence. Positive time cycles
are retained, allowing arbitrarily long elapsed times.

This is the discrete-continuity interpretation in the paper's preliminaries.
On these unit-time systems, ordinary weak bisimulation matches weak action
steps `tau* a tau*`, weak zero-time steps `tau*`, and weak one-unit time steps.
Repeated one-unit matches establish the corresponding accumulated-time steps.
The same encoding represents finite timed traces by sequences of visible
actions and unit ticks.

Afra's `shift` and `executionTime` attributes describe its finite
shift-equivalence representation. They are validated as metadata; the checker
obtains elapsed time from explicit `<time>` edges. A shift is not an extra
delay and is not an observable label.

## Algorithms

- **Weak timed bisimulation:** construct the disjoint union, collapse internal
  strongly connected components, then refine partitions using `tau*` and
  `tau* a tau*` target-block signatures. Signatures are propagated over the
  internal DAG without materializing all saturated transitions.
- **Weak timed trace equivalence:** explore reachable pairs of determinized,
  internally closed state subsets using breadth-first search. A difference
  yields a shortest distinguishing trace. Equality is checked to completion,
  with no trace-length cutoff.

State IDs are treated as opaque XML IDs, including their suffixes. The initial
state is selected from `initial` / `initialState` on the root, then Afra's
`1_0`, then `0`, then the first listed state. Use `--initial-left ID` and
`--initial-right ID` to override the two roots. Unreachable states do not
affect the verdict.

Supported transition label elements are `<messageserver>`, `<time>`, `<tau>`,
and `<internal>`. Unsupported or malformed labels are errors. Inputs must
represent finite, non-probabilistic, discretely timed transition systems.
The checker operates on the exported graph; it does not generate state spaces
or verify that the source model satisfies Afra's modeling assumptions.

## Optional mCRL2 backend

```bash
python semantic_checker.py first.statespace second.statespace observable_messages.txt --mcrl2 --equivalence weak-bisim
```

Install [mCRL2](https://www.mcrl2.org/) and put `ltscompare` in `PATH`, or pass
`--ltscompare /path/to/ltscompare`. The standard Windows installation at
`C:\Program Files\mCRL2\bin\ltscompare.exe` is detected automatically.
Intermediate AUT files are written to a temporary directory and removed after
the comparison. mCRL2 receives `--equivalence=weak-bisim` or
`--equivalence=weak-trace`; see the
[official ltscompare manual](https://www.mcrl2.org/web/user_manual/tools/release/ltscompare.html).

## Limits and testing

Time expansion is bounded by `--max-states` (default 1,000,000 normalized states
per input). Python trace exploration is bounded by `--max-pairs` (default
100,000 subset pairs). Reaching a bound produces an error; raise the relevant
limit to continue. Weak trace determinization can require exponentially many
subsets. The mCRL2 subprocess has a `--timeout` in seconds (default 300).

Run the tests:

```bash
python -m unittest discover -s tests -v
```

The suite covers time splitting, accumulated and cyclic time, hidden branching,
the distinction between trace and bisimulation, arbitrary roots, malformed
XML, observation selection, argument ambiguity, limits, and CLI exit codes.
It includes 250 comparisons against an independent fixed-point bisimulation
oracle and 75 random input pairs checked under both relations against mCRL2
when installed. Included Afra heater examples are also checked under both
relations. The complete suite was verified with mCRL2 202407.1.

For the corresponding Rebeca source scenarios and supplied reference answers,
see [BehavorialAnalysisBenchmark](https://github.com/AliAtaollahi/BehavorialAnalysisBenchmark).

## Attribution and license

MIT; see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
