# Templates Stick, Rules Don't

Code, per-run results, and candidate configurations for the Kaggle Gemma 4 Developer Agent paper-track writeup *Templates Stick, Rules Don't: What 4,400 Controlled Runs Show About a Gemma 4 Coding Agent*.

All runs use gemma-4-31B-it-qat-w4a16 (Kaggle v2 weights) under the official swegemma 0.2.11 harness, on 125 gradable public tasks (FastAPI 64, Rich 47, Requests 13, HTTPX 1), 2 passes per task.

## Contents

| Path | What it is |
| --- | --- |
| `analysis/paper_stats.py` | Recomputes the paired comparisons, same-configuration noise, power simulation, and the before/after missing-argument rates (Sections 4.1 and 4.2) from the raw result packages, and checks them against the numbers in each round's report. Comments are in Chinese. |
| `analysis/README_zh.md` | Original (Chinese) usage notes for the script: inputs, outputs, and checks. |
| `results/rounds_1-7/` | Script output for the Budget-Fit baseline and rounds 1–7: `runs.csv` (one row per run), `comparisons.csv` (one row per paired comparison), `stats.json`, `summary.md` (Chinese), and the CSVs behind both figures. |
| `results/round10_T8/`, `results/round11_T8-R1/` | Per-run tables for the two T8 batches (rounds 10 and 11), as written by the evaluation runner: task, pass, outcome, time, calls, and tokens (columns differ from `rounds_1-7/runs.csv`). |
| `candidates/` | Configuration packages (`agent.yaml`, `eval_config.yaml`, prompts, skills) for the Budget-Fit baseline and our 16 candidates. |
| `figures/` | The two figures of the writeup. |

## Candidates

| Folder | Round | Change relative to its control |
| --- | --- | --- |
| `budget_fit_base` | 1 | Public Budget-Fit configuration (8 min, 28 counted calls, 80 turns, temperature 0.2) |
| `C01`, `R01` | 1 | Working rules; argument-error recovery rule |
| `C01b` | 2 | Tool-calling rules on top of Budget-Fit; control from round 2 on |
| `C03b`, `C04` | 2 | C01b plus a verification skill; temperature 0.7 and top_k 64 |
| `C01c` | 3 | Per-tool error-recovery section |
| `T2048`, `T3072`, `X` | 4 | Thinking caps 2048 and 3072; read and search rules |
| `V` | 5 | Contract checks before and after edits |
| `E` | 6 | Two write tools removed; writes via the terminal |
| `K2`, `K3` | 7 | Fixed editing helper; K2 plus install and heredoc templates |
| `B30` | 7 | Call budget 28 → 30 |
| `task_pin` | 8 | Task statement appended to the system prompt |
| `LB1` | 9 | Edit via a Python script after a missing argument |

T8 is a public solution by navyadevadiga ([gemma4-swe-agent-t8-static](https://www.kaggle.com/code/navyadevadiga/gemma4-swe-agent-t8-static), scriptVersionId 360787674); its configuration is not redistributed here. T8-R1 is T8 with the call budget raised to 30 and a 90-second command timeout.

## Reproducing the numbers

```bash
python analysis/paper_stats.py --results <result-package-dir> --a0 <formal_a0_full_20261020.tgz> --out out --figures
```

The script reads the zip and tgz result packages directly (Python 3.10+, numpy for the power simulation, matplotlib for figures). The raw result packages and agent traces are not included in this repository; the per-run tables in `results/` hold the outcome and tool-call metrics for every run.

## Attribution and license

The Budget-Fit configuration comes from a public Kaggle notebook by verracodeguacas (Apache 2.0). The local sandbox was rebuilt from a public notebook. Everything else in this repository is released under the Apache License 2.0 (see `LICENSE`).
