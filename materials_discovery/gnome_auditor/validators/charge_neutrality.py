"""Tier 1: Charge neutrality check — oxidation states must sum to zero."""

from gnome_auditor.config import OXI_CONFIDENCE_MAP
from gnome_auditor.validators.base import BaseValidator, ValidationResult


class ChargeNeutralityValidator(BaseValidator):
    check_name = "charge_neutrality"
    tier = 1
    independence = "fully_independent"

    def validate(self, structure, material_info: dict,
                 oxi_assignment: dict | None = None) -> ValidationResult:
        if oxi_assignment is None or oxi_assignment["confidence"] == "no_assignment":
            return self._skip_no_params(
                "No oxidation state assignment available",
                details={"oxi_state_confidence": "none"},
            )

        oxi_states = oxi_assignment["oxi_states"]
        oxi_confidence = oxi_assignment["confidence"]
        confidence_score = OXI_CONFIDENCE_MAP.get(oxi_confidence, 0.0)

        # Sum oxidation states weighted by composition
        composition = structure.composition
        total_charge = 0.0
        element_charges = {}

        for el, amt in composition.items():
            el_str = str(el)
            if el_str not in oxi_states:
                return self._skip_no_params(
                    f"No oxidation state for element {el_str}",
                    details={
                        "oxi_state_confidence": oxi_confidence,
                        "missing_element": el_str,
                    },
                )
            oxi = oxi_states[el_str]
            charge = oxi * amt
            total_charge += charge
            element_charges[el_str] = {"oxi_state": oxi, "count": amt, "charge": charge}

        passed = abs(total_charge) < 0.01  # effectively zero

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=confidence_score,
            score=total_charge,
            details={
                "total_charge": total_charge,
                "element_charges": element_charges,
                "oxi_state_confidence": oxi_confidence,
                "oxi_state_method": oxi_assignment.get("method_used"),
            },
        )
