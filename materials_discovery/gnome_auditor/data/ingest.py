"""CSV filtering, CIF extraction, and DB population for GNoME ternary oxides."""

import ast
import json
import zipfile
from math import gcd
from functools import reduce

import pandas as pd
from tqdm import tqdm

from gnome_auditor.config import (
    SUMMARY_CSV, R2SCAN_CSV, BY_ID_ZIP, EXTRACTED_CIFS_DIR, OXIDE_TYPE_RATIOS,
)
from gnome_auditor.db.store import get_connection, insert_materials_batch


def _is_ternary_oxide(elements_str: str) -> bool:
    """Check if a material is a ternary oxide (exactly 3 elements, one is O)."""
    try:
        elements = ast.literal_eval(elements_str)
        return len(elements) == 3 and "O" in elements
    except (ValueError, SyntaxError):
        return False


def _classify_oxide_type(composition: str, reduced_formula: str, elements: list[str]) -> str:
    """Classify oxide type from reduced formula ratios.

    Simple approach: parse the reduced formula to get element counts,
    identify oxygen count and two cation counts, normalize, and match
    against known patterns.

    Documented limitation: misses double perovskites, Ruddlesden-Popper, etc.
    """
    from pymatgen.core import Composition
    try:
        comp = Composition(reduced_formula)
    except Exception:
        return "other"

    # Get element amounts in the reduced formula
    amounts = {}
    for el, amt in comp.items():
        amounts[str(el)] = amt

    o_count = amounts.get("O", 0)
    if o_count == 0:
        return "other"

    cation_counts = sorted(
        [amt for el, amt in amounts.items() if el != "O"],
        reverse=False,  # smaller first → A, B
    )
    if len(cation_counts) != 2:
        return "other"

    # Build ratio tuple and normalize
    a, b = cation_counts[0], cation_counts[1]
    raw = (a, b, o_count)
    # Convert to integers
    raw_int = tuple(int(x) if x == int(x) else 0 for x in raw)
    if 0 in raw_int:
        return "other"

    divisor = reduce(gcd, raw_int)
    normalized = tuple(x // divisor for x in raw_int)

    return OXIDE_TYPE_RATIOS.get(normalized, "other")


def load_and_filter_csv() -> pd.DataFrame:
    """Load the summary CSV and filter to ternary oxides."""
    print("Loading summary CSV...")
    df = pd.read_csv(SUMMARY_CSV)
    print(f"  Total materials: {len(df)}")

    mask = df["Elements"].apply(_is_ternary_oxide)
    ternary = df[mask].copy()
    print(f"  Ternary oxides: {len(ternary)}")

    # Join r2scan data
    print("Loading r2SCAN CSV...")
    r2 = pd.read_csv(R2SCAN_CSV)
    r2_ids = set(r2["MaterialId"].values)
    ternary["has_r2scan"] = ternary["MaterialId"].isin(r2_ids)

    r2_decomp = r2.set_index("MaterialId")["Decomposition Energy Per Atom"]
    ternary["r2scan_decomp_energy"] = ternary["MaterialId"].map(r2_decomp)

    return ternary


def extract_cifs(material_ids: set[str]) -> dict[str, str]:
    """Extract CIF files for the given material IDs from the by_id zip.

    Returns dict mapping material_id → path to extracted CIF file.
    """
    print(f"Extracting CIFs for {len(material_ids)} materials...")
    extracted = {}
    with zipfile.ZipFile(BY_ID_ZIP, "r") as zf:
        for name in tqdm(zf.namelist(), desc="Scanning zip"):
            if not name.endswith(".CIF"):
                continue
            # by_id/MATERIALID.CIF
            mat_id = name.split("/")[-1].replace(".CIF", "")
            if mat_id in material_ids:
                out_path = EXTRACTED_CIFS_DIR / f"{mat_id}.cif"
                if not out_path.exists():
                    data = zf.read(name)
                    out_path.write_bytes(data)
                extracted[mat_id] = str(out_path)
    print(f"  Extracted: {len(extracted)} CIFs")
    return extracted


def populate_db(df: pd.DataFrame, cif_paths: dict[str, str]):
    """Populate the SQLite database from the filtered DataFrame."""
    print("Populating database...")
    conn = get_connection()

    materials = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Building records"):
        elements = ast.literal_eval(row["Elements"])
        mat_id = row["MaterialId"]

        # Skip materials without extracted CIFs
        if mat_id not in cif_paths:
            continue

        oxide_type = _classify_oxide_type(
            row["Composition"], row["Reduced Formula"], elements
        )

        materials.append({
            "material_id": mat_id,
            "composition": row["Composition"],
            "reduced_formula": row["Reduced Formula"],
            "elements": elements,
            "n_sites": int(row["NSites"]),
            "volume": float(row["Volume"]),
            "density": float(row["Density"]),
            "space_group": row.get("Space Group"),
            "space_group_number": int(row["Space Group Number"]) if pd.notna(row.get("Space Group Number")) else None,
            "crystal_system": row.get("Crystal System"),
            "formation_energy_per_atom": float(row["Formation Energy Per Atom"]) if pd.notna(row.get("Formation Energy Per Atom")) else None,
            "decomposition_energy_per_atom": float(row["Decomposition Energy Per Atom"]) if pd.notna(row.get("Decomposition Energy Per Atom")) else None,
            "bandgap": float(row["Bandgap"]) if pd.notna(row.get("Bandgap")) else None,
            "is_train": bool(row.get("Is Train", False)),
            "has_r2scan": bool(row.get("has_r2scan", False)),
            "r2scan_decomp_energy": float(row["r2scan_decomp_energy"]) if pd.notna(row.get("r2scan_decomp_energy")) else None,
            "oxide_type": oxide_type,
        })

    insert_materials_batch(conn, materials)
    conn.close()
    print(f"  Inserted {len(materials)} materials into database.")
    return len(materials)


def run_ingestion():
    """Full ingestion pipeline: filter CSV → extract CIFs → populate DB."""
    df = load_and_filter_csv()
    material_ids = set(df["MaterialId"].values)
    cif_paths = extract_cifs(material_ids)
    count = populate_db(df, cif_paths)
    return count
