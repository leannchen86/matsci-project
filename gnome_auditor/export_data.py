"""
Export SQLite data to a JS file for the Curious Materials frontend.

Usage:
    cd materials_discovery
    python -m gnome_auditor.export_data
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

from gnome_auditor.config import DB_PATH

OUTPUT_DIR = Path(__file__).parent.parent / "interface"


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def export_materials(conn):
    """Export all materials with validation results, oxi assignments, and MP cross-ref."""
    materials = []

    rows = conn.execute("""
        SELECT m.*,
               oa.method_used AS oxi_method,
               oa.confidence AS oxi_confidence,
               oa.oxi_states,
               oa.has_mixed_valence,
               oa.mixed_valence_elements,
               mc.match_type,
               mc.synth_status,
               mc.best_match_mp_id,
               mc.mp_formula,
               mc.mp_space_group
        FROM materials m
        LEFT JOIN oxidation_state_assignments oa ON m.material_id = oa.material_id
        LEFT JOIN mp_cross_ref mc ON m.material_id = mc.material_id
    """).fetchall()

    for row in rows:
        mat = dict(row)

        # Parse JSON fields
        for field in ("elements", "oxi_states", "mixed_valence_elements"):
            if mat.get(field) and isinstance(mat[field], str):
                try:
                    mat[field] = json.loads(mat[field])
                except (json.JSONDecodeError, TypeError):
                    pass

        # Get validation results
        checks = {}
        for vr in conn.execute("""
            SELECT check_name, tier, independence, status, passed,
                   confidence, score, details
            FROM validation_results
            WHERE material_id = ?
            ORDER BY tier, check_name
        """, (mat["material_id"],)):
            vr_dict = dict(vr)
            if vr_dict["details"]:
                try:
                    vr_dict["details"] = json.loads(vr_dict["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            checks[vr_dict["check_name"]] = vr_dict
        mat["checks"] = checks
        mat["n_completed"] = sum(
            1 for c in checks.values() if c["status"] == "completed"
        )

        materials.append(mat)

    return materials


def find_interesting_failures(materials):
    """Algorithmically select materials with interesting validation profiles."""
    categories = {
        "tier_conflict": {
            "label": "Chemically valid, geometrically unstable",
            "description": "All Tier 1 (DFT-independent) checks pass, but Tier 2 (BVS) shows high geometric instability",
            "items": [],
        },
        "suspiciously_perfect": {
            "label": "All checks pass, novel prediction",
            "description": "Novel material with near-ideal scores across all validators",
            "items": [],
        },
        "identity_crisis": {
            "label": "Oxidation state disagreement",
            "description": "Oxidation state methods disagree, causing inconsistent downstream results",
            "items": [],
        },
        "geometric_strain": {
            "label": "Geometrically strained but chemically valid",
            "description": "Charge neutral with high GII — bond lengths are off but the chemistry adds up",
            "items": [],
        },
    }

    for mat in materials:
        checks = mat.get("checks", {})
        bvs = checks.get("bond_valence_sum", {})
        cn = checks.get("charge_neutrality", {})
        pauling = checks.get("pauling_rule2", {})
        shannon = checks.get("shannon_radii", {})

        bvs_ok = bvs.get("status") == "completed"
        cn_ok = cn.get("status") == "completed"
        paul_ok = pauling.get("status") == "completed"
        shan_ok = shannon.get("status") == "completed"

        gii = bvs.get("score", 999) if bvs_ok else None
        charge = cn.get("score", 999) if cn_ok else None
        paul_score = pauling.get("score", 999) if paul_ok else None
        shan_score = shannon.get("score", 999) if shan_ok else None

        entry = {
            "material_id": mat["material_id"],
            "reduced_formula": mat["reduced_formula"],
            "compound_class": mat.get("compound_class"),
            "match_type": mat.get("match_type"),
            "gii": gii,
            "charge": charge,
            "pauling": paul_score,
            "shannon": shan_score,
        }

        # Tier conflict: Tier 1 all pass, Tier 2 fails
        if (bvs_ok and cn_ok and paul_ok and shan_ok
                and charge == 0.0 and paul_score == 0.0 and shan_score == 0.0
                and gii is not None and gii > 1.5
                and mat.get("match_type") == "novel"):
            entry["_sort"] = -gii
            categories["tier_conflict"]["items"].append(entry)

        # Suspiciously perfect: novel, all pass, low GII
        if (bvs_ok and cn_ok and paul_ok and shan_ok
                and charge == 0.0 and paul_score == 0.0 and shan_score == 0.0
                and gii is not None and gii < 0.15
                and mat.get("match_type") == "novel"
                and mat.get("oxi_confidence") == "both_agree"):
            entry["_sort"] = gii
            categories["suspiciously_perfect"]["items"].append(entry)

        # Identity crisis: methods disagree + large charge residual
        if (mat.get("oxi_confidence") == "methods_disagree"
                and cn_ok and charge is not None and abs(charge) > 4):
            entry["_sort"] = -abs(charge)
            categories["identity_crisis"]["items"].append(entry)

        # Geometric strain: charge neutral but high GII
        if (bvs_ok and cn_ok
                and charge == 0.0 and gii is not None and gii > 1.0
                and mat.get("match_type") == "novel"):
            entry["_sort"] = -gii
            categories["geometric_strain"]["items"].append(entry)

    # Sort and limit each category
    for cat in categories.values():
        cat["items"].sort(key=lambda x: x.get("_sort", 0))
        cat["items"] = cat["items"][:8]
        for item in cat["items"]:
            item.pop("_sort", None)
        cat["count"] = len(cat["items"])

    return categories


def compute_aggregate_stats(materials):
    """Compute dashboard-level aggregate statistics."""
    total = len(materials)

    # Compound class distribution
    compound_classes = {}
    for m in materials:
        cc = m.get("compound_class", "unknown")
        compound_classes[cc] = compound_classes.get(cc, 0) + 1

    # Match type distribution
    match_types = {}
    for m in materials:
        mt = m.get("match_type", "unknown")
        match_types[mt] = match_types.get(mt, 0) + 1

    # Oxi confidence distribution
    oxi_conf = {}
    for m in materials:
        oc = m.get("oxi_confidence", "unknown")
        oxi_conf[oc] = oxi_conf.get(oc, 0) + 1

    # Crystal system distribution
    crystal_systems = {}
    for m in materials:
        cs = m.get("crystal_system", "unknown")
        crystal_systems[cs] = crystal_systems.get(cs, 0) + 1

    # Per-check score distributions
    check_stats = {}
    check_names = [
        "bond_valence_sum", "charge_neutrality", "pauling_rule2",
        "shannon_radii", "space_group",
    ]
    for cn in check_names:
        scores = []
        n_completed = 0
        n_skipped = 0
        for m in materials:
            c = m.get("checks", {}).get(cn, {})
            if c.get("status") == "completed":
                n_completed += 1
                if c.get("score") is not None:
                    scores.append(c["score"])
            elif c.get("status", "").startswith("skipped"):
                n_skipped += 1

        scores.sort()
        n = len(scores)

        # Pre-bin scores for histograms (avoids shipping raw arrays)
        if cn == "charge_neutrality":
            bin_edges = list(range(-28, 28, 2))
        elif cn == "bond_valence_sum":
            bin_edges = [i * 0.1 for i in range(0, 81)]
        else:
            bin_edges = [i * 0.05 for i in range(0, 22)]
        hist_counts = [0] * (len(bin_edges) - 1)
        for s in scores:
            for bi in range(len(bin_edges) - 1):
                if bin_edges[bi] <= s < bin_edges[bi + 1]:
                    hist_counts[bi] += 1
                    break
            else:
                if s >= bin_edges[-1]:
                    hist_counts[-1] += 1

        check_stats[cn] = {
            "n_completed": n_completed,
            "n_skipped": n_skipped,
            "hist_bins": bin_edges,
            "hist_counts": hist_counts,
            "mean": round(sum(scores) / n, 4) if n > 0 else None,
            "median": round(scores[n // 2], 4) if n > 0 else None,
            "p25": round(scores[n // 4], 4) if n > 0 else None,
            "p75": round(scores[3 * n // 4], 4) if n > 0 else None,
        }

    # Completion counts
    completion_dist = {}
    for m in materials:
        nc = m.get("n_completed", 0)
        completion_dist[nc] = completion_dist.get(nc, 0) + 1

    return {
        "total": total,
        "compound_classes": compound_classes,
        "match_types": match_types,
        "oxi_confidence": oxi_conf,
        "crystal_systems": crystal_systems,
        "check_stats": check_stats,
        "completion_dist": completion_dist,
    }


def inject_opus_questions():
    """Inject opus questions into an existing data.js without needing SQLite."""
    output_path = OUTPUT_DIR / "data.js"
    if not output_path.exists():
        print("Error: data.js not found. Run full export first.")
        return False

    opus_questions_path = Path(__file__).parent.parent / "data" / "opus_questions.json"
    if not opus_questions_path.exists():
        print("Error: opus_questions.json not found. Run: python -m gnome_auditor.opus_questions")
        return False

    print(f"Reading existing data.js ({output_path.stat().st_size / 1024 / 1024:.1f} MB)...")
    raw = output_path.read_text()
    json_str = raw[len("const DATA = "):-2]
    data = json.loads(json_str)

    # Load opus questions
    with open(opus_questions_path) as f:
        raw_questions = json.load(f)
    opus_questions = {}
    for mat_id, entry in raw_questions.items():
        if entry.get("questions"):
            opus_questions[mat_id] = entry["questions"]

    data["opus_questions"] = opus_questions
    data["meta"]["opus_questions_count"] = len(opus_questions)
    print(f"  Injected questions for {len(opus_questions)} materials")

    print(f"Writing {output_path}...")
    with open(output_path, "w") as f:
        f.write("const DATA = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";\n")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {size_mb:.1f} MB written")
    return True


def run_export():
    conn = get_conn()
    print("Exporting materials...")
    materials = export_materials(conn)
    print(f"  {len(materials)} materials loaded")

    print("Finding interesting failures...")
    interesting = find_interesting_failures(materials)
    for cat_key, cat in interesting.items():
        print(f"  {cat_key}: {cat['count']} items")

    print("Computing aggregate stats...")
    stats = compute_aggregate_stats(materials)

    # Strip full score arrays from materials (keep in stats only for charts)
    # Also strip heavy details from list-level data — keep details accessible by ID
    material_details = {}
    material_list = []
    for mat in materials:
        mat_id = mat["material_id"]
        # Full details stored separately — slim down heavy per-site arrays
        slim_checks = {}
        for cn, cv in mat.get("checks", {}).items():
            slim_cv = dict(cv)
            det = slim_cv.get("details")
            if isinstance(det, dict):
                slim_det = dict(det)
                # Keep only top 3 worst sites/violations for the UI
                for key in ("worst_sites", "worst_violations"):
                    if key in slim_det and isinstance(slim_det[key], list):
                        slim_det[key] = slim_det[key][:3]
                # Keep space group top entries limited
                if "top_experimental_space_groups" in slim_det:
                    slim_det["top_experimental_space_groups"] = \
                        slim_det["top_experimental_space_groups"][:5]
                slim_cv["details"] = slim_det
            slim_checks[cn] = slim_cv
        material_details[mat_id] = {
            "checks": slim_checks,
            "oxi_states": mat.get("oxi_states"),
            "mixed_valence_elements": mat.get("mixed_valence_elements"),
        }
        # Light summary for list view
        check_summary = {}
        for cn, cv in mat.get("checks", {}).items():
            check_summary[cn] = {
                "status": cv.get("status"),
                "score": cv.get("score"),
                "tier": cv.get("tier"),
                "confidence": cv.get("confidence"),
            }
        material_list.append({
            "material_id": mat_id,
            "reduced_formula": mat.get("reduced_formula"),
            "composition": mat.get("composition"),
            "elements": mat.get("elements"),
            "n_sites": mat.get("n_sites"),
            "space_group": mat.get("space_group"),
            "space_group_number": mat.get("space_group_number"),
            "crystal_system": mat.get("crystal_system"),
            "compound_class": mat.get("compound_class"),
            "oxide_type": mat.get("oxide_type"),
            "formation_energy_per_atom": mat.get("formation_energy_per_atom"),
            "bandgap": mat.get("bandgap"),
            "match_type": mat.get("match_type"),
            "synth_status": mat.get("synth_status"),
            "best_match_mp_id": mat.get("best_match_mp_id"),
            "oxi_method": mat.get("oxi_method"),
            "oxi_confidence": mat.get("oxi_confidence"),
            "has_mixed_valence": mat.get("has_mixed_valence"),
            "n_completed": mat.get("n_completed"),
            "checks": check_summary,
        })

    # Load Opus questions if available
    opus_questions = {}
    opus_questions_path = Path(__file__).parent.parent / "data" / "opus_questions.json"
    if opus_questions_path.exists():
        with open(opus_questions_path) as f:
            raw = json.load(f)
        for mat_id, entry in raw.items():
            if entry.get("questions"):
                opus_questions[mat_id] = entry["questions"]
        print(f"  Loaded Opus questions for {len(opus_questions)} materials")
    else:
        print("  No opus_questions.json found (run: python -m gnome_auditor.opus_questions)")

    output = {
        "materials": material_list,
        "details": material_details,
        "interesting_failures": interesting,
        "stats": stats,
        "opus_questions": opus_questions,
        "meta": {
            "total_materials": len(materials),
            "export_timestamp": datetime.now().isoformat(),
            "platform": "Curious Materials",
            "opus_questions_count": len(opus_questions),
        },
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "data.js"
    print(f"Writing {output_path}...")
    with open(output_path, "w") as f:
        f.write("const DATA = ")
        json.dump(output, f, separators=(",", ":"))
        f.write(";\n")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {size_mb:.1f} MB written")

    conn.close()
    print("Export complete!")


if __name__ == "__main__":
    import sys
    if "--inject-opus" in sys.argv:
        inject_opus_questions()
    else:
        run_export()
