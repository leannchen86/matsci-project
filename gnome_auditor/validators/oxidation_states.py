"""Shared oxidation state assignment with multi-method consensus.

This is a critical module — all downstream validators depend on its output.
Two methods are tried:
  1. BVAnalyzer (structure-aware, ~34% success rate on GNoME P1 structures)
  2. Composition.oxi_state_guesses() (composition-only, broader empirical basis)

The consensus logic and tiebreaker rules are documented inline.

Mixed valence: BVAnalyzer can detect multiple oxidation states per element
(e.g., Fe²⁺/Fe³⁺ in magnetite). This information is preserved in the result
and flagged via has_mixed_valence. Downstream validators receive flattened
single-state assignments but the raw mixed-valence data is stored for
transparency and for charge-neutrality interpretation.
"""

from dataclasses import dataclass, field
from pymatgen.core import Structure, Composition
from pymatgen.analysis.bond_valence import BVAnalyzer


@dataclass
class OxidationStateResult:
    method_used: str      # bv_analyzer | oxi_state_guesses | both_agree | both_disagree | none
    oxi_states: dict | None  # element → oxidation state (e.g., {"Ca": 2, "Ti": 4, "O": -2})
    bv_analyzer_result: dict | None
    guesses_result: dict | None
    confidence: str       # both_agree | single_method | methods_disagree | no_assignment
    has_mixed_valence: bool = False
    mixed_valence_elements: list = field(default_factory=list)


def _try_bv_analyzer(structure: Structure) -> dict | None:
    """Try BVAnalyzer on the structure. Returns {element: oxi_state_or_list} or None.

    If an element has multiple oxidation states across sites (mixed valence),
    the value is a list of distinct states, e.g. {"Fe": [2, 3], "O": -2}.
    """
    try:
        bva = BVAnalyzer()
        oxi_struct = bva.get_oxi_state_decorated_structure(structure)
        element_oxi = {}
        for site in oxi_struct:
            sp = site.specie
            el = str(sp.element)
            oxi = sp.oxi_state
            if el in element_oxi and element_oxi[el] != oxi:
                if isinstance(element_oxi[el], list):
                    if oxi not in element_oxi[el]:
                        element_oxi[el].append(oxi)
                else:
                    if element_oxi[el] != oxi:
                        element_oxi[el] = [element_oxi[el], oxi]
            else:
                element_oxi[el] = oxi
        return element_oxi
    except Exception:
        return None


def _try_oxi_state_guesses(composition: Composition) -> dict | None:
    """Try Composition.oxi_state_guesses(). Returns {element: oxi_state} or None."""
    try:
        guesses = composition.oxi_state_guesses(max_sites=-1)
        if not guesses:
            return None
        top = guesses[0]
        element_oxi = {}
        for el, oxi in top.items():
            el = str(el)
            oxi = int(oxi)
            element_oxi[el] = oxi
        return element_oxi
    except Exception:
        return None


def _flatten_oxi(oxi_dict: dict) -> dict:
    """Flatten lists to single values (take first / most common).

    This is necessary for downstream validators that need one state per element.
    The unflattened data is preserved in bv_analyzer_result for transparency.
    """
    result = {}
    for el, val in oxi_dict.items():
        if isinstance(val, list):
            result[el] = val[0]
        else:
            result[el] = val
    return result


def _detect_mixed_valence(oxi_dict: dict) -> tuple[bool, list]:
    """Check if any elements have multiple oxidation states."""
    mixed_elements = []
    for el, val in oxi_dict.items():
        if isinstance(val, list) and len(val) > 1:
            mixed_elements.append({"element": el, "states": sorted(val)})
    return (len(mixed_elements) > 0, mixed_elements)


def _oxi_states_agree(bva: dict, guesses: dict) -> bool:
    """Check if two oxidation state assignments agree on all elements."""
    bva_flat = _flatten_oxi(bva)
    guesses_flat = _flatten_oxi(guesses)
    if set(bva_flat.keys()) != set(guesses_flat.keys()):
        return False
    return all(bva_flat[el] == guesses_flat[el] for el in bva_flat)


def assign_oxidation_states(structure: Structure) -> OxidationStateResult:
    """Assign oxidation states using multi-method consensus.

    Confidence labels (renamed for clarity — these describe the method outcome,
    not a guarantee of correctness):
      1. Both agree → confidence="both_agree"
      2. Both succeed but disagree → confidence="methods_disagree",
         use oxi_state_guesses (broader empirical basis), store both
      3. Only one method succeeds → confidence="single_method"
      4. Neither succeeds → confidence="no_assignment"

    Mixed valence: if BVAnalyzer detects multiple states per element,
    this is preserved in has_mixed_valence and mixed_valence_elements.
    Downstream validators get flattened single-state assignments.
    """
    composition = structure.composition

    bva_result = _try_bv_analyzer(structure)
    guesses_result = _try_oxi_state_guesses(composition)

    # Detect mixed valence from BVAnalyzer
    has_mixed = False
    mixed_els = []
    if bva_result is not None:
        has_mixed, mixed_els = _detect_mixed_valence(bva_result)

    if bva_result is not None and guesses_result is not None:
        if _oxi_states_agree(bva_result, guesses_result):
            return OxidationStateResult(
                method_used="both_agree",
                oxi_states=_flatten_oxi(bva_result),
                bv_analyzer_result=bva_result,
                guesses_result=guesses_result,
                confidence="both_agree",
                has_mixed_valence=has_mixed,
                mixed_valence_elements=mixed_els,
            )
        else:
            return OxidationStateResult(
                method_used="both_disagree",
                oxi_states=_flatten_oxi(guesses_result),
                bv_analyzer_result=bva_result,
                guesses_result=guesses_result,
                confidence="methods_disagree",
                has_mixed_valence=has_mixed,
                mixed_valence_elements=mixed_els,
            )
    elif bva_result is not None:
        return OxidationStateResult(
            method_used="bv_analyzer",
            oxi_states=_flatten_oxi(bva_result),
            bv_analyzer_result=bva_result,
            guesses_result=None,
            confidence="single_method",
            has_mixed_valence=has_mixed,
            mixed_valence_elements=mixed_els,
        )
    elif guesses_result is not None:
        return OxidationStateResult(
            method_used="oxi_state_guesses",
            oxi_states=_flatten_oxi(guesses_result),
            bv_analyzer_result=None,
            guesses_result=guesses_result,
            confidence="single_method",
        )
    else:
        return OxidationStateResult(
            method_used="none",
            oxi_states=None,
            bv_analyzer_result=None,
            guesses_result=None,
            confidence="no_assignment",
        )
