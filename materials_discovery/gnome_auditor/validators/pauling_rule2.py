"""Tier 1: Pauling's Second Rule (Electrostatic Valence Principle).

For each anion (O²⁻), the sum of electrostatic bond strengths from coordinating
cations should approximately equal the anion's valence (2 for O²⁻).

Electrostatic bond strength = cation_oxidation_state / coordination_number
"""

from pymatgen.core import Structure

from gnome_auditor.config import PAULING_R2_TOLERANCE, OXI_CONFIDENCE_MAP
from gnome_auditor.validators.base import BaseValidator, ValidationResult


class PaulingRule2Validator(BaseValidator):
    check_name = "pauling_rule2"
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

        # Find oxygen sites
        o_indices = [i for i, site in enumerate(structure) if str(site.specie) == "O"]
        if not o_indices:
            return self._skip_not_applicable("No oxygen sites found in structure")

        # Use pre-computed neighbor cache or compute on the fly
        if nn_cache is None:
            from pymatgen.analysis.local_env import CrystalNN
            try:
                cnn = CrystalNN()
            except Exception as e:
                return self._error(f"CrystalNN initialization failed: {e}")
        else:
            cnn = None

        def _get_nn_info(site_idx):
            if nn_cache is not None and site_idx in nn_cache:
                return nn_cache[site_idx]
            if cnn is not None:
                return cnn.get_nn_info(structure, site_idx)
            return None

        expected_valence = 2.0  # |valence of O²⁻|
        site_results = []
        n_checked = 0
        n_violations = 0

        for o_idx in o_indices:
            try:
                nn_info = _get_nn_info(o_idx)
                if nn_info is None:
                    continue
            except Exception:
                continue

            # Sum electrostatic bond strengths from coordinating cations
            bond_strength_sum = 0.0
            cation_contributions = []

            for nn in nn_info:
                nn_el = str(nn["site"].specie)
                oxi = oxi_states.get(nn_el)
                if oxi is None or oxi <= 0:
                    continue  # skip anions and unknown

                # Get coordination number of this cation by ANIONS only
                # (Pauling's rule defines CN as coordination by anions)
                try:
                    nn_idx = nn["site_index"]
                    cation_nn = _get_nn_info(nn_idx)
                    cation_cn = sum(
                        1 for n in cation_nn
                        if oxi_states.get(str(n["site"].specie), 0) < 0
                    )
                except Exception:
                    cation_cn = 0

                if cation_cn > 0:
                    strength = oxi / cation_cn
                    bond_strength_sum += strength
                    cation_contributions.append({
                        "element": nn_el, "oxi_state": oxi,
                        "cn": cation_cn, "strength": round(strength, 3),
                    })

            if not cation_contributions:
                continue

            n_checked += 1
            deviation = abs(bond_strength_sum - expected_valence) / expected_valence
            is_ok = deviation <= PAULING_R2_TOLERANCE

            if not is_ok:
                n_violations += 1

            site_results.append({
                "o_site_index": o_idx,
                "bond_strength_sum": round(bond_strength_sum, 3),
                "expected": expected_valence,
                "deviation": round(deviation, 3),
                "passed": is_ok,
                "cation_contributions": cation_contributions,
            })

            # Limit for performance
            if n_checked >= 50:
                break

        if n_checked == 0:
            return self._skip_no_params(
                "No oxygen sites could be analyzed",
                details={"oxi_state_confidence": oxi_confidence},
            )

        violation_fraction = n_violations / n_checked
        passed = violation_fraction <= 0.25  # ≤25% of O sites violate

        details = {
            "n_oxygen_sites_checked": n_checked,
            "n_violations": n_violations,
            "violation_fraction": round(violation_fraction, 4),
            "tolerance": PAULING_R2_TOLERANCE,
            "worst_sites": sorted(
                [s for s in site_results if not s["passed"]],
                key=lambda x: x["deviation"],
                reverse=True,
            )[:5],
            "oxi_state_confidence": oxi_confidence,
            "oxi_state_method": oxi_assignment.get("method_used"),
        }

        compound_class = material_info.get("compound_class", "pure_oxide")
        if compound_class != "pure_oxide":
            details["compound_class_warning"] = (
                f"This {compound_class} contains non-oxide anions. "
                "Only O²⁻ sites are checked (expected valence sum = 2). "
                "Non-oxide anion sites are not evaluated."
            )

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=confidence_score,
            score=round(violation_fraction, 4),
            details=details,
        )
