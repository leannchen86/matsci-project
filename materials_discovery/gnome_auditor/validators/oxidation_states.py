"""Shared oxidation state assignment with multi-method consensus.

This is a critical module — all downstream validators depend on its output.
Two methods are tried:
  1. BVAnalyzer (structure-aware, ~34% success rate on GNoME P1 structures)
  2. Composition.oxi_state_guesses() (composition-only, broader empirical basis)

The consensus logic and tiebreaker rules are documented inline.
"""

from dataclasses import dataclass
from pymatgen.core import Structure, Composition
from pymatgen.analysis.bond_valence import BVAnalyzer


@dataclass
class OxidationStateResult:
    method_used: str      # bv_analyzer | oxi_state_guesses | both_agree | both_disagree | none
    oxi_states: dict | None  # element → oxidation state (e.g., {"Ca": 2, "Ti": 4, "O": -2})
    bv_analyzer_result: dict | None
    guesses_result: dict | None
    confidence: str       # high | medium | low | none


def _try_bv_analyzer(structure: Structure) -> dict | None:
    """Try BVAnalyzer on the structure. Returns {element: oxi_state} or None."""
    try:
        bva = BVAnalyzer()
        oxi_struct = bva.get_oxi_state_decorated_structure(structure)
        # Extract per-element oxidation states
        element_oxi = {}
        for site in oxi_struct:
            sp = site.specie
            el = str(sp.element)
            oxi = sp.oxi_state
            if el in element_oxi and element_oxi[el] != oxi:
                # Mixed valence detected — store as list
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
        # Top guess is a dict: {element_str: oxidation_state_value}
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
    """Flatten lists to single values where possible (take first)."""
    result = {}
    for el, val in oxi_dict.items():
        if isinstance(val, list):
            result[el] = val[0]  # take most common / first
        else:
            result[el] = val
    return result


def _oxi_states_agree(bva: dict, guesses: dict) -> bool:
    """Check if two oxidation state assignments agree on all elements."""
    bva_flat = _flatten_oxi(bva)
    guesses_flat = _flatten_oxi(guesses)
    if set(bva_flat.keys()) != set(guesses_flat.keys()):
        return False
    return all(bva_flat[el] == guesses_flat[el] for el in bva_flat)


def assign_oxidation_states(structure: Structure) -> OxidationStateResult:
    """Assign oxidation states using multi-method consensus.

    Tiebreaker rules:
      1. Both agree → use shared result, confidence="high"
      2. Both succeed but disagree → use oxi_state_guesses (broader empirical basis),
         confidence="low", store both for transparency
      3. Only BVAnalyzer succeeds → use it, confidence="medium"
      4. Only oxi_state_guesses succeeds → use it, confidence="medium"
      5. Neither succeeds → confidence="none"
    """
    composition = structure.composition

    bva_result = _try_bv_analyzer(structure)
    guesses_result = _try_oxi_state_guesses(composition)

    if bva_result is not None and guesses_result is not None:
        if _oxi_states_agree(bva_result, guesses_result):
            return OxidationStateResult(
                method_used="both_agree",
                oxi_states=_flatten_oxi(bva_result),
                bv_analyzer_result=bva_result,
                guesses_result=guesses_result,
                confidence="high",
            )
        else:
            # Disagree — use guesses (broader empirical basis)
            return OxidationStateResult(
                method_used="both_disagree",
                oxi_states=_flatten_oxi(guesses_result),
                bv_analyzer_result=bva_result,
                guesses_result=guesses_result,
                confidence="low",
            )
    elif bva_result is not None:
        return OxidationStateResult(
            method_used="bv_analyzer",
            oxi_states=_flatten_oxi(bva_result),
            bv_analyzer_result=bva_result,
            guesses_result=None,
            confidence="medium",
        )
    elif guesses_result is not None:
        return OxidationStateResult(
            method_used="oxi_state_guesses",
            oxi_states=_flatten_oxi(guesses_result),
            bv_analyzer_result=None,
            guesses_result=guesses_result,
            confidence="medium",
        )
    else:
        return OxidationStateResult(
            method_used="none",
            oxi_states=None,
            bv_analyzer_result=None,
            guesses_result=None,
            confidence="none",
        )
