"""Materials Project API cross-referencing with synth/not-synth gold data.

Queries MP by chemical system (not per material) for efficiency.
Caches responses as JSON for reproducibility.
Integrates expert-curated synth/not-synth labels from ICSD cross-reference.
"""

import json
import time
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from gnome_auditor.config import MP_CACHE_DIR, SYNTH_CSV, NOT_SYNTH_CSV
from gnome_auditor.db.store import (
    get_connection, get_all_material_ids, get_material,
    insert_mp_cross_ref, insert_spacegroup_stats_batch,
)


def _load_gold_data() -> tuple[set, set]:
    """Load synth/not-synth MP ID sets from gold data files."""
    synth_ids = set()
    not_synth_ids = set()
    with open(SYNTH_CSV) as f:
        for line in f:
            line = line.strip()
            if line and line != "filename":
                synth_ids.add(line)
    with open(NOT_SYNTH_CSV) as f:
        for line in f:
            line = line.strip()
            if line and line != "filename":
                not_synth_ids.add(line)
    return synth_ids, not_synth_ids


def _get_unique_chemsys(conn) -> list[str]:
    """Get all unique chemical systems from the materials table."""
    rows = conn.execute("SELECT DISTINCT elements FROM materials").fetchall()
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
        data = json.loads(cache_file.read_text())
        if isinstance(data, list):
            return data
        return []  # cached error

    try:
        from mp_api.client import MPRester
        with MPRester(api_key) as mpr:
            docs = mpr.materials.summary.search(
                chemsys=chemsys,
                fields=[
                    "material_id", "formula_pretty",
                    "symmetry", "formation_energy_per_atom",
                    "is_stable", "theoretical",
                ],
            )

        results = []
        for doc in docs:
            sg_number = None
            sg_symbol = None
            if hasattr(doc, "symmetry") and doc.symmetry:
                sg_number = getattr(doc.symmetry, "number", None)
                sg_symbol = getattr(doc.symmetry, "symbol", None)

            results.append({
                "mp_id": str(doc.material_id),
                "formula": doc.formula_pretty,
                "formation_energy_per_atom": doc.formation_energy_per_atom,
                "is_stable": doc.is_stable,
                "theoretical": doc.theoretical,
                "space_group_number": sg_number,
                "space_group_symbol": sg_symbol,
            })

        cache_file.write_text(json.dumps(results, indent=2))
        return results

    except Exception as e:
        cache_file.write_text(json.dumps({"error": str(e)}))
        return []


def _collect_spacegroup_stats(mp_entries: list[dict]) -> list[dict]:
    """Compute space group frequency distribution from experimental MP entries."""
    sg_counts = Counter()
    for entry in mp_entries:
        if not entry.get("theoretical") and entry.get("space_group_number"):
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


def match_material_to_mp(material_info: dict, mp_entries: list[dict],
                         synth_ids: set, not_synth_ids: set,
                         chemsys: str) -> dict:
    """Match a GNoME material against MP entries with synth/not-synth labels.

    Classification:
      - experimentally_known: composition matches an MP entry that is in synth_ids
      - computationally_known: composition matches MP entries but none are in synth_ids
      - novel: no composition match in MP at all

    synth_status:
      - synth: best matching MP entry is in synth_ids (ICSD-verified)
      - not_synth: best match is in not_synth_ids (computational only)
      - no_mp_match: no MP entries for this composition
    """
    formula = material_info["reduced_formula"]
    all_mp_ids = [e["mp_id"] for e in mp_entries]

    # Find composition matches
    matches = [e for e in mp_entries if e.get("formula") == formula]

    if not matches:
        return {
            "chemsys": chemsys,
            "mp_ids": all_mp_ids,
            "best_match_mp_id": None,
            "match_type": "novel",
            "synth_status": "no_mp_match",
            "mp_is_experimental": None,
            "mp_formula": None,
            "mp_formation_energy": None,
            "mp_space_group": None,
        }

    # Check synth status of each match
    synth_matches = [m for m in matches if m["mp_id"] in synth_ids]
    not_synth_matches = [m for m in matches if m["mp_id"] in not_synth_ids]

    if synth_matches:
        best = synth_matches[0]
        return {
            "chemsys": chemsys,
            "mp_ids": all_mp_ids,
            "best_match_mp_id": best["mp_id"],
            "match_type": "experimentally_known",
            "synth_status": "synth",
            "mp_is_experimental": True,
            "mp_formula": best.get("formula"),
            "mp_formation_energy": best.get("formation_energy_per_atom"),
            "mp_space_group": best.get("space_group_symbol"),
        }
    elif not_synth_matches:
        best = not_synth_matches[0]
        return {
            "chemsys": chemsys,
            "mp_ids": all_mp_ids,
            "best_match_mp_id": best["mp_id"],
            "match_type": "computationally_known",
            "synth_status": "not_synth",
            "mp_is_experimental": False,
            "mp_formula": best.get("formula"),
            "mp_formation_energy": best.get("formation_energy_per_atom"),
            "mp_space_group": best.get("space_group_symbol"),
        }
    else:
        # Matches exist but not in either gold data set
        best = matches[0]
        is_exp = not best.get("theoretical", True)
        return {
            "chemsys": chemsys,
            "mp_ids": all_mp_ids,
            "best_match_mp_id": best["mp_id"],
            "match_type": "experimentally_known" if is_exp else "computationally_known",
            "synth_status": "synth" if is_exp else "not_synth",
            "mp_is_experimental": is_exp,
            "mp_formula": best.get("formula"),
            "mp_formation_energy": best.get("formation_energy_per_atom"),
            "mp_space_group": best.get("space_group_symbol"),
        }


def run_mp_cross_reference(api_key: str | None = None):
    """Run full MP cross-referencing with synth/not-synth gold data.

    1. Load synth/not-synth gold data
    2. Get unique chemical systems
    3. Query MP for each (with caching)
    4. Collect space group stats
    5. Match each material with synth/not-synth classification
    """
    conn = get_connection()

    # Load gold data
    synth_ids, not_synth_ids = _load_gold_data()
    print(f"Gold data loaded: {len(synth_ids)} synth, {len(not_synth_ids)} not-synth MP entries")

    chemsys_list = _get_unique_chemsys(conn)
    print(f"Found {len(chemsys_list)} unique chemical systems to query")

    # Query MP for each chemical system
    mp_data = {}
    for chemsys in tqdm(chemsys_list, desc="Querying MP"):
        entries = query_mp_for_chemsys(chemsys, api_key)
        mp_data[chemsys] = entries

        sg_stats = _collect_spacegroup_stats(entries)
        if sg_stats:
            insert_spacegroup_stats_batch(conn, chemsys, sg_stats)

        time.sleep(0.05)

    # Match each material
    material_ids = get_all_material_ids(conn)
    counts = Counter()

    for mat_id in tqdm(material_ids, desc="Matching materials"):
        mat = get_material(conn, mat_id)
        if mat is None:
            continue

        elements = mat["elements"]
        chemsys = "-".join(sorted(elements))
        entries = mp_data.get(chemsys, [])

        match_data = match_material_to_mp(mat, entries, synth_ids, not_synth_ids, chemsys)
        insert_mp_cross_ref(conn, mat_id, match_data)
        counts[match_data["match_type"]] += 1

    conn.commit()
    conn.close()

    print(f"\nMP cross-referencing complete:")
    for match_type, count in counts.most_common():
        print(f"  {match_type}: {count}")
