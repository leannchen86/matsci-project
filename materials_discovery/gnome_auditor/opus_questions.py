"""Generate research questions for materials using Claude Opus.

Opus reads validation profiles and generates *research questions* — not answers,
not claims. Questions the data is asking, categorized by type.

Usage:
    cd materials_discovery
    export ANTHROPIC_API_KEY='...'
    python -m gnome_auditor.opus_questions --subset interesting
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import anthropic

from gnome_auditor.config import DB_PATH, DATA_DIR
from gnome_auditor.export_data import get_conn, export_materials, find_interesting_failures, compute_aggregate_stats

OUTPUT_PATH = DATA_DIR / "opus_questions.json"
CHECKPOINT_PATH = DATA_DIR / "opus_questions_checkpoint.json"

SYSTEM_PROMPT = """\
You are a materials science research assistant examining validation data from an \
independent audit of Google DeepMind's GNoME crystal structure predictions.

Your job is to generate RESEARCH QUESTIONS — not answers, not claims, not judgments.

## Rules

1. **Questions only.** Never say a structure is "stable", "unstable", "correct", or "wrong".
2. **Cite evidence.** Every question must reference specific numbers from the validation data.
3. **Be specific.** "Why is the GII so high?" is bad. "Why does this material show GII = 2.59 v.u. \
(12x the ICSD baseline) despite perfect charge neutrality?" is good.
4. **Use dataset context.** Reference the aggregate statistics provided to explain what makes this \
material unusual compared to the dataset.
5. **4 categories:**
   - `anomaly` — Something unexpected in this material's validation profile
   - `cross_validator` — Tension or agreement between different checks worth investigating
   - `dataset_context` — How this material compares to dataset-wide patterns
   - `oxi_state` — Questions about oxidation state assignment and its downstream effects

## Output format

Return a JSON array of 1-4 questions:
```json
[
  {
    "category": "anomaly",
    "question_text": "The specific research question",
    "evidence": "Key numbers/facts that motivate this question",
    "priority": 1
  }
]
```

priority: 1 = most interesting, 2 = notable, 3 = minor observation.

Return ONLY the JSON array — no other text."""


def build_material_prompt(mat, aggregate_stats):
    """Build per-material prompt with full validation profile and dataset context."""
    checks = mat.get("checks", {})
    formula = mat.get("reduced_formula", "?")
    mat_id = mat.get("material_id", "?")

    lines = [
        f"## Material: {formula} (ID: {mat_id})",
        f"- Compound class: {mat.get('compound_class', '?')}",
        f"- Crystal system: {mat.get('crystal_system', '?')}, Space group: {mat.get('space_group', '?')} (#{mat.get('space_group_number', '?')})",
        f"- Sites: {mat.get('n_sites', '?')}",
        f"- Formation energy: {mat.get('formation_energy_per_atom', '?')} eV/atom",
        f"- Band gap: {mat.get('bandgap', '?')} eV",
        f"- MP status: {mat.get('match_type', '?')}",
        f"- Oxi method: {mat.get('oxi_method', '?')}, Confidence: {mat.get('oxi_confidence', '?')}",
        f"- Mixed valence: {mat.get('has_mixed_valence', False)}",
        "",
        "## Validation Results",
    ]

    check_order = ["charge_neutrality", "shannon_radii", "pauling_rule2", "bond_valence_sum", "space_group"]
    for cn in check_order:
        c = checks.get(cn, {})
        status = c.get("status", "not_run")
        if status == "completed":
            score = c.get("score")
            details = c.get("details", {})
            tier = c.get("tier", "?")
            lines.append(f"- **{cn}** (Tier {tier}): score = {score}")
            # Add key details
            if cn == "bond_valence_sum" and isinstance(details, dict):
                worst = details.get("worst_sites", [])
                if worst:
                    sites_str = "; ".join(
                        f"{ws.get('element', '?')} site {ws.get('site_index', '?')}: "
                        f"BVS={ws.get('bvs', '?')}, expected={ws.get('expected', '?')}, "
                        f"deviation={ws.get('relative_deviation', '?')}"
                        for ws in worst[:3]
                    )
                    lines.append(f"  Worst sites: {sites_str}")
            if cn == "charge_neutrality" and isinstance(details, dict):
                lines.append(f"  Total charge: {details.get('total_charge', '?')}")
            if cn == "pauling_rule2" and isinstance(details, dict):
                n_checked = details.get("n_oxygen_sites_checked", "?")
                n_violated = details.get("n_violated", "?")
                lines.append(f"  O sites checked: {n_checked}, violated: {n_violated}")
                warn = details.get("compound_class_warning")
                if warn:
                    lines.append(f"  Warning: {warn}")
            if cn == "shannon_radii" and isinstance(details, dict):
                n_bonds = details.get("n_bonds_checked", "?")
                lines.append(f"  Bonds checked: {n_bonds}")
            if cn == "space_group" and isinstance(details, dict):
                top_sgs = details.get("top_experimental_space_groups", [])
                if top_sgs:
                    sg_str = ", ".join(
                        f"#{sg.get('space_group_number', '?')} ({sg.get('fraction', 0)*100:.0f}%)"
                        for sg in top_sgs[:3]
                    )
                    lines.append(f"  Top experimental SGs: {sg_str}")
        else:
            reason = ""
            if isinstance(c.get("details"), dict):
                reason = c["details"].get("skip_reason", "")
            lines.append(f"- **{cn}**: {status}" + (f" ({reason})" if reason else ""))

    # Dataset context
    lines.append("")
    lines.append("## Dataset Context (3,262 ternary O-containing compounds)")
    cs = aggregate_stats.get("check_stats", {})
    for cn in ["bond_valence_sum", "charge_neutrality", "pauling_rule2", "shannon_radii"]:
        s = cs.get(cn, {})
        if s.get("mean") is not None:
            lines.append(
                f"- {cn}: mean={s['mean']}, median={s['median']}, "
                f"P25={s['p25']}, P75={s['p75']} (n={s['n_completed']})"
            )

    mt = aggregate_stats.get("match_types", {})
    lines.append(f"- Match types: novel={mt.get('novel', 0)}, "
                 f"comp_known={mt.get('computationally_known', 0)}, "
                 f"exp_known={mt.get('experimentally_known', 0)}")

    return "\n".join(lines)


def parse_opus_response(text):
    """Parse JSON array from Opus response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        # Remove markdown fences
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    questions = json.loads(text)
    if not isinstance(questions, list):
        raise ValueError("Expected JSON array")

    valid = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if "question_text" not in q or "category" not in q:
            continue
        valid.append({
            "category": q.get("category", "anomaly"),
            "question_text": q["question_text"],
            "evidence": q.get("evidence", ""),
            "priority": q.get("priority", 2),
        })
    return valid


def load_checkpoint():
    """Load checkpoint if it exists."""
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {}


def save_checkpoint(results):
    """Save results as checkpoint."""
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(results, f, indent=2)


def save_final(results):
    """Save final results."""
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {len(results)} material question sets to {OUTPUT_PATH}")


def get_interesting_material_ids(materials):
    """Get material IDs from interesting failures categories."""
    interesting = find_interesting_failures(materials)
    ids = set()
    for cat in interesting.values():
        for item in cat.get("items", []):
            ids.add(item["material_id"])
    return ids


def get_subset_materials(materials, subset, max_count=None):
    """Filter materials by subset."""
    if subset == "interesting":
        target_ids = get_interesting_material_ids(materials)
        mats = [m for m in materials if m["material_id"] in target_ids]
    elif subset == "novel":
        mats = [m for m in materials
                if m.get("match_type") == "novel" and m.get("n_completed", 0) >= 3]
    else:  # all
        mats = [m for m in materials if m.get("n_completed", 0) >= 1]

    if max_count:
        mats = mats[:max_count]

    return mats


def generate_questions(subset="interesting", max_count=None, fresh=False):
    """Main entry: generate Opus questions for materials."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Load data — try SQLite first, fall back to data.js
    materials = None
    try:
        conn = get_conn()
        print("Loading materials from SQLite...")
        materials = export_materials(conn)
        conn.close()
        if not materials:
            materials = None
    except Exception as e:
        print(f"  SQLite unavailable: {e}")

    if not materials:
        data_js_path = Path(__file__).parent.parent / "interface" / "data.js"
        if data_js_path.exists():
            print(f"Falling back to data.js...")
            raw = data_js_path.read_text()
            # Strip "const DATA = " prefix and ";\n" suffix
            json_str = raw[len("const DATA = "):-2]
            data = json.loads(json_str)
            # Merge materials list with details for full validation data
            details = data.get("details", {})
            materials = []
            for mat in data.get("materials", []):
                mat_id = mat["material_id"]
                det = details.get(mat_id, {})
                mat["checks"] = det.get("checks", mat.get("checks", {}))
                mat["oxi_states"] = det.get("oxi_states")
                mat["mixed_valence_elements"] = det.get("mixed_valence_elements")
                materials.append(mat)
            print(f"  {len(materials)} materials loaded from data.js")
        else:
            print("Error: No SQLite database and no data.js found.")
            sys.exit(1)
    else:
        print(f"  {len(materials)} materials loaded")

    print("Computing aggregate stats...")
    aggregate_stats = compute_aggregate_stats(materials)

    # Select subset
    subset_mats = get_subset_materials(materials, subset, max_count)
    print(f"  Subset '{subset}': {len(subset_mats)} materials to process")

    if not subset_mats:
        print("No materials to process.")
        return

    # Load checkpoint
    results = {} if fresh else load_checkpoint()
    already_done = set(results.keys())
    to_process = [m for m in subset_mats if m["material_id"] not in already_done]

    if already_done:
        print(f"  Resuming: {len(already_done)} already done, {len(to_process)} remaining")

    # Process each material
    total = len(to_process)
    for i, mat in enumerate(to_process):
        mat_id = mat["material_id"]
        formula = mat.get("reduced_formula", "?")
        print(f"  [{i+1}/{total}] {formula} ({mat_id})...", end=" ", flush=True)

        prompt = build_material_prompt(mat, aggregate_stats)

        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text
            questions = parse_opus_response(text)
            results[mat_id] = {
                "material_id": mat_id,
                "reduced_formula": formula,
                "questions": questions,
            }
            print(f"{len(questions)} questions")

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            results[mat_id] = {
                "material_id": mat_id,
                "reduced_formula": formula,
                "questions": [],
                "error": f"JSON parse error: {e}",
            }
        except Exception as e:
            print(f"API error: {e}")
            results[mat_id] = {
                "material_id": mat_id,
                "reduced_formula": formula,
                "questions": [],
                "error": str(e),
            }

        # Checkpoint every 10 materials
        if (i + 1) % 10 == 0:
            save_checkpoint(results)
            print(f"  [Checkpoint saved: {len(results)} materials]")

        # Rate limiting
        time.sleep(1.0)

    # Save final
    save_final(results)

    # Summary
    total_questions = sum(len(r.get("questions", [])) for r in results.values())
    errors = sum(1 for r in results.values() if r.get("error"))
    print(f"\nDone! {total_questions} questions across {len(results)} materials ({errors} errors)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Opus research questions for GNoME materials"
    )
    parser.add_argument(
        "--subset", choices=["interesting", "novel", "all"], default="interesting",
        help="Which materials to process (default: interesting ~30 materials)",
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help="Maximum number of materials to process",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore checkpoint and start fresh",
    )
    args = parser.parse_args()
    generate_questions(subset=args.subset, max_count=args.max, fresh=args.fresh)


if __name__ == "__main__":
    main()
