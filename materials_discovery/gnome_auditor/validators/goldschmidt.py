"""Tier 1: Goldschmidt tolerance factor for ABO3 perovskites.

t = (r_A + r_O) / (sqrt(2) * (r_B + r_O))

Stable perovskites typically have 0.71 < t < 1.05.
Only applicable to materials classified as ABO3.
"""

import math

from pymatgen.core import Structure, Composition

from gnome_auditor.config import GOLDSCHMIDT_MIN, GOLDSCHMIDT_MAX, OXI_CONFIDENCE_MAP
from gnome_auditor.validators.base import BaseValidator, ValidationResult
from gnome_auditor.validators.shannon_radii import SHANNON_RADII


def _get_radius_for_perovskite(element: str, oxi_state: int, site: str) -> float | None:
    """Get Shannon radius appropriate for perovskite sites.

    A-site: typically 12-coordinated (or 8)
    B-site: typically 6-coordinated
    O: 6-coordinated
    """
    if site == "A":
        for cn in [12, 8, 6]:
            key = (element, oxi_state, cn)
            if key in SHANNON_RADII:
                return SHANNON_RADII[key]
    elif site == "B":
        for cn in [6, 4]:
            key = (element, oxi_state, cn)
            if key in SHANNON_RADII:
                return SHANNON_RADII[key]
    elif site == "O":
        return SHANNON_RADII.get((element, oxi_state, 6), 1.40)
    return None


class GoldschmidtValidator(BaseValidator):
    check_name = "goldschmidt"
    tier = 1
    independence = "fully_independent"

    def validate(self, structure: Structure, material_info: dict,
                 oxi_assignment: dict | None = None) -> ValidationResult:
        # Only applicable to ABO3 perovskites
        oxide_type = material_info.get("oxide_type")
        if oxide_type != "ABO3":
            return self._skip_not_applicable(
                f"Not an ABO3 perovskite (oxide_type={oxide_type})",
            )

        if oxi_assignment is None or oxi_assignment["confidence"] == "no_assignment":
            return self._skip_no_params(
                "No oxidation state assignment available",
                details={"oxi_state_confidence": "no_assignment"},
            )

        oxi_states = oxi_assignment["oxi_states"]
        oxi_confidence = oxi_assignment["confidence"]
        confidence_score = OXI_CONFIDENCE_MAP.get(oxi_confidence, 0.0)

        # Identify A and B cations (O is the anion)
        comp = Composition(material_info["reduced_formula"])
        elements_amounts = {}
        for el, amt in comp.items():
            elements_amounts[str(el)] = amt

        cations = {el: amt for el, amt in elements_amounts.items() if el != "O"}
        if len(cations) != 2:
            return self._skip_not_applicable(
                f"Expected 2 cations, found {len(cations)}",
            )

        # In ABO3: A has larger radius (typically lower oxidation state),
        # B has smaller radius (typically higher oxidation state)
        cation_list = list(cations.keys())
        oxi_0 = oxi_states.get(cation_list[0])
        oxi_1 = oxi_states.get(cation_list[1])

        if oxi_0 is None or oxi_1 is None:
            return self._skip_no_params(
                "Missing oxidation states for cations",
                details={"oxi_state_confidence": oxi_confidence},
            )

        # A-site has lower oxi state (or equal, then larger radius)
        r_a_0 = _get_radius_for_perovskite(cation_list[0], int(oxi_0), "A")
        r_a_1 = _get_radius_for_perovskite(cation_list[1], int(oxi_1), "A")
        r_b_0 = _get_radius_for_perovskite(cation_list[0], int(oxi_0), "B")
        r_b_1 = _get_radius_for_perovskite(cation_list[1], int(oxi_1), "B")

        # Try both assignments and pick the one that makes more chemical sense
        # (A = larger cation, B = smaller cation)
        assignments = []
        if r_a_0 is not None and r_b_1 is not None:
            assignments.append((cation_list[0], oxi_0, r_a_0, cation_list[1], oxi_1, r_b_1))
        if r_a_1 is not None and r_b_0 is not None:
            assignments.append((cation_list[1], oxi_1, r_a_1, cation_list[0], oxi_0, r_b_0))

        if not assignments:
            return self._skip_no_params(
                "Shannon radii not available for perovskite coordination",
                details={
                    "cations": cation_list,
                    "oxi_states": {c: oxi_states.get(c) for c in cation_list},
                    "oxi_state_confidence": oxi_confidence,
                },
            )

        r_O = 1.40  # Shannon radius for O²⁻ in 6-coordination

        best_result = None
        for a_el, a_oxi, r_A, b_el, b_oxi, r_B in assignments:
            t = (r_A + r_O) / (math.sqrt(2) * (r_B + r_O))
            in_range = GOLDSCHMIDT_MIN <= t <= GOLDSCHMIDT_MAX

            result = {
                "a_site": {"element": a_el, "oxi_state": a_oxi, "radius": r_A},
                "b_site": {"element": b_el, "oxi_state": b_oxi, "radius": r_B},
                "r_O": r_O,
                "tolerance_factor": round(t, 4),
                "in_stable_range": in_range,
                "stable_range": [GOLDSCHMIDT_MIN, GOLDSCHMIDT_MAX],
            }

            # Prefer assignment where A-site has larger radius
            if best_result is None or r_A > best_result["a_site"]["radius"]:
                best_result = result

        t = best_result["tolerance_factor"]
        passed = best_result["in_stable_range"]

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=confidence_score,
            score=t,
            details={
                **best_result,
                "oxi_state_confidence": oxi_confidence,
                "oxi_state_method": oxi_assignment.get("method_used"),
            },
        )
