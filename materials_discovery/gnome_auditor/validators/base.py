"""Base classes for GNoME Auditor validators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class ValidationResult:
    """Result of a single validation check on a single material."""
    check_name: str
    tier: int                           # 1 or 2
    independence: str                   # fully_independent | semi_independent | computational_consistency
    status: str                         # completed | skipped_no_params | skipped_not_applicable | error
    passed: bool | None = None          # only meaningful when status="completed"
    confidence: float = 0.0             # 0.0–1.0, inherits from oxi_state confidence when applicable
    score: float | None = None          # check-specific numeric value
    details: dict = field(default_factory=dict)
    error_message: str | None = None

    def to_db_dict(self, material_id: str) -> dict:
        """Convert to dict for database insertion."""
        return {
            "material_id": material_id,
            "check_name": self.check_name,
            "tier": self.tier,
            "independence": self.independence,
            "status": self.status,
            "passed": self.passed,
            "confidence": self.confidence,
            "score": self.score,
            "details": self.details,
            "error_message": self.error_message,
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> dict:
        return asdict(self)


class BaseValidator(ABC):
    """Abstract base class for all validators."""

    @property
    @abstractmethod
    def check_name(self) -> str:
        ...

    @property
    @abstractmethod
    def tier(self) -> int:
        ...

    @property
    @abstractmethod
    def independence(self) -> str:
        ...

    @abstractmethod
    def validate(self, structure, material_info: dict,
                 oxi_assignment: dict | None = None,
                 nn_cache: dict | None = None) -> ValidationResult:
        """Run the validation check.

        Args:
            structure: pymatgen Structure object (from CIF)
            material_info: dict from materials table
            oxi_assignment: dict from oxidation_state_assignments table (may be None)
            nn_cache: optional pre-computed CrystalNN neighbor info per site index
                      {site_idx: [nn_info_list]} — shared across validators to
                      avoid redundant Voronoi decomposition

        Returns:
            ValidationResult
        """
        ...

    def _make_result(self, *, status: str, passed: bool | None = None,
                     confidence: float = 0.0, score: float | None = None,
                     details: dict | None = None,
                     error_message: str | None = None) -> ValidationResult:
        """Helper to construct a ValidationResult with this validator's metadata."""
        return ValidationResult(
            check_name=self.check_name,
            tier=self.tier,
            independence=self.independence,
            status=status,
            passed=passed,
            confidence=confidence,
            score=score,
            details=details or {},
            error_message=error_message,
        )

    def _skip_no_params(self, reason: str, details: dict | None = None) -> ValidationResult:
        """Helper for when required parameters are unavailable."""
        return self._make_result(
            status="skipped_no_params",
            details={"skip_reason": reason, **(details or {})},
        )

    def _skip_not_applicable(self, reason: str, details: dict | None = None) -> ValidationResult:
        """Helper for when the check doesn't apply to this material."""
        return self._make_result(
            status="skipped_not_applicable",
            details={"skip_reason": reason, **(details or {})},
        )

    def _error(self, error_message: str, details: dict | None = None) -> ValidationResult:
        """Helper for when the check encounters an error."""
        return self._make_result(
            status="error",
            error_message=error_message,
            details=details or {},
        )
