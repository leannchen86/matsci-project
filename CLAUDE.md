# matsci

## Virtual Environment

The Python virtual environment is located at `materials_discovery/.venv` (Python 3.12.3).

To activate:

```bash
source materials_discovery/.venv/bin/activate
```

## GNoME Auditor — Project Context

### Goal
Audit Google DeepMind's GNoME predicted crystal structures using classical inorganic chemistry rules that are **independent of the DFT/ML training pipeline**. The aim is objective reflection on chemical plausibility, not premature pass/fail judgment.

### Dataset
- 3,262 ternary oxygen-containing compounds filtered from GNoME's ~520k+ predicted materials
- CIF structures extracted from `by_id.zip`
- SQLite database: `materials_discovery/data/auditor_db/gnome_auditor.db`

### Package Structure
```
materials_discovery/gnome_auditor/
  cli.py              # CLI: ingest, validate, cross-ref, chat, stats
  config.py           # All paths, thresholds, reference values
  pipeline.py         # Orchestrates validation across all materials
  claude_interface.py # Tool-calling chat with Anthropic SDK
  data/
    ingest.py         # CSV + CIF loading, compound classification
    mp_cross_ref.py   # Materials Project cross-referencing
  db/
    schema.py         # SQLite tables, views, indexes
    store.py          # All DB read/write operations
  validators/
    base.py           # Abstract base class
    oxidation_states.py  # BVAnalyzer + oxi_state_guesses consensus
    charge_neutrality.py
    shannon_radii.py
    pauling_rule2.py
    bond_valence_sum.py
    goldschmidt.py
    space_group.py
  gold_data/          # Expert-curated synth/not-synth CSVs from ICSD
```

### Running the CLI
```bash
cd materials_discovery
source .venv/bin/activate
python -m gnome_auditor.cli stats        # View current results
python -m gnome_auditor.cli validate     # Run validation pipeline
python -m gnome_auditor.cli cross-ref    # MP cross-referencing (needs MP_API_KEY)
python -m gnome_auditor.cli chat         # Claude research interface (needs ANTHROPIC_API_KEY)
```

### Current Results (as of commit 9eca5ec)

| Validator | Computed | Coverage | Key Metric |
|-----------|----------|----------|------------|
| Charge Neutrality | 2,787 | 85.4% | Mean residual charge: -1.19 |
| Shannon Radii | 2,571 | 78.8% | Mean violation fraction: 0.006 (too lenient) |
| Pauling Rule 2 | 2,785 | 85.4% | Mean violation fraction: 0.17 |
| Bond Valence Sum | 2,588 | 79.3% | Mean GII: 0.52 v.u. (ICSD baseline: 0.2) |
| Space Group | 1,857 | 56.9% | 89.7% have novel space groups |
| Goldschmidt | 0 | 0% | Only 2 ABO3 perovskites in dataset |

**Compound classes:** 2,682 pure oxides, 282 oxychalcogenides, 257 oxyhalides, 29 oxynitrides, 12 oxyhydrides
**Oxi confidence:** 1,071 both_agree, 1,407 single_method, 309 methods_disagree, 475 no_assignment
**MP cross-ref:** 2,424 novel (74.3%), 837 computationally known (25.6%), 1 experimentally known (Sc3InO)

### Key Findings and Caveats
- 18% of dataset are NOT pure oxides — O2- assumption in charge neutrality/BVS may not hold
- BVS 86% "fail" rate reflects DFT-vs-ICSD geometry calibration offset, not chemical implausibility
- Shannon radii 99% pass means the 25% tolerance is too lenient to discriminate
- 449 materials (13.8%) have mixed valence (e.g. Fe2+/Fe3+)
- Binary pass/fail thresholds are inappropriate — all validators produce continuous scores

### Remaining Work
- Test Claude chat interface (`claude_interface.py`) with live ANTHROPIC_API_KEY
- Calibrate validators against synth/not-synth gold data (do chemistry flags predict synthesizability?)
- Visualizations and distribution plots
- Demo preparation
