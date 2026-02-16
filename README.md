# Curious Materials

DeepMind's GNoME neural net predicted 520k new materials. We let Claude go over 3k of them and ask the questions that 3k decent grad students would have asked!

## Quick Start

```bash
python3 -m http.server 8080 --directory interface
```

Open `http://localhost:8080` in your browser

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## What Claude Asks

For each material we first generate these 5 validations traditionally:

| Validator | What it checks | Tier |
|-----------|---------------|------|
| Charge Neutrality | Oxidation states sum to zero | 1 (DFT-independent) |
| Shannon Radii | Bond lengths match expected ionic radii | 1 |
| Pauling Rule 2 | Electrostatic valence around O sites | 1 |
| Bond Valence Sum (GII) | Global bond strain | 2 (uses DFT geometry) |
| Space Group | Matches experimental databases | 2 |

Then Claude goes over each material, looks at these validations and the **related materials**, and ask one really great question.

## Project Structure

```
interface/
  index.html              # Curious Materials frontend
  data.js                 # All 3,262 materials + validation results (13 MB)
gnome_auditor/
  cli.py                  # CLI: python -m gnome_auditor.cli {stats,validate,...}
  pipeline.py             # Validation pipeline orchestration
  export_data.py          # SQLite -> data.js
  opus_questions.py       # Question generation docs + prompt
  analysis.py             # Calibration plots
  validators/             # 6 validators + oxi state assignment
  db/                     # SQLite schema + queries
  data/                   # Ingestion + MP cross-referencing
  gold_data/              # Synth/not-synth reference CSVs (ICSD)
data/
  opus_questions.json     # 1,700 Claude research questions
```

## Regenerating Data

```bash
source .venv/bin/activate
python -m gnome_auditor.export_data      # Regenerate data.js
python -m gnome_auditor.cli stats        # View pipeline results
python -m gnome_auditor.analysis         # Generate calibration plots
```

## License

Apache 2.0 (code). GNoME data under CC BY-NC 4.0 per [Google's terms](https://creativecommons.org/licenses/by-nc/4.0/).

Built for the Anthropic Claude Code Hackathon, Feb 2025.
