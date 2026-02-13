"""SQLite schema definitions and view creation for the GNoME Auditor database."""

TABLES = {
    "materials": """
        CREATE TABLE IF NOT EXISTS materials (
            material_id TEXT PRIMARY KEY,
            composition TEXT NOT NULL,
            reduced_formula TEXT NOT NULL,
            elements TEXT NOT NULL,          -- JSON array
            n_sites INTEGER NOT NULL,
            volume REAL NOT NULL,
            density REAL NOT NULL,
            space_group TEXT,
            space_group_number INTEGER,
            crystal_system TEXT,
            formation_energy_per_atom REAL,
            decomposition_energy_per_atom REAL,
            bandgap REAL,
            is_train INTEGER,                -- 0/1 boolean
            has_r2scan INTEGER DEFAULT 0,
            r2scan_decomp_energy REAL,
            oxide_type TEXT                  -- ABO3, AB2O4, etc. or 'other'
        )
    """,

    "oxidation_state_assignments": """
        CREATE TABLE IF NOT EXISTS oxidation_state_assignments (
            material_id TEXT PRIMARY KEY REFERENCES materials(material_id),
            method_used TEXT NOT NULL,        -- bv_analyzer | oxi_state_guesses | both_agree | both_disagree | none
            oxi_states TEXT,                  -- JSON: chosen assignment
            bv_analyzer_result TEXT,          -- JSON: BVAnalyzer output (nullable)
            guesses_result TEXT,              -- JSON: oxi_state_guesses output (nullable)
            confidence TEXT NOT NULL           -- high | medium | low | none
        )
    """,

    "validation_results": """
        CREATE TABLE IF NOT EXISTS validation_results (
            material_id TEXT NOT NULL REFERENCES materials(material_id),
            check_name TEXT NOT NULL,
            tier INTEGER NOT NULL,
            independence TEXT NOT NULL,
            status TEXT NOT NULL,             -- completed | skipped_no_params | skipped_not_applicable | error
            passed INTEGER,                   -- 0/1 boolean, only meaningful when status=completed
            confidence REAL,
            score REAL,
            details TEXT,                     -- JSON
            error_message TEXT,
            run_timestamp TEXT NOT NULL,
            PRIMARY KEY (material_id, check_name)
        )
    """,

    "mp_cross_ref": """
        CREATE TABLE IF NOT EXISTS mp_cross_ref (
            material_id TEXT PRIMARY KEY REFERENCES materials(material_id),
            mp_id TEXT,
            match_type TEXT,                  -- experimental_match | computational_match | novel | structural_mismatch
            mp_is_experimental INTEGER,       -- 0/1
            mp_formation_energy REAL,
            mp_space_group TEXT
        )
    """,

    "mp_spacegroup_stats": """
        CREATE TABLE IF NOT EXISTS mp_spacegroup_stats (
            chemsys TEXT NOT NULL,
            space_group_number INTEGER NOT NULL,
            count INTEGER NOT NULL,
            fraction REAL NOT NULL,
            PRIMARY KEY (chemsys, space_group_number)
        )
    """,
}

VIEWS = {
    "v_audit_summary": """
        CREATE VIEW IF NOT EXISTS v_audit_summary AS
        SELECT
            vr.check_name,
            vr.tier,
            vr.independence,
            COUNT(*) AS total,
            SUM(CASE WHEN vr.status = 'completed' THEN 1 ELSE 0 END) AS computed,
            SUM(CASE WHEN vr.status = 'completed' AND vr.passed = 1 THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN vr.status = 'completed' AND vr.passed = 0 THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN vr.status = 'skipped_no_params' THEN 1 ELSE 0 END) AS skipped_no_params,
            SUM(CASE WHEN vr.status = 'skipped_not_applicable' THEN 1 ELSE 0 END) AS skipped_na,
            SUM(CASE WHEN vr.status = 'error' THEN 1 ELSE 0 END) AS errors
        FROM validation_results vr
        GROUP BY vr.check_name, vr.tier, vr.independence
    """,

    "v_material_flags": """
        CREATE VIEW IF NOT EXISTS v_material_flags AS
        SELECT
            m.material_id,
            m.reduced_formula,
            m.oxide_type,
            osa.confidence AS oxi_confidence,
            SUM(CASE WHEN vr.status = 'completed' AND vr.passed = 0 THEN 1 ELSE 0 END) AS n_failed,
            SUM(CASE WHEN vr.status = 'completed' AND vr.passed = 1 THEN 1 ELSE 0 END) AS n_passed,
            SUM(CASE WHEN vr.status = 'completed' THEN 1 ELSE 0 END) AS n_computed,
            mc.match_type AS mp_match_type
        FROM materials m
        LEFT JOIN oxidation_state_assignments osa ON m.material_id = osa.material_id
        LEFT JOIN validation_results vr ON m.material_id = vr.material_id
        LEFT JOIN mp_cross_ref mc ON m.material_id = mc.material_id
        GROUP BY m.material_id
    """,
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_vr_check ON validation_results(check_name)",
    "CREATE INDEX IF NOT EXISTS idx_vr_status ON validation_results(status)",
    "CREATE INDEX IF NOT EXISTS idx_vr_passed ON validation_results(passed)",
    "CREATE INDEX IF NOT EXISTS idx_materials_formula ON materials(reduced_formula)",
    "CREATE INDEX IF NOT EXISTS idx_materials_oxide_type ON materials(oxide_type)",
    "CREATE INDEX IF NOT EXISTS idx_materials_crystal_system ON materials(crystal_system)",
    "CREATE INDEX IF NOT EXISTS idx_mp_match_type ON mp_cross_ref(match_type)",
]


def init_db(conn):
    """Create all tables, views, and indexes."""
    cursor = conn.cursor()
    for ddl in TABLES.values():
        cursor.execute(ddl)
    for ddl in VIEWS.values():
        cursor.execute(ddl)
    for ddl in INDEXES:
        cursor.execute(ddl)
    conn.commit()
