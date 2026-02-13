"""Tier 1: Shannon radii check — interatomic distances vs expected from ionic radii."""

from pymatgen.core import Structure

from gnome_auditor.config import SHANNON_TOLERANCE, OXI_CONFIDENCE_MAP
from gnome_auditor.validators.base import BaseValidator, ValidationResult

# Shannon effective ionic radii (Å) for common oxidation states and coordination numbers.
# Source: Shannon (1976), Acta Cryst. A32, 751-767.
# Format: {(element, oxidation_state, coordination_number): radius}
# We include the most common coordination numbers; for elements not listed,
# the validator returns skipped_no_params.
SHANNON_RADII = {
    # Alkali metals
    ("Li", 1, 4): 0.59, ("Li", 1, 6): 0.76, ("Li", 1, 8): 0.92,
    ("Na", 1, 4): 0.99, ("Na", 1, 6): 1.02, ("Na", 1, 8): 1.18, ("Na", 1, 12): 1.39,
    ("K", 1, 6): 1.38, ("K", 1, 8): 1.51, ("K", 1, 12): 1.64,
    ("Rb", 1, 6): 1.52, ("Rb", 1, 8): 1.61, ("Rb", 1, 12): 1.72,
    ("Cs", 1, 6): 1.67, ("Cs", 1, 8): 1.74, ("Cs", 1, 12): 1.88,
    # Alkaline earth
    ("Be", 2, 4): 0.27, ("Be", 2, 6): 0.45,
    ("Mg", 2, 4): 0.57, ("Mg", 2, 6): 0.72, ("Mg", 2, 8): 0.89,
    ("Ca", 2, 6): 1.00, ("Ca", 2, 8): 1.12, ("Ca", 2, 12): 1.34,
    ("Sr", 2, 6): 1.18, ("Sr", 2, 8): 1.26, ("Sr", 2, 12): 1.44,
    ("Ba", 2, 6): 1.35, ("Ba", 2, 8): 1.42, ("Ba", 2, 12): 1.61,
    # Transition metals — common oxidation states
    ("Ti", 3, 6): 0.67, ("Ti", 4, 4): 0.42, ("Ti", 4, 6): 0.605,
    ("V", 3, 6): 0.64, ("V", 4, 6): 0.58, ("V", 5, 4): 0.355, ("V", 5, 6): 0.54,
    ("Cr", 3, 6): 0.615, ("Cr", 6, 4): 0.26, ("Cr", 6, 6): 0.44,
    ("Mn", 2, 6): 0.83, ("Mn", 3, 6): 0.645, ("Mn", 4, 6): 0.53,
    ("Fe", 2, 4): 0.63, ("Fe", 2, 6): 0.78, ("Fe", 3, 4): 0.49, ("Fe", 3, 6): 0.645,
    ("Co", 2, 6): 0.745, ("Co", 3, 6): 0.61, ("Co", 4, 6): 0.53,
    ("Ni", 2, 4): 0.55, ("Ni", 2, 6): 0.69, ("Ni", 3, 6): 0.56,
    ("Cu", 1, 4): 0.60, ("Cu", 2, 4): 0.57, ("Cu", 2, 6): 0.73,
    ("Zn", 2, 4): 0.60, ("Zn", 2, 6): 0.74,
    # 4d transition metals
    ("Zr", 4, 6): 0.72, ("Zr", 4, 8): 0.84,
    ("Nb", 5, 6): 0.64, ("Nb", 4, 6): 0.68,
    ("Mo", 4, 6): 0.65, ("Mo", 6, 4): 0.41, ("Mo", 6, 6): 0.59,
    ("Ru", 4, 6): 0.62, ("Ru", 3, 6): 0.68, ("Ru", 5, 6): 0.565,
    ("Rh", 3, 6): 0.665, ("Rh", 4, 6): 0.60,
    ("Pd", 2, 4): 0.64, ("Pd", 4, 6): 0.615,
    ("Ag", 1, 4): 1.00, ("Ag", 1, 6): 1.15,
    ("Cd", 2, 6): 0.95, ("Cd", 2, 8): 1.10,
    # 5d transition metals
    ("Hf", 4, 6): 0.71, ("Hf", 4, 8): 0.83,
    ("Ta", 5, 6): 0.64, ("Ta", 4, 6): 0.68,
    ("W", 4, 6): 0.66, ("W", 6, 4): 0.42, ("W", 6, 6): 0.60,
    ("Re", 4, 6): 0.63, ("Re", 7, 6): 0.53,
    ("Os", 4, 6): 0.63, ("Os", 6, 6): 0.545,
    ("Ir", 3, 6): 0.68, ("Ir", 4, 6): 0.625, ("Ir", 5, 6): 0.57,
    ("Pt", 2, 4): 0.60, ("Pt", 4, 6): 0.625,
    ("Au", 1, 6): 1.37, ("Au", 3, 4): 0.68, ("Au", 3, 6): 0.85,
    # Post-transition metals
    ("Al", 3, 4): 0.39, ("Al", 3, 6): 0.535,
    ("Ga", 3, 4): 0.47, ("Ga", 3, 6): 0.62,
    ("In", 3, 6): 0.80, ("In", 3, 8): 0.92,
    ("Sn", 2, 6): 0.93, ("Sn", 4, 6): 0.69,
    ("Tl", 1, 6): 1.50, ("Tl", 3, 6): 0.885,
    ("Pb", 2, 6): 1.19, ("Pb", 2, 8): 1.29, ("Pb", 4, 6): 0.775,
    ("Bi", 3, 6): 1.03, ("Bi", 5, 6): 0.76,
    ("Sb", 3, 6): 0.76, ("Sb", 5, 6): 0.60,
    # Rare earths
    ("Sc", 3, 6): 0.745, ("Sc", 3, 8): 0.87,
    ("Y", 3, 6): 0.90, ("Y", 3, 8): 1.019,
    ("La", 3, 6): 1.032, ("La", 3, 8): 1.16, ("La", 3, 12): 1.36,
    ("Ce", 3, 6): 1.01, ("Ce", 4, 6): 0.87, ("Ce", 4, 8): 0.97,
    ("Pr", 3, 6): 0.99, ("Pr", 4, 6): 0.85,
    ("Nd", 3, 6): 0.983, ("Nd", 3, 8): 1.109,
    ("Sm", 3, 6): 0.958, ("Sm", 3, 8): 1.079,
    ("Eu", 2, 6): 1.17, ("Eu", 3, 6): 0.947,
    ("Gd", 3, 6): 0.938, ("Gd", 3, 8): 1.053,
    ("Tb", 3, 6): 0.923, ("Tb", 4, 6): 0.76,
    ("Dy", 3, 6): 0.912, ("Dy", 3, 8): 1.027,
    ("Ho", 3, 6): 0.901, ("Ho", 3, 8): 1.015,
    ("Er", 3, 6): 0.89, ("Er", 3, 8): 1.004,
    ("Tm", 3, 6): 0.88, ("Tm", 3, 8): 0.994,
    ("Yb", 2, 6): 1.02, ("Yb", 3, 6): 0.868,
    ("Lu", 3, 6): 0.861, ("Lu", 3, 8): 0.977,
    # Actinides (limited — Np, Pu, Pa, U, Th, Ac)
    ("Th", 4, 6): 0.94, ("Th", 4, 8): 1.05,
    ("U", 4, 6): 0.89, ("U", 6, 6): 0.73,
    ("Ac", 3, 6): 1.12,
    # Oxygen (anion)
    ("O", -2, 2): 1.35, ("O", -2, 3): 1.36, ("O", -2, 4): 1.38, ("O", -2, 6): 1.40,
    # Halogens (for halide-containing ternary oxides like Mn4Br6O)
    ("F", -1, 4): 1.31, ("F", -1, 6): 1.33,
    ("Cl", -1, 6): 1.81, ("Cl", 7, 4): 0.08,
    ("Br", -1, 6): 1.96, ("Br", 5, 6): 0.31,
    ("I", -1, 6): 2.20, ("I", 5, 6): 0.95, ("I", 7, 6): 0.53,
    # Chalcogenides
    ("S", -2, 6): 1.84, ("S", 6, 4): 0.12, ("S", 6, 6): 0.29,
    ("Se", -2, 6): 1.98, ("Se", 4, 6): 0.50, ("Se", 6, 6): 0.42,
    ("Te", -2, 6): 2.21, ("Te", 4, 6): 0.97, ("Te", 6, 6): 0.56,
    # Metalloids
    ("Si", 4, 4): 0.26, ("Si", 4, 6): 0.40,
    ("Ge", 4, 4): 0.39, ("Ge", 4, 6): 0.53,
    ("As", 3, 6): 0.58, ("As", 5, 4): 0.335, ("As", 5, 6): 0.46,
    ("P", 3, 6): 0.44, ("P", 5, 4): 0.17, ("P", 5, 6): 0.38,
    ("B", 3, 4): 0.11, ("B", 3, 6): 0.27,
    ("N", -3, 4): 1.46, ("N", 3, 6): 0.16, ("N", 5, 6): 0.13,
    ("C", 4, 6): 0.16,
}


def _get_shannon_radius(element: str, oxi_state: int, coord_number: int) -> tuple[float | None, str]:
    """Look up Shannon radius, trying exact CN then nearest CN, then pymatgen fallback.

    Returns (radius, source) where source is 'table_exact', 'table_nearest_cn',
    'pymatgen', or 'missing'.
    """
    # Try exact match from hand-curated table
    key = (element, oxi_state, coord_number)
    if key in SHANNON_RADII:
        return SHANNON_RADII[key], "table_exact"

    # Try nearby coordination numbers from hand-curated table
    available = {cn: r for (el, ox, cn), r in SHANNON_RADII.items()
                 if el == element and ox == oxi_state}
    if available:
        nearest_cn = min(available.keys(), key=lambda cn: abs(cn - coord_number))
        return available[nearest_cn], "table_nearest_cn"

    # Fallback to pymatgen's Species.ionic_radius
    try:
        from pymatgen.core import Species
        sp = Species(element, oxi_state)
        r = sp.ionic_radius
        if r is not None and r > 0:
            return float(r), "pymatgen"
    except Exception:
        pass

    return None, "missing"


class ShannonRadiiValidator(BaseValidator):
    check_name = "shannon_radii"
    tier = 1
    independence = "fully_independent"

    def validate(self, structure: Structure, material_info: dict,
                 oxi_assignment: dict | None = None,
                 nn_cache: dict | None = None) -> ValidationResult:
        if oxi_assignment is None or oxi_assignment["confidence"] == "no_assignment":
            return self._skip_no_params(
                "No oxidation state assignment available",
                details={"oxi_state_confidence": "none"},
            )

        oxi_states = oxi_assignment["oxi_states"]
        oxi_confidence = oxi_assignment["confidence"]
        confidence_score = OXI_CONFIDENCE_MAP.get(oxi_confidence, 0.0)

        # Use pre-computed neighbor cache or compute on the fly
        if nn_cache is None:
            from pymatgen.analysis.local_env import CrystalNN
            try:
                cnn = CrystalNN()
            except Exception as e:
                return self._error(f"CrystalNN initialization failed: {e}")
        else:
            cnn = None

        bond_checks = []
        n_checked = 0
        n_violations = 0
        missing_params = []
        n_pymatgen_fallback = 0

        def _get_nn_info(site_idx):
            if nn_cache is not None and site_idx in nn_cache:
                return nn_cache[site_idx]
            if cnn is not None:
                return cnn.get_nn_info(structure, site_idx)
            return None

        for i, site in enumerate(structure):
            el_i = str(site.specie)
            oxi_i = oxi_states.get(el_i)
            if oxi_i is None:
                missing_params.append(el_i)
                continue

            try:
                nn_info = _get_nn_info(i)
                if nn_info is None:
                    continue
            except Exception:
                continue

            coord_number = len(nn_info)

            r_i, src_i = _get_shannon_radius(el_i, int(oxi_i), coord_number)
            if r_i is None:
                missing_params.append(f"{el_i}({oxi_i}+,CN={coord_number})")
                continue
            if src_i == "pymatgen":
                n_pymatgen_fallback += 1

            for nn in nn_info:
                nn_site = nn["site"]
                el_j = str(nn_site.specie)
                oxi_j = oxi_states.get(el_j)
                if oxi_j is None:
                    continue

                try:
                    nn_nn_info = _get_nn_info(nn["site_index"])
                    nn_coord = len(nn_nn_info) if nn_nn_info else coord_number
                except Exception:
                    nn_coord = coord_number  # fallback to central atom's CN
                r_j, src_j = _get_shannon_radius(el_j, int(oxi_j), nn_coord)
                if r_j is None:
                    continue
                if src_j == "pymatgen":
                    n_pymatgen_fallback += 1

                expected_dist = r_i + r_j
                actual_dist = site.distance(nn_site)
                if expected_dist > 0:
                    deviation = abs(actual_dist - expected_dist) / expected_dist
                else:
                    deviation = 0.0

                n_checked += 1
                is_ok = deviation <= SHANNON_TOLERANCE
                if not is_ok:
                    n_violations += 1

                # Only store violations to keep details manageable
                if not is_ok:
                    bond_checks.append({
                        "site_i": i, "el_i": el_i, "oxi_i": oxi_i,
                        "el_j": el_j, "oxi_j": oxi_j,
                        "expected": round(expected_dist, 3),
                        "actual": round(actual_dist, 3),
                        "deviation": round(deviation, 3),
                    })

            # Limit to first 50 sites for performance
            if i >= 49:
                break

        if n_checked == 0:
            return self._skip_no_params(
                "No bonds could be checked (missing Shannon radii parameters)",
                details={
                    "oxi_state_confidence": oxi_confidence,
                    "missing_params": list(set(missing_params))[:10],
                },
            )

        violation_fraction = n_violations / n_checked
        passed = violation_fraction <= 0.2  # ≤20% of bonds violate threshold

        details = {
            "n_bonds_checked": n_checked,
            "n_violations": n_violations,
            "violation_fraction": round(violation_fraction, 4),
            "tolerance": SHANNON_TOLERANCE,
            "n_pymatgen_fallback": n_pymatgen_fallback,
            "worst_violations": bond_checks[:10],
            "oxi_state_confidence": oxi_confidence,
            "oxi_state_method": oxi_assignment.get("method_used"),
        }

        compound_class = material_info.get("compound_class", "pure_oxide")
        if compound_class != "pure_oxide":
            details["compound_class_warning"] = (
                f"This {compound_class} contains non-oxide anions. "
                "Shannon radii for non-O²⁻ anion bonds may use different "
                "reference values than assumed here."
            )

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=confidence_score,
            score=round(violation_fraction, 4),
            details=details,
        )
