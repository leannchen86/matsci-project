# matsci — GNoME Auditor + StackOverBond

## Quick Start

```bash
cd materials_discovery
source .venv/bin/activate  # Python 3.12.3

# Core pipeline (already run — results in SQLite)
python -m gnome_auditor.cli stats        # View results
python -m gnome_auditor.cli validate     # Run validators (takes ~17 min)
python -m gnome_auditor.cli cross-ref    # MP cross-ref (needs MP_API_KEY)

# Data export + interface
python -m gnome_auditor.export_data      # Generates interface/data.js from SQLite
# Then open interface/index.html in browser (or python -m http.server in interface/)

# Analysis
python -m gnome_auditor.analysis         # Generates plots + calibration_summary.txt
```

---

## Project Overview & Hackathon Context

### What This Is
An independent audit of Google DeepMind's GNoME crystal structure predictions using classical inorganic chemistry rules. GNoME predicted ~520k materials using graph neural networks trained on DFT data. We apply **textbook chemistry checks that are completely independent of the DFT/ML training pipeline** to 3,262 ternary oxygen-containing compounds.

### Hackathon: Anthropic Claude Code Hackathon
- **Deadline: Feb 16, 2025, 3:00 PM EST**
- **Submission: 3-min demo video + GitHub repo + 200-word summary**
- **Problem Statement 3 ("Amplify Human Judgment")** is our best fit: "Build AI that makes researchers dramatically more capable — without taking them out of the loop"
- Also fits Problem Statement 2 ("Break the Barriers") — making crystallographic validation accessible via familiar UI

### Judging Criteria
1. **Impact (25%)** — Real-world potential, who benefits
2. **Opus 4.6 Use (25%)** — Creative, beyond basic integration. **THIS IS OUR CURRENT WEAKNESS — see "Open Problem" below**
3. **Depth & Execution (20%)** — Engineering craft, refined beyond first idea
4. **Demo (30%)** — Working, impressive, genuinely cool to watch

### Special Prizes to Target
- "Most Creative Opus 4.6 Exploration" ($5k) — unexpected capability nobody thought to try
- "The Keep Thinking Prize" ($5k) — likely about extended thinking

---

## Core Design Principles (NON-NEGOTIABLE)

These were established through extensive discussion and critique response. Do NOT violate them:

1. **Ground truth comes from classical chemistry, not AI/ML.** The entire value proposition is that our validators are deterministic, reproducible, and independent of the DFT/ML pipeline. DO NOT use LLMs to write validators or evaluate materials — this would trickle down systematic errors and contradict our independence claim.

2. **Traceable assumptions, not just answers.** Every validation result traces back to specific assumptions (which oxi states were used, what tolerance, what reference data). The user should always be able to see WHY a check produced its result.

3. **Continuous scores, not binary pass/fail.** The `passed` field in the DB is legacy. Always present the continuous `score` with context (e.g., "GII of 0.52 v.u. — ICSD baseline: 0.2 v.u.") rather than "BVS: FAILED."

4. **Coverage is information, not failure.** When a check can't run (missing oxi states, not applicable), that's a data point, not an error. Always report "X of Y materials checked."

5. **18% are not pure oxides** — oxyhalides, oxychalcogenides, etc. Validators assuming O²⁻ may not fully apply. Always flag compound class.

---

## Decision-Making Trajectory

### Phase 1: Pipeline Built (commits 354b8f5, 9eca5ec)
- Ingested 3,262 ternary O-containing compounds from GNoME's ~520k
- Built 6 validators: charge neutrality, Shannon radii, Pauling Rule 2, Goldschmidt, BVS/GII, space group
- Multi-method oxi state assignment with confidence tracking
- MP cross-referencing with synth/not-synth gold data (52,689 + 147,843 ICSD entries)
- SQLite with WAL mode, per-material checkpointing

### Phase 2: External Critique Response (commit d6258a8)
Received 6-point critique, responded as domain expert, implemented 5 fixes:
1. **Pauling CN fix** — changed to count only anion neighbors (Pauling's actual definition). Impact: negligible (~0.001 change in mean score, confirming cation-neighbor contamination was minor)
2. **Shannon pymatgen fallback** — added `Species.ionic_radius` when hand-curated table misses. Impact: recovered 158 more materials (2,571 → 2,729)
3. **CrystalNN caching** — compute neighbor info once per material, share across validators. Impact: ~2x speedup
4. **Compound class warnings** — validators flag when material is not pure_oxide
5. **Claude interface improvements** — continuous scores emphasis, model updated

### Phase 3: Calibration Analysis (commit 597e300)
**Key finding: novel GNoME predictions are statistically indistinguishable from computationally known materials across all validators.** This is a positive signal for GNoME.
- BVS/GII: novel median 0.43 vs known 0.41 (p=0.24, n.s.)
- Pauling: novel mean 0.17 vs known 0.17 (p=0.52, n.s.)
- Compound class effect confirmed: oxyhalides/oxychalcogenides show higher Pauling violations (expected — O²⁻ assumption doesn't hold)
- Oxi confidence correlates monotonically with validation quality

### Phase 4: StackOverBond Interface (commit 54e0b1c)
Built SO-inspired static frontend for the validation data:
- **Concept:** Stack Overflow's Q&A format mapped to materials validation — "question" = material, "answers" = validation checks, "reputation" = tier/independence
- **Inspiration:** Jmail project (Jeffrey Epstein files repackaged in Gmail UI) — take inaccessible data, present in a UI everyone knows
- **Tongue-in-cheek humor:** "Logged in as GNoME (1 rep)", "audited 0.3s ago", speedrunning tagline, parody badges
- **"Interesting Failures"** algorithmically detected across 4 categories:
  - Tier conflict: all Tier 1 pass, Tier 2 fails (e.g., PaMoO4 — GII 2.59 but charge neutral)
  - Suspiciously perfect: novel + all checks ace (e.g., Gd2(CO3)3 — GII 0.03)
  - Identity crisis: oxi methods disagree + cascading failures
  - Geometric strain: charge neutral but extreme GII
- **Confidence anatomy bar:** GitHub-style language bar replacing SO's vote count — each segment = one check, color = result quality

---

## Current State (as of commit 54e0b1c)

### Pipeline Results (Updated)
| Validator | Computed | Coverage | Key Metric |
|-----------|----------|----------|------------|
| Charge Neutrality | 2,787 | 85.4% | Mean residual charge: -1.19 |
| Shannon Radii | 2,729 | 83.7% | Mean violation fraction: 0.005 |
| Pauling Rule 2 | 2,785 | 85.4% | Mean violation fraction: 0.172 |
| Bond Valence Sum | 2,588 | 79.3% | Mean GII: 0.52 v.u. |
| Space Group | 1,857 | 56.9% | 89.7% novel space groups |
| Goldschmidt | 2 | 0.06% | Only 2 ABO3 perovskites |

### Files
```
materials_discovery/
  gnome_auditor/
    cli.py, config.py, pipeline.py       # Core pipeline
    claude_interface.py                   # Tool-calling chat (uses Sonnet, untested)
    export_data.py                        # SQLite → data.js for frontend
    analysis.py                           # Calibration plots + stats
    data/ingest.py, mp_cross_ref.py       # Data loading
    db/schema.py, store.py               # SQLite operations
    validators/                           # 6 validators (base, charge, shannon, pauling, bvs, goldschmidt, space_group)
    gold_data/                            # Synth/not-synth CSVs
  interface/
    index.html                            # StackOverBond frontend (single file, ~1900 lines)
    data.js                               # Generated from SQLite (12 MB, gitignored)
  data/
    auditor_db/gnome_auditor.db          # SQLite database (gitignored)
    analysis_output/                      # Generated plots (gitignored)
```

---

## THE OPEN PROBLEM: Opus 4.6 Integration

### The Tension
Our project's strength (deterministic, classical, independent of AI) is exactly what makes bolting on an LLM feel wrong. The hackathon requires creative Opus 4.6 use (25% of judging), but:

### What Opus CANNOT Be (violates principles)
- **The validator** — contradicts ground truth independence, trickles down systematic errors
- **A chatbot / "Ask an Expert"** — saturated, boring, every hackathon team does this
- **A dashboard narrator / summarizer** — still an LLM wrapper, not transformative

### What We Need
Something that **unlocks a whole new level of experience** — not chat, not wrapper, genuinely transforms how users interact with materials science data. The user explicitly rejected:
1. "Ask an Expert" button (chat wrapper)
2. Dashboard narrator (LLM wrapper)
3. Opus writing validators (violates ground truth principle, trickles systematic errors)

### Possible Directions Still Open
- Something around the "building training data for future AI" thesis
- Something that makes the platform MORE than a data viewer
- Something that demonstrates an unexpected Opus 4.6 capability
- Must respect: Opus doesn't judge/evaluate, classical chemistry IS the ground truth
- Should feel like a genuine innovation, not a feature bolted on

### The Broader Vision
"Stack Overflow for materials science — hoping that one day AI will be trained on the data here, and take over the website" (tongue-in-cheek reference to SO's traffic decline post-AI). The platform should generate structured, traceable data that improves future materials AI.

---

## Interface Design Decisions

### SO → StackOverBond Mapping
| Stack Overflow | StackOverBond |
|----------------|---------------|
| Question | Material (predicted structure) |
| Answer | Validation check result |
| Upvote/downvote | Confidence anatomy bar |
| Accepted answer ✅ | MP experimental confirmation |
| Tags | Compound class + methodology tags |
| User reputation | Check tier (Tier 1 = trusted, Tier 2 = peer review) |
| Hot Network Questions | "Interesting Failures" (4 algorithmic categories) |

### Trolling Elements
- "Logged in as GNoME 🤖" with 1 rep
- "Predicted by GNoME, audited 0.3s ago"
- "Stack Overflow took 15 years to make AI good enough to kill it. We're speedrunning."
- Badges: Trusted Validator, Peer Review, Pioneer, Shapeshifter
- "Building the dataset we wish AI already had™"

### Demo Flow (Planned)
1. **Hook:** Lead with an "Interesting Failure" (PaMoO4 — all Tier 1 pass, Tier 2 fails dramatically)
2. **Show the interface:** SO-familiar layout, confidence bars, traceable assumptions
3. **Opus 4.6 moment:** [TO BE DETERMINED — this is the gap]
4. **Punchline:** "We're building the dataset we wish AI already had"

---

## Regenerating Data

```bash
# If you need to regenerate data.js from the SQLite database:
cd materials_discovery
source .venv/bin/activate
python -m gnome_auditor.export_data  # → interface/data.js

# If you need to rerun the full pipeline (requires pymatgen, ~17 min):
python -m gnome_auditor.cli validate

# If you need to rerun analysis plots:
python -m gnome_auditor.analysis  # → data/analysis_output/
```
