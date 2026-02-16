# StackOverBond — GNoME Auditor

## Quick Start

```bash
source .venv/bin/activate
python -m gnome_auditor.cli stats              # View results
python -m gnome_auditor.export_data            # SQLite -> interface/data.js
python3 -m http.server 8080 --directory interface  # Serve frontend
```

## What This Is

Independent audit of GNoME crystal predictions using classical chemistry rules (charge neutrality, Shannon radii, Pauling rules, bond valence, space group plausibility). 3,262 ternary oxygen compounds. Results displayed in a Stack Overflow-inspired interface.

## Core Principle

**Ground truth = classical chemistry, not AI/ML.** Validators are deterministic and independent of GNoME's DFT/ML pipeline. Claude generates research questions about the data but never judges or validates materials.

## Opus Integration

1,700 materials have a Claude-generated research question ("Claude asks:") using cross-material family context — sibling compounds in the same chemical system. Generated via 68 parallel Claude Code subagents. See `gnome_auditor/opus_questions.py` for the prompt and data-prep helpers.

## Files

```
interface/index.html           # StackOverBond frontend
interface/data.js              # All 3,262 materials + validations (13 MB)
gnome_auditor/
  cli.py                       # CLI entry point
  pipeline.py                  # Validation orchestration
  export_data.py               # SQLite -> data.js
  opus_questions.py            # Question generation docs + prompt
  analysis.py                  # Calibration plots
  validators/                  # 6 validators + oxi state assignment
  db/                          # SQLite schema + queries
  data/                        # Ingestion + MP cross-referencing
  gold_data/                   # Synth/not-synth reference CSVs
data/opus_questions.json       # 1,700 Claude research questions
```

## Regenerating

```bash
source .venv/bin/activate
python -m gnome_auditor.export_data    # Regenerate data.js from SQLite
python -m gnome_auditor.cli validate   # Rerun validators (~17 min)
python -m gnome_auditor.analysis       # Regenerate calibration plots
```
