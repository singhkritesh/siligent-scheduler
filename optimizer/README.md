# Optimizer

This package owns deterministic scheduling feasibility and ranking. The initial
engine enumerates valid candidates for a newly arriving patient from
materialized patient, doctor, and room availability. It protects every active
appointment passed to it and produces ranked, explainable recommendations.

The candidate engine is deliberately dependency-free so its core constraints can
be tested everywhere. A later CP-SAT layer will use OR-Tools for batch scheduling
and approved hypothetical rescheduling. OR-Tools and its pinned transitive
dependencies must be included in the signed offline build bundle.

Run the core tests:

```bash
python3 -m unittest discover -s optimizer/tests -v
```

Run the deterministic year-horizon simulation:

```bash
python3 optimizer/tests/simulate_year.py
```

Generate and replay a privacy-safe CSV of 100 synthetic appointment requests:

```bash
python3 scripts/generate_synthetic_appointments.py
python3 optimizer/tests/simulate_csv.py
```

The generated input, scheduled-result CSV, and JSON report are written under
the ignored `data/synthetic/` runtime-data directory. Patient values are opaque
synthetic references; the files contain no names, record numbers, or free-text
clinical notes. Pass `--rows`, `--seed`, `--start-date`, or output-path options
to produce a different deterministic scenario.
