"""Paths, constants, and thresholds for the GNoME Auditor."""

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # materials_discovery/
DATA_DIR = PROJECT_ROOT / "data"
GNOME_DATA_DIR = DATA_DIR / "gnome_data"
AUDITOR_DB_DIR = DATA_DIR / "auditor_db"
MP_CACHE_DIR = AUDITOR_DB_DIR / "mp_cache"
EXTRACTED_CIFS_DIR = DATA_DIR / "extracted_cifs"

# Data files
SUMMARY_CSV = GNOME_DATA_DIR / "stable_materials_summary.csv"
R2SCAN_CSV = GNOME_DATA_DIR / "stable_materials_r2scan.csv"
BY_ID_ZIP = GNOME_DATA_DIR / "by_id.zip"

# Database
DB_PATH = AUDITOR_DB_DIR / "gnome_auditor.db"

# Ensure directories exist
for d in [AUDITOR_DB_DIR, MP_CACHE_DIR, EXTRACTED_CIFS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- Validator thresholds ---

# Shannon radii: bond length tolerance (fraction of expected)
SHANNON_TOLERANCE = 0.25  # 25% deviation from expected bond length

# Bond Valence Sum
BVS_TOLERANCE = 0.35  # |BVS - expected| / expected < 35%
GII_THRESHOLD = 0.2   # Global instability index threshold (v.u.)

# Pauling Rule 2: electrostatic valence sum tolerance
PAULING_R2_TOLERANCE = 0.25  # |sum - |valence_O|| / |valence_O| < 25%

# Goldschmidt tolerance factor range for stable perovskites
GOLDSCHMIDT_MIN = 0.71
GOLDSCHMIDT_MAX = 1.05

# Space group plausibility
SPACEGROUP_MIN_FRACTION = 0.01  # Flag if <1% of experimental entries share this space group

# Oxidation state confidence mapping
OXI_CONFIDENCE_MAP = {
    "high": 0.9,    # both methods agree
    "medium": 0.7,  # one method succeeded
    "low": 0.4,     # methods disagree
    "none": 0.0,    # neither worked
}

# Oxide type classification patterns (reduced formula element ratios)
# Maps (A:B:O) ratios to type names
OXIDE_TYPE_RATIOS = {
    (1, 1, 3): "ABO3",
    (1, 2, 4): "AB2O4",
    (2, 1, 4): "A2BO4",
    (1, 1, 2): "ABO2",
    (2, 2, 7): "A2B2O7",
    (1, 2, 6): "AB2O6",
    (2, 1, 3): "A2BO3",
}
