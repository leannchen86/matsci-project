"""Tier 2: Bond Valence Sum (BVS) per site and Global Instability Index (GII).

BVS uses empirical parameters from ICSD to compute the actual valence at each site
based on bond distances. The Global Instability Index is the RMS deviation of
BVS from expected oxidation states across all sites.

Uses pymatgen's calculate_bv_sum which relies on the Brown-Altermatt BV parameters.

Independence: semi_independent (ICSD-derived parameters applied to DFT-relaxed geometry)
"""

import math

from pymatgen.core import Structure, Species
from pymatgen.analysis.bond_valence import calculate_bv_sum

from gnome_auditor.config import BVS_TOLERANCE, GII_REFERENCE_ICSD, OXI_CONFIDENCE_MAP
from gnome_auditor.validators.base import BaseValidator, ValidationResult


def _decorate_structure(structure: Structure, oxi_states: dict) -> Structure:
    """Add oxidation states to structure sites for BVS calculation."""
    new_species = []
    for site in structure:
        el = str(site.specie)
        oxi = oxi_states.get(el, 0)
        new_species.append(Species(el, oxi))
    decorated = structure.copy()
    for i, sp in enumerate(new_species):
        decorated[i] = sp
    return decorated


class BondValenceSumValidator(BaseValidator):
    check_name = "bond_valence_sum"
    tier = 2
    independence = "semi_independent"

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

        # Decorate structure with oxidation states
        try:
            dec_struct = _decorate_structure(structure, oxi_states)
        except Exception as e:
            return self._error(
                f"Could not assign oxidation states to structure: {e}",
                details={"oxi_state_confidence": oxi_confidence},
            )

        # Compute BVS per site using pymatgen's calculate_bv_sum
        site_results = []
        n_computed = 0
        sum_sq_dev = 0.0

        for i, site in enumerate(dec_struct):
            el = str(site.specie.element)
            signed_oxi = oxi_states.get(el, 0)
            if signed_oxi == 0:
                continue

            try:
                nn_list = dec_struct.get_neighbors(site, r=4.0)
                if not nn_list:
                    continue
                bvs = calculate_bv_sum(site, nn_list)
            except Exception:
                continue

            # BVS is signed (negative for anions), compare to signed oxi state
            deviation = abs(bvs - signed_oxi)
            expected_abs = abs(signed_oxi)
            relative_dev = deviation / expected_abs if expected_abs > 0 else 0.0
            sum_sq_dev += deviation ** 2
            n_computed += 1

            site_results.append({
                "site_index": i,
                "element": el,
                "oxi_state": signed_oxi,
                "bvs": round(bvs, 3),
                "expected": signed_oxi,
                "deviation": round(deviation, 3),
                "relative_deviation": round(relative_dev, 3),
            })

        if n_computed == 0:
            return self._skip_no_params(
                "Could not compute BVS for any sites (missing BV parameters)",
                details={"oxi_state_confidence": oxi_confidence},
            )

        # Global Instability Index
        gii = math.sqrt(sum_sq_dev / n_computed)
        # passed is legacy — GII is a continuous metric, not a binary judgment
        passed = gii < GII_REFERENCE_ICSD

        worst_sites = sorted(site_results, key=lambda x: x["deviation"], reverse=True)[:5]
        n_bad_sites = sum(1 for s in site_results if s["relative_deviation"] > BVS_TOLERANCE)

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=confidence_score,
            score=round(gii, 4),
            details={
                "global_instability_index": round(gii, 4),
                "gii_reference_icsd": GII_REFERENCE_ICSD,
                "n_sites_analyzed": n_computed,
                "n_sites_total": len(dec_struct),
                "n_sites_above_tolerance": n_bad_sites,
                "bvs_tolerance": BVS_TOLERANCE,
                "worst_sites": worst_sites,
                "oxi_state_confidence": oxi_confidence,
                "oxi_state_method": oxi_assignment.get("method_used"),
            },
        )
