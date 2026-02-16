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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

from gnome_auditor.config import DB_PATH, DATA_DIR
from gnome_auditor.export_data import get_conn, export_materials, find_interesting_failures, compute_aggregate_stats

OUTPUT_PATH = DATA_DIR / "opus_questions.json"
CHECKPOINT_PATH = DATA_DIR / "opus_questions_checkpoint.json"

SYSTEM_PROMPT = """\
You are a materials scientist and ML researcher auditing GNoME crystal predictions \
using classical chemistry rules independent of the DFT/ML pipeline.

Generate exactly ONE research question. Keep it concise (a few sentences, not a \
giant paragraph). Self-contained with key numbers. Expert chemical insight, not statistics.

## What makes a GREAT question:
- References related materials in the same chemical system to identify PATTERNS \
("3 of 13 U-Pa-O compounds show GII>2.8, all Pa-rich — is Pa5+ poorly parameterized?")
- Proposes a specific testable hypothesis with the alternative worked out
- Connects to known chemistry or structural archetypes
- Challenges whether the validation method itself is appropriate for this material

## BAD questions (DO NOT write):
- "How can Tier 1 pass while Tier 2 fails?" — obvious
- "This is at the Xth percentile" — statistics without chemistry
- "Should this be synthesized?" — outside scope
- Generic "could the oxi state be wrong?" without proposing the specific alternative

## For CLEAN materials (all checks pass, low BVS):
Hypothesize WHY — easy chemistry? known structural archetype? over-optimized \
relaxation? Or note an anomaly hidden in the clean profile (e.g., space group mismatch).

## Categories:
- `hypothesis` — A testable claim about chemistry, structure, or prediction quality
- `methodology` — Whether our validation tools are adequate/misleading for this material
- `anomaly` — Something genuinely unexpected demanding explanation

Return JSON array with exactly 1 question: [{"category":"...","question_text":"...","priority":1}]
Return ONLY JSON."""


def build_material_prompt(mat, aggregate_stats, family=None):
    """Build per-material prompt with full validation profile and dataset context.

    family: list of sibling materials in the same chemical system (chemsys).
    """
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

    # Related materials in same chemical system
    if family and len(family) > 1:
        siblings = [m for m in family if m["material_id"] != mat_id]
        if siblings:
            lines.append("")
            lines.append(f"## Related Materials ({len(siblings)} other predictions in same chemical system)")
            for sib in siblings[:8]:
                sib_checks = sib.get("checks", {})
                bvs = sib_checks.get("bond_valence_sum", {})
                cn = sib_checks.get("charge_neutrality", {})
                gii = bvs.get("score", "N/A") if bvs.get("status") == "completed" else "N/A"
                charge = cn.get("score", "N/A") if cn.get("status") == "completed" else "N/A"
                lines.append(
                    f"- {sib.get('reduced_formula', '?'):18s} "
                    f"SG={sib.get('space_group', '?'):10s} "
                    f"GII={gii!s:8s} charge={charge!s:8s} "
                    f"match={sib.get('match_type', '?')}"
                )

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
    elif subset == "half":
        # Smart 50%+ selection: all materials with >= 3 checks, sorted by
        # most validation data first, then by most anomalous scores
        mats = [m for m in materials if m.get("n_completed", 0) >= 3]
        def sort_key(m):
            # Prioritize: more checks first, then more anomalous BVS
            n = m.get("n_completed", 0)
            bvs = m.get("checks", {}).get("bond_valence_sum", {})
            gii = abs(bvs.get("score", 0)) if bvs.get("status") == "completed" else 0
            return (-n, -gii)
        mats.sort(key=sort_key)
    else:  # all
        mats = [m for m in materials if m.get("n_completed", 0) >= 1]

    if max_count:
        mats = mats[:max_count]

    return mats


def generate_questions(subset="interesting", max_count=None, fresh=False, timeout_min=None):
    """Main entry: generate Opus questions for materials."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    start_time = time.time()
    deadline = start_time + timeout_min * 60 if timeout_min else None

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

    # Build chemsys family map for cross-material context
    print("Building chemical system families...")
    chemsys_lookup = {}
    try:
        conn2 = get_conn()
        for row in conn2.execute("SELECT material_id, chemsys FROM mp_cross_ref"):
            chemsys_lookup[row[0]] = row[1]
        conn2.close()
    except Exception:
        pass  # Fall back to no family data
    mat_by_id = {m["material_id"]: m for m in materials}
    family_map = {}  # material_id -> list of family members
    chemsys_groups = {}
    for mid, cs in chemsys_lookup.items():
        chemsys_groups.setdefault(cs, []).append(mid)
    for mid, cs in chemsys_lookup.items():
        siblings = chemsys_groups.get(cs, [])
        if len(siblings) > 1:
            family_map[mid] = [mat_by_id[s] for s in siblings if s in mat_by_id]
    print(f"  {len(family_map)} materials have family context")

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

    if deadline:
        elapsed = time.time() - start_time
        remaining_min = (deadline - time.time()) / 60
        print(f"  Timeout: {timeout_min} min ({remaining_min:.0f} min remaining after setup)")

    # Process each material
    total = len(to_process)
    stopped_early = False
    for i, mat in enumerate(to_process):
        # Check timeout before starting next material
        if deadline and time.time() >= deadline:
            print(f"\n  Timeout reached ({timeout_min} min). Stopping gracefully.")
            stopped_early = True
            break

        mat_id = mat["material_id"]
        formula = mat.get("reduced_formula", "?")
        print(f"  [{i+1}/{total}] {formula} ({mat_id})...", end=" ", flush=True)

        family = family_map.get(mat_id)
        prompt = build_material_prompt(mat, aggregate_stats, family=family)

        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=768,
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
            elapsed_min = (time.time() - start_time) / 60
            rate = (i + 1) / elapsed_min if elapsed_min > 0 else 0
            print(f"  [Checkpoint: {len(results)} materials | {elapsed_min:.1f} min | {rate:.1f}/min]")

        # Rate limiting
        time.sleep(0.5)

    # Save final
    save_checkpoint(results)  # Always save checkpoint for resume
    save_final(results)

    # Summary
    elapsed_min = (time.time() - start_time) / 60
    total_questions = sum(len(r.get("questions", [])) for r in results.values())
    errors = sum(1 for r in results.values() if r.get("error"))
    print(f"\n{'Paused' if stopped_early else 'Done'}! "
          f"{total_questions} questions across {len(results)} materials "
          f"({errors} errors) in {elapsed_min:.1f} min")
    if stopped_early:
        remaining = total - (i)
        print(f"  {remaining} materials remaining — run again without --fresh to resume")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Opus research questions for GNoME materials"
    )
    parser.add_argument(
        "--subset", choices=["interesting", "novel", "half", "all"], default="half",
        help="Which materials to process (default: half — ~1700 with most data)",
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help="Maximum number of materials to process",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore checkpoint and start fresh",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Stop after N minutes (saves checkpoint for resume)",
    )
    args = parser.parse_args()
    generate_questions(subset=args.subset, max_count=args.max, fresh=args.fresh,
                       timeout_min=args.timeout)


if __name__ == "__main__":
    main()
