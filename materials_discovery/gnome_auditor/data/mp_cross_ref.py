"""Materials Project API cross-referencing and space group distribution collection.

Queries MP by chemical system (not per material) for efficiency.
Caches responses as JSON for reproducibility.
Collects space group + ICSD data for the space_group validator.
"""

import json
import time
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from gnome_auditor.config import MP_CACHE_DIR
from gnome_auditor.db.store import (
    get_connection, get_all_material_ids, get_material,
    insert_mp_cross_ref, insert_spacegroup_stats_batch,
)


def _get_unique_chemsys(conn) -> list[str]:
    """Get all unique chemical systems from the materials table."""
    rows = conn.execute("""
        SELECT DISTINCT elements FROM materials
    """).fetchall()

    chemsys_set = set()
    for row in rows:
        elements = json.loads(row["elements"])
        chemsys = "-".join(sorted(elements))
        chemsys_set.add(chemsys)

    return sorted(chemsys_set)


def _cache_path(chemsys: str) -> Path:
    return MP_CACHE_DIR / f"{chemsys}.json"


def query_mp_for_chemsys(chemsys: str, api_key: str | None = None) -> list[dict]:
    """Query Materials Project for all entries in a chemical system.

    Returns list of dicts with relevant fields. Results are cached.
    """
    cache_file = _cache_path(chemsys)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    try:
        from mp_api.client import MPRester
        with MPRester(api_key) as mpr:
            docs = mpr.materials.summary.search(
                chemsys=chemsys,
                fields=[
                    "material_id", "formula_pretty", "composition",
                    "symmetry", "formation_energy_per_atom",
                    "is_stable", "database_IDs",
                ],
            )

        results = []
        for doc in docs:
            is_experimental = False
            db_ids = doc.database_IDs if hasattr(doc, "database_IDs") and doc.database_IDs else {}
            icsd_ids = db_ids.get("ICSD", []) if isinstance(db_ids, dict) else []
            if icsd_ids:
                is_experimental = True

            sg_number = None
            sg_symbol = None
            if hasattr(doc, "symmetry") and doc.symmetry:
                sg_number = doc.symmetry.number if hasattr(doc.symmetry, "number") else None
                sg_symbol = doc.symmetry.symbol if hasattr(doc.symmetry, "symbol") else None

            results.append({
                "mp_id": str(doc.material_id),
                "formula": doc.formula_pretty,
                "formation_energy_per_atom": doc.formation_energy_per_atom,
                "is_experimental": is_experimental,
                "icsd_ids": icsd_ids,
                "space_group_number": sg_number,
                "space_group_symbol": sg_symbol,
            })

        cache_file.write_text(json.dumps(results, indent=2))
        return results

    except Exception as e:
        # Cache the error too so we don't retry
        cache_file.write_text(json.dumps({"error": str(e)}))
        return []


def _collect_spacegroup_stats(mp_entries: list[dict]) -> list[dict]:
    """Compute space group frequency distribution from MP entries.

    Only counts experimental entries (those with ICSD IDs).
    """
    sg_counts = Counter()
    for entry in mp_entries:
        if entry.get("is_experimental") and entry.get("space_group_number"):
            sg_counts[entry["space_group_number"]] += 1

    total = sum(sg_counts.values())
    if total == 0:
        return []

    return [
        {
            "space_group_number": sg,
            "count": count,
            "fraction": round(count / total, 4),
        }
        for sg, count in sg_counts.most_common()
    ]


def match_material_to_mp(material_info: dict, mp_entries: list[dict]) -> dict:
    """Match a GNoME material against MP entries for its chemical system.

    Returns match info dict for insertion into mp_cross_ref table.
    """
    formula = material_info["reduced_formula"]

    # Find composition matches
    matches = [e for e in mp_entries if e.get("formula") == formula]

    if not matches:
        return {
            "mp_id": None,
            "match_type": "novel",
            "mp_is_experimental": None,
            "mp_formation_energy": None,
            "mp_space_group": None,
        }

    # Prefer experimental matches
    exp_matches = [m for m in matches if m.get("is_experimental")]
    if exp_matches:
        best = exp_matches[0]
        # Check if space groups match
        gnome_sg = material_info.get("space_group_number")
        mp_sg = best.get("space_group_number")
        if gnome_sg and mp_sg and gnome_sg != mp_sg:
            match_type = "structural_mismatch"
        else:
            match_type = "experimental_match"
        return {
            "mp_id": best["mp_id"],
            "match_type": match_type,
            "mp_is_experimental": True,
            "mp_formation_energy": best.get("formation_energy_per_atom"),
            "mp_space_group": best.get("space_group_symbol"),
        }

    # Only computational matches
    best = matches[0]
    gnome_sg = material_info.get("space_group_number")
    mp_sg = best.get("space_group_number")
    if gnome_sg and mp_sg and gnome_sg != mp_sg:
        match_type = "structural_mismatch"
    else:
        match_type = "computational_match"
    return {
        "mp_id": best["mp_id"],
        "match_type": match_type,
        "mp_is_experimental": False,
        "mp_formation_energy": best.get("formation_energy_per_atom"),
        "mp_space_group": best.get("space_group_symbol"),
    }


def run_mp_cross_reference(api_key: str | None = None):
    """Run full MP cross-referencing for all materials.

    1. Get unique chemical systems
    2. Query MP for each (with caching)
    3. Collect space group stats
    4. Match each material to MP entries
    """
    conn = get_connection()
    chemsys_list = _get_unique_chemsys(conn)
    print(f"Found {len(chemsys_list)} unique chemical systems")

    # Query MP for each chemical system
    mp_data = {}  # chemsys → list of MP entries
    for chemsys in tqdm(chemsys_list, desc="Querying MP"):
        entries = query_mp_for_chemsys(chemsys, api_key)
        if isinstance(entries, dict) and "error" in entries:
            continue
        mp_data[chemsys] = entries

        # Collect and store space group stats
        sg_stats = _collect_spacegroup_stats(entries)
        if sg_stats:
            insert_spacegroup_stats_batch(conn, chemsys, sg_stats)

        time.sleep(0.05)  # gentle rate limiting

    # Match each material
    material_ids = get_all_material_ids(conn)
    n_matched = 0
    for mat_id in tqdm(material_ids, desc="Matching materials"):
        mat = get_material(conn, mat_id)
        if mat is None:
            continue

        elements = mat["elements"]
        chemsys = "-".join(sorted(elements))
        entries = mp_data.get(chemsys, [])

        match_data = match_material_to_mp(mat, entries)
        insert_mp_cross_ref(conn, mat_id, match_data)
        if match_data["match_type"] != "novel":
            n_matched += 1

    conn.commit()
    conn.close()

    print(f"MP cross-referencing complete: {n_matched}/{len(material_ids)} matched")
