"""Database read/write operations for the GNoME Auditor."""

import json
import sqlite3
from pathlib import Path

from gnome_auditor.config import DB_PATH
from gnome_auditor.db.schema import init_db


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a database connection, initializing if needed."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    init_db(conn)
    return conn


# --- Materials ---

def insert_material(conn, mat: dict):
    """Insert a single material row."""
    conn.execute("""
        INSERT OR REPLACE INTO materials
        (material_id, composition, reduced_formula, elements, n_sites, volume, density,
         space_group, space_group_number, crystal_system,
         formation_energy_per_atom, decomposition_energy_per_atom, bandgap, is_train,
         has_r2scan, r2scan_decomp_energy, oxide_type, compound_class)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        mat["material_id"], mat["composition"], mat["reduced_formula"],
        json.dumps(mat["elements"]), mat["n_sites"], mat["volume"], mat["density"],
        mat.get("space_group"), mat.get("space_group_number"), mat.get("crystal_system"),
        mat.get("formation_energy_per_atom"), mat.get("decomposition_energy_per_atom"),
        mat.get("bandgap"), int(mat.get("is_train", False)),
        int(mat.get("has_r2scan", False)), mat.get("r2scan_decomp_energy"),
        mat.get("oxide_type"), mat.get("compound_class", "pure_oxide"),
    ))


def insert_materials_batch(conn, materials: list[dict]):
    """Insert a batch of materials in a single transaction."""
    for mat in materials:
        insert_material(conn, mat)
    conn.commit()


def get_material(conn, material_id: str) -> dict | None:
    """Retrieve a material by ID."""
    row = conn.execute("SELECT * FROM materials WHERE material_id = ?", (material_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["elements"] = json.loads(d["elements"])
    return d


def get_material_by_formula(conn, formula: str) -> list[dict]:
    """Retrieve materials matching a reduced formula."""
    rows = conn.execute(
        "SELECT * FROM materials WHERE reduced_formula = ?", (formula,)
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["elements"] = json.loads(d["elements"])
        results.append(d)
    return results


def search_materials(conn, *, element: str | None = None,
                     crystal_system: str | None = None,
                     oxide_type: str | None = None,
                     compound_class: str | None = None,
                     check_name: str | None = None,
                     check_passed: bool | None = None,
                     synth_status: str | None = None,
                     limit: int = 50) -> list[dict]:
    """Search materials with optional filters."""
    clauses = []
    params = []
    joins = []

    if element:
        clauses.append("m.elements LIKE ?")
        params.append(f'%"{element}"%')
    if crystal_system:
        clauses.append("m.crystal_system = ?")
        params.append(crystal_system)
    if oxide_type:
        clauses.append("m.oxide_type = ?")
        params.append(oxide_type)
    if compound_class:
        clauses.append("m.compound_class = ?")
        params.append(compound_class)
    if check_name is not None:
        joins.append("JOIN validation_results vr ON m.material_id = vr.material_id")
        clauses.append("vr.check_name = ?")
        params.append(check_name)
        if check_passed is not None:
            clauses.append("vr.passed = ?")
            params.append(int(check_passed))
            clauses.append("vr.status = 'completed'")
    if synth_status:
        joins.append("JOIN mp_cross_ref mc ON m.material_id = mc.material_id")
        clauses.append("mc.synth_status = ?")
        params.append(synth_status)

    join_clause = " ".join(joins) if joins else ""
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT DISTINCT m.* FROM materials m {join_clause} WHERE {where} LIMIT ?",
        params + [limit]
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["elements"] = json.loads(d["elements"])
        results.append(d)
    return results


def get_all_material_ids(conn) -> list[str]:
    """Get all material IDs."""
    rows = conn.execute("SELECT material_id FROM materials ORDER BY material_id").fetchall()
    return [r["material_id"] for r in rows]


# --- Oxidation State Assignments ---

def insert_oxi_assignment(conn, material_id: str, result: dict):
    """Insert or update an oxidation state assignment."""
    conn.execute("""
        INSERT OR REPLACE INTO oxidation_state_assignments
        (material_id, method_used, oxi_states, bv_analyzer_result, guesses_result,
         confidence, has_mixed_valence, mixed_valence_elements)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        material_id,
        result["method_used"],
        json.dumps(result["oxi_states"]) if result["oxi_states"] else None,
        json.dumps(result["bv_analyzer_result"]) if result.get("bv_analyzer_result") else None,
        json.dumps(result["guesses_result"]) if result.get("guesses_result") else None,
        result["confidence"],
        int(result.get("has_mixed_valence", False)),
        json.dumps(result["mixed_valence_elements"]) if result.get("mixed_valence_elements") else None,
    ))


def get_oxi_assignment(conn, material_id: str) -> dict | None:
    """Retrieve oxidation state assignment for a material."""
    row = conn.execute(
        "SELECT * FROM oxidation_state_assignments WHERE material_id = ?",
        (material_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d["oxi_states"]:
        d["oxi_states"] = json.loads(d["oxi_states"])
    if d["bv_analyzer_result"]:
        d["bv_analyzer_result"] = json.loads(d["bv_analyzer_result"])
    if d["guesses_result"]:
        d["guesses_result"] = json.loads(d["guesses_result"])
    if d.get("mixed_valence_elements"):
        d["mixed_valence_elements"] = json.loads(d["mixed_valence_elements"])
    d["has_mixed_valence"] = bool(d.get("has_mixed_valence", 0))
    return d


# --- Validation Results ---

def insert_validation_result(conn, result: dict):
    """Insert or update a validation result."""
    conn.execute("""
        INSERT OR REPLACE INTO validation_results
        (material_id, check_name, tier, independence, status, passed,
         confidence, score, details, error_message, run_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result["material_id"], result["check_name"], result["tier"],
        result["independence"], result["status"],
        int(result["passed"]) if result["passed"] is not None else None,
        result.get("confidence"), result.get("score"),
        json.dumps(result["details"]) if result.get("details") else None,
        result.get("error_message"), result["run_timestamp"],
    ))


def get_validation_results(conn, material_id: str) -> list[dict]:
    """Get all validation results for a material."""
    rows = conn.execute(
        "SELECT * FROM validation_results WHERE material_id = ? ORDER BY tier, check_name",
        (material_id,)
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d["details"]:
            d["details"] = json.loads(d["details"])
        d["passed"] = bool(d["passed"]) if d["passed"] is not None else None
        results.append(d)
    return results


def get_validation_results_by_check(conn, check_name: str, *,
                                     status: str | None = None,
                                     limit: int = 100) -> list[dict]:
    """Get validation results for a specific check across materials."""
    clauses = ["check_name = ?"]
    params: list = [check_name]
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM validation_results WHERE {where} LIMIT ?",
        params + [limit]
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d["details"]:
            d["details"] = json.loads(d["details"])
        d["passed"] = bool(d["passed"]) if d["passed"] is not None else None
        results.append(d)
    return results


def has_validation_result(conn, material_id: str, check_name: str) -> bool:
    """Check if a validation result already exists (for checkpointing)."""
    row = conn.execute(
        "SELECT 1 FROM validation_results WHERE material_id = ? AND check_name = ?",
        (material_id, check_name)
    ).fetchone()
    return row is not None


# --- MP Cross-Reference ---

def insert_mp_cross_ref(conn, material_id: str, data: dict):
    """Insert or update MP cross-reference data."""
    conn.execute("""
        INSERT OR REPLACE INTO mp_cross_ref
        (material_id, chemsys, mp_ids, best_match_mp_id, match_type, synth_status,
         mp_is_experimental, mp_formula, mp_formation_energy, mp_space_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        material_id,
        data.get("chemsys"),
        json.dumps(data["mp_ids"]) if data.get("mp_ids") else None,
        data.get("best_match_mp_id"),
        data.get("match_type"),
        data.get("synth_status"),
        int(data["mp_is_experimental"]) if data.get("mp_is_experimental") is not None else None,
        data.get("mp_formula"),
        data.get("mp_formation_energy"),
        data.get("mp_space_group"),
    ))


def get_mp_cross_ref(conn, material_id: str) -> dict | None:
    """Get MP cross-reference data for a material."""
    row = conn.execute(
        "SELECT * FROM mp_cross_ref WHERE material_id = ?", (material_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("mp_ids"):
        d["mp_ids"] = json.loads(d["mp_ids"])
    d["mp_is_experimental"] = bool(d["mp_is_experimental"]) if d["mp_is_experimental"] is not None else None
    return d


# --- MP Space Group Stats ---

def insert_spacegroup_stats_batch(conn, chemsys: str, stats: list[dict]):
    """Insert space group statistics for a chemical system."""
    for s in stats:
        conn.execute("""
            INSERT OR REPLACE INTO mp_spacegroup_stats
            (chemsys, space_group_number, count, fraction)
            VALUES (?, ?, ?, ?)
        """, (chemsys, s["space_group_number"], s["count"], s["fraction"]))
    conn.commit()


def get_spacegroup_stats(conn, chemsys: str) -> list[dict]:
    """Get space group statistics for a chemical system."""
    rows = conn.execute(
        "SELECT * FROM mp_spacegroup_stats WHERE chemsys = ? ORDER BY count DESC",
        (chemsys,)
    ).fetchall()
    return [dict(r) for r in rows]


# --- Statistics / Aggregations ---

def get_audit_summary(conn) -> list[dict]:
    """Get aggregate validation statistics from the view."""
    rows = conn.execute("SELECT * FROM v_audit_summary ORDER BY tier, check_name").fetchall()
    return [dict(r) for r in rows]


def get_statistics(conn) -> dict:
    """Get overall database statistics."""
    total = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    oxi_counts = conn.execute("""
        SELECT confidence, COUNT(*) as cnt
        FROM oxidation_state_assignments
        GROUP BY confidence
    """).fetchall()
    mp_counts = conn.execute("""
        SELECT synth_status, COUNT(*) as cnt
        FROM mp_cross_ref
        GROUP BY synth_status
    """).fetchall()
    compound_counts = conn.execute("""
        SELECT compound_class, COUNT(*) as cnt
        FROM materials
        GROUP BY compound_class
    """).fetchall()

    return {
        "total_materials": total,
        "oxidation_state_confidence": {r["confidence"]: r["cnt"] for r in oxi_counts},
        "mp_synth_status": {r["synth_status"]: r["cnt"] for r in mp_counts if r["synth_status"]},
        "compound_classes": {r["compound_class"]: r["cnt"] for r in compound_counts},
    }
