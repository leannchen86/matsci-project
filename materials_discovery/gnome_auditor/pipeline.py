"""Orchestrates all validators with per-material checkpointing.

Runs oxidation state assignment once, then all validators for each material.
Commits to DB after each material (crash-safe checkpointing).
"""

from dataclasses import asdict
from pathlib import Path

from pymatgen.core import Structure
from pymatgen.analysis.local_env import CrystalNN
from tqdm import tqdm

from gnome_auditor.config import EXTRACTED_CIFS_DIR
from gnome_auditor.db.store import (
    get_connection,
    get_all_material_ids,
    get_material,
    get_oxi_assignment,
    insert_oxi_assignment,
    insert_validation_result,
    has_validation_result,
)
from gnome_auditor.validators.oxidation_states import assign_oxidation_states
from gnome_auditor.validators.charge_neutrality import ChargeNeutralityValidator
from gnome_auditor.validators.shannon_radii import ShannonRadiiValidator
from gnome_auditor.validators.pauling_rule2 import PaulingRule2Validator
from gnome_auditor.validators.goldschmidt import GoldschmidtValidator
from gnome_auditor.validators.bond_valence_sum import BondValenceSumValidator
from gnome_auditor.validators.space_group import SpaceGroupValidator


def _load_structure(material_id: str) -> Structure | None:
    """Load a structure from the extracted CIF files."""
    cif_path = EXTRACTED_CIFS_DIR / f"{material_id}.cif"
    if not cif_path.exists():
        return None
    try:
        return Structure.from_file(str(cif_path))
    except Exception:
        return None


def _get_validators(conn=None):
    """Instantiate all validators."""
    return [
        # Tier 1
        ChargeNeutralityValidator(),
        ShannonRadiiValidator(),
        PaulingRule2Validator(),
        GoldschmidtValidator(),
        # Tier 2
        BondValenceSumValidator(),
        SpaceGroupValidator(conn=conn),
    ]


def validate_material(material_id: str, conn=None, force: bool = False) -> dict:
    """Run all validation checks on a single material.

    Returns dict with oxi_assignment and list of validation results.
    Uses checkpointing: skips checks that already have results in DB.
    """
    if conn is None:
        conn = get_connection()

    mat = get_material(conn, material_id)
    if mat is None:
        return {"error": f"Material {material_id} not found in database"}

    # Load structure
    structure = _load_structure(material_id)
    if structure is None:
        return {"error": f"Could not load CIF for {material_id}"}

    # Step 1: Oxidation state assignment (compute once, reuse everywhere)
    oxi_db = get_oxi_assignment(conn, material_id)
    if oxi_db is None or force:
        oxi_result = assign_oxidation_states(structure)
        oxi_dict = {
            "method_used": oxi_result.method_used,
            "oxi_states": oxi_result.oxi_states,
            "bv_analyzer_result": oxi_result.bv_analyzer_result,
            "guesses_result": oxi_result.guesses_result,
            "confidence": oxi_result.confidence,
            "has_mixed_valence": oxi_result.has_mixed_valence,
            "mixed_valence_elements": oxi_result.mixed_valence_elements,
        }
        insert_oxi_assignment(conn, material_id, oxi_dict)
        conn.commit()
    else:
        oxi_dict = oxi_db

    # Step 2: Pre-compute CrystalNN neighbor info (shared by Shannon + Pauling)
    nn_cache = None
    validators = _get_validators(conn=conn)
    needs_nn = any(
        not force and not has_validation_result(conn, material_id, v.check_name)
        for v in validators if v.check_name in ("shannon_radii", "pauling_rule2")
    )
    if force or needs_nn:
        try:
            cnn = CrystalNN()
            nn_cache = {}
            for i in range(len(structure)):
                try:
                    nn_cache[i] = cnn.get_nn_info(structure, i)
                except Exception:
                    pass  # individual site failures are handled by validators
        except Exception:
            nn_cache = None  # validators will fall back to computing their own

    # Step 3: Run all validators
    results = []

    for validator in validators:
        check_name = validator.check_name

        # Checkpointing: skip if already computed (unless force)
        if not force and has_validation_result(conn, material_id, check_name):
            continue

        try:
            result = validator.validate(structure, mat, oxi_dict, nn_cache=nn_cache)
        except Exception as e:
            result = validator._error(str(e))

        db_dict = result.to_db_dict(material_id)
        insert_validation_result(conn, db_dict)
        results.append(result)

    conn.commit()
    return {"material_id": material_id, "oxi_assignment": oxi_dict, "results": results}


def run_full_pipeline(force: bool = False):
    """Run validation on all materials with per-material checkpointing."""
    conn = get_connection()
    material_ids = get_all_material_ids(conn)

    print(f"Running validation pipeline on {len(material_ids)} materials...")
    n_success = 0
    n_error = 0

    for mat_id in tqdm(material_ids, desc="Validating"):
        try:
            result = validate_material(mat_id, conn=conn, force=force)
            if "error" in result:
                n_error += 1
            else:
                n_success += 1
        except Exception as e:
            n_error += 1
            tqdm.write(f"Error on {mat_id}: {e}")

    conn.close()
    print(f"\nPipeline complete: {n_success} succeeded, {n_error} errors")
