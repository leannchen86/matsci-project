"""Tier 2: Space group plausibility vs experimental distributions.

Checks whether the claimed space group for a GNoME structure is commonly
observed in experimental databases for similar chemical systems.

Independence: semi_independent (experimental distribution data)
"""

from pymatgen.core import Structure

from gnome_auditor.config import SPACEGROUP_MIN_FRACTION
from gnome_auditor.validators.base import BaseValidator, ValidationResult


class SpaceGroupValidator(BaseValidator):
    check_name = "space_group"
    tier = 2
    independence = "semi_independent"

    def __init__(self, conn=None):
        """Initialize with optional DB connection for space group stats."""
        self._conn = conn

    def validate(self, structure: Structure, material_info: dict,
                 oxi_assignment: dict | None = None) -> ValidationResult:
        sg_number = material_info.get("space_group_number")
        if sg_number is None:
            return self._skip_no_params("No space group number available")

        # Build chemsys key (sorted elements joined by -)
        elements = material_info.get("elements", [])
        if isinstance(elements, str):
            import json
            elements = json.loads(elements)
        chemsys = "-".join(sorted(elements))

        if self._conn is None:
            return self._skip_no_params(
                "No database connection for space group statistics",
            )

        # Query space group stats for this chemical system
        rows = self._conn.execute(
            "SELECT * FROM mp_spacegroup_stats WHERE chemsys = ? ORDER BY count DESC",
            (chemsys,)
        ).fetchall()

        if not rows:
            return self._skip_no_params(
                f"No experimental space group data for chemical system {chemsys}",
                details={"chemsys": chemsys, "space_group_number": sg_number},
            )

        stats = [dict(r) for r in rows]
        total_entries = sum(s["count"] for s in stats)

        # Find this space group in the distribution
        matching = [s for s in stats if s["space_group_number"] == sg_number]
        if matching:
            fraction = matching[0]["fraction"]
            count = matching[0]["count"]
        else:
            fraction = 0.0
            count = 0

        # Is this space group plausible?
        passed = fraction >= SPACEGROUP_MIN_FRACTION

        # Top space groups for context
        top_sgs = stats[:5]

        return self._make_result(
            status="completed",
            passed=passed,
            confidence=0.7,  # semi-independent check
            score=round(fraction, 4),
            details={
                "chemsys": chemsys,
                "space_group_number": sg_number,
                "space_group": material_info.get("space_group"),
                "fraction_in_experimental": round(fraction, 4),
                "count_in_experimental": count,
                "total_experimental_entries": total_entries,
                "min_fraction_threshold": SPACEGROUP_MIN_FRACTION,
                "top_experimental_space_groups": top_sgs,
            },
        )
