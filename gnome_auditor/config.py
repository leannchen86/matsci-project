"""Paths, constants, and thresholds for the GNoME Auditor."""

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # repo root
DATA_DIR = PROJECT_ROOT / "data"
GNOME_DATA_DIR = DATA_DIR / "gnome_data"
AUDITOR_DB_DIR = DATA_DIR / "auditor_db"
MP_CACHE_DIR = AUDITOR_DB_DIR / "mp_cache"
EXTRACTED_CIFS_DIR = DATA_DIR / "extracted_cifs"

# Gold data
GOLD_DATA_DIR = Path(__file__).resolve().parent / "gold_data"
SYNTH_CSV = GOLD_DATA_DIR / "mp_synth_icsd.csv"
NOT_SYNTH_CSV = GOLD_DATA_DIR / "mp_not_synth_icsd.csv"

# Data files
SUMMARY_CSV = GNOME_DATA_DIR / "stable_materials_summary.csv"
R2SCAN_CSV = GNOME_DATA_DIR / "stable_materials_r2scan.csv"
BY_ID_ZIP = GNOME_DATA_DIR / "by_id.zip"

# Database
DB_PATH = AUDITOR_DB_DIR / "gnome_auditor.db"

# Ensure directories exist
for d in [AUDITOR_DB_DIR, MP_CACHE_DIR, EXTRACTED_CIFS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- Validator reference values ---
# These are NOT pass/fail thresholds. They are reference baselines from the
# literature for contextualizing continuous metrics.

# Shannon radii: bond length tolerance (fraction of expected)
SHANNON_TOLERANCE = 0.25  # 25% deviation — used to count violations, not to judge

# Bond Valence Sum
BVS_TOLERANCE = 0.35  # per-site relative deviation reference
GII_REFERENCE_ICSD = 0.2   # GII baseline for ICSD experimental structures (v.u.)

# Pauling Rule 2: electrostatic valence sum tolerance
PAULING_R2_TOLERANCE = 0.25  # |sum - |valence_O|| / |valence_O| reference

# Goldschmidt tolerance factor range for stable perovskites
GOLDSCHMIDT_MIN = 0.71
GOLDSCHMIDT_MAX = 1.05

# Space group plausibility
SPACEGROUP_MIN_FRACTION = 0.01

# Oxidation state confidence — descriptive labels, NOT quality guarantees
OXI_CONFIDENCE_MAP = {
    "both_agree": 0.9,         # both methods returned same result
    "single_method": 0.7,      # only one method succeeded
    "methods_disagree": 0.4,   # both succeeded but gave different states
    "no_assignment": 0.0,      # neither method could assign states
}

# Oxide type classification patterns (reduced formula element ratios)
OXIDE_TYPE_RATIOS = {
    (1, 1, 3): "ABO3",
    (1, 2, 4): "AB2O4",
    (2, 1, 4): "A2BO4",
    (1, 1, 2): "ABO2",
    (2, 2, 7): "A2B2O7",
    (1, 2, 6): "AB2O6",
    (2, 1, 3): "A2BO3",
}

# Compound class classification — identifies non-pure-oxide compounds
# that need separate treatment because O²⁻ assumption may not hold
ANION_ELEMENTS = {
    "F", "Cl", "Br", "I",      # halogens → oxyhalide
    "S", "Se", "Te",            # chalcogens → oxychalcogenide
    "N",                        # nitrogen → oxynitride
    "H",                        # hydrogen → oxyhydride
}
