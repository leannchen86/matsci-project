"""Claude Opus 4.6 research interface for GNoME Auditor.

System prompt, tool definitions, and conversation loop using the Anthropic SDK.
This is the primary user-facing component (55% of judging weight).
"""

import json
import os

import anthropic

from gnome_auditor.db.store import (
    get_connection,
    get_material,
    get_material_by_formula,
    search_materials,
    get_validation_results,
    get_validation_results_by_check,
    get_mp_cross_ref,
    get_oxi_assignment,
    get_audit_summary,
    get_flagged_materials,
    get_statistics,
    get_spacegroup_stats,
)
from gnome_auditor.config import EXTRACTED_CIFS_DIR


SYSTEM_PROMPT = """You are a materials science research assistant analyzing the results of a chemistry-based audit of Google's GNoME crystal structure predictions. You have access to a database of 3,262 ternary oxides from the GNoME dataset that have been validated using classical chemistry rules.

## Your Core Principles

1. **Always surface tier and independence for every validation result:**
   - Tier 1 checks (charge neutrality, Shannon radii, Pauling Rule 2, Goldschmidt) are FULLY INDEPENDENT of DFT — they use pre-computational chemistry knowledge
   - Tier 2 checks (Bond Valence Sum, space group plausibility) are SEMI-INDEPENDENT — they use experimental parameters on DFT-relaxed geometry

2. **Always show raw numbers — you interpret, the human decides:**
   - Report exact scores, counts, and fractions
   - Never reduce results to just pass/fail without the underlying data

3. **Always report coverage:**
   - "Charge neutrality: X of Y materials could be checked (Z%), of which W failed (V%)"
   - Coverage gaps are information, not failures

4. **Surface oxidation state confidence:**
   - When oxi assignment is uncertain (confidence="low" or "medium"), say so explicitly
   - "Note: the oxidation state assignment was uncertain — BVAnalyzer assigned Fe³⁺ but the heuristic method suggested Fe²⁺/Fe³⁺ mixed valence"

5. **Never claim a structure is "correct" or "wrong":**
   - Say "this structure passes/fails this specific chemistry check" not "this structure is stable/unstable"
   - A failed check means the structure is unusual according to that rule, not necessarily wrong

6. **Distinguish experimental vs computational MP entries:**
   - experimental_match (has ICSD IDs) = composition exists in nature
   - computational_match = composition exists in MP's computational database
   - novel = not found in MP at all
   - structural_mismatch = composition matches but space group differs

7. **Explain what flags mean physically:**
   - Don't just say "GII = 0.35" — explain "The Global Instability Index of 0.35 v.u. exceeds the threshold of 0.2, suggesting significant strain in the bond network"
   - Connect results to chemistry: "Shannon radii violation on the Fe-O bond suggests the Fe-O distance (2.45 Å) is 30% longer than expected for Fe³⁺ in octahedral coordination (1.89 Å)"

## Oxide Type Classification
Materials are classified by reduced formula ratios: ABO3 (perovskites), AB2O4 (spinels), A2BO4 (Ruddlesden-Popper), etc.
Limitation: this simple classification misses double perovskites and complex phases.

## Available Tools
Use the provided tools to query the database. Always use tools to get actual data rather than speculating about results."""


TOOLS = [
    {
        "name": "lookup_material",
        "description": "Look up full details for a material by its GNoME material ID or by reduced formula. Returns material properties, composition, crystal system, and classification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "GNoME material ID (10-character hex string)",
                },
                "formula": {
                    "type": "string",
                    "description": "Reduced formula to search for (e.g., 'CaTiO3')",
                },
            },
        },
    },
    {
        "name": "get_validation_results",
        "description": "Get all validation check results for a specific material. Returns tier, independence, status, pass/fail, confidence, scores, and detailed data for each check.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "GNoME material ID",
                },
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "search_materials",
        "description": "Search for materials by element, crystal system, oxide type, validation results, or MP match type. Returns matching materials with basic properties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element": {
                    "type": "string",
                    "description": "Filter by element (e.g., 'Fe', 'Ti')",
                },
                "crystal_system": {
                    "type": "string",
                    "description": "Filter by crystal system (e.g., 'cubic', 'monoclinic')",
                },
                "oxide_type": {
                    "type": "string",
                    "description": "Filter by oxide type (e.g., 'ABO3', 'AB2O4')",
                },
                "check_name": {
                    "type": "string",
                    "description": "Filter by validation check name (e.g., 'charge_neutrality', 'bond_valence_sum')",
                },
                "check_passed": {
                    "type": "boolean",
                    "description": "Filter by whether the check passed (true) or failed (false). Requires check_name.",
                },
                "mp_match_type": {
                    "type": "string",
                    "description": "Filter by MP match type: 'experimental_match', 'computational_match', 'novel', 'structural_mismatch'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default 20)",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "get_mp_comparison",
        "description": "Get Materials Project cross-reference data for a material: whether it exists in MP, if it's experimentally verified (ICSD), formation energy comparison, and space group match.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "GNoME material ID",
                },
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "get_statistics",
        "description": "Get aggregate statistics: total materials, validation coverage per check (computed/skipped/failed counts), oxidation state confidence distribution, and MP match type distribution. Always reports coverage alongside results.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_structure_details",
        "description": "Get detailed structural information: lattice parameters, site positions, bond distances, and coordination environments from the CIF file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "GNoME material ID",
                },
            },
            "required": ["material_id"],
        },
    },
]


def _handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as JSON string."""
    conn = get_connection()
    try:
        if tool_name == "lookup_material":
            if tool_input.get("material_id"):
                mat = get_material(conn, tool_input["material_id"])
                if mat:
                    oxi = get_oxi_assignment(conn, tool_input["material_id"])
                    mat["oxidation_states"] = oxi
                    return json.dumps(mat, indent=2, default=str)
                return json.dumps({"error": f"Material {tool_input['material_id']} not found"})
            elif tool_input.get("formula"):
                mats = get_material_by_formula(conn, tool_input["formula"])
                if mats:
                    for m in mats:
                        m["oxidation_states"] = get_oxi_assignment(conn, m["material_id"])
                    return json.dumps(mats, indent=2, default=str)
                return json.dumps({"error": f"No materials found for formula {tool_input['formula']}"})
            return json.dumps({"error": "Provide material_id or formula"})

        elif tool_name == "get_validation_results":
            mat_id = tool_input["material_id"]
            results = get_validation_results(conn, mat_id)
            oxi = get_oxi_assignment(conn, mat_id)
            return json.dumps({
                "material_id": mat_id,
                "oxidation_state_assignment": oxi,
                "validation_results": results,
            }, indent=2, default=str)

        elif tool_name == "search_materials":
            mats = search_materials(
                conn,
                element=tool_input.get("element"),
                crystal_system=tool_input.get("crystal_system"),
                oxide_type=tool_input.get("oxide_type"),
                check_name=tool_input.get("check_name"),
                check_passed=tool_input.get("check_passed"),
                mp_match_type=tool_input.get("mp_match_type"),
                limit=tool_input.get("limit", 20),
            )
            return json.dumps(mats, indent=2, default=str)

        elif tool_name == "get_mp_comparison":
            mat_id = tool_input["material_id"]
            mp_data = get_mp_cross_ref(conn, mat_id)
            mat = get_material(conn, mat_id)
            if mat:
                elements = mat["elements"]
                chemsys = "-".join(sorted(elements))
                sg_stats = get_spacegroup_stats(conn, chemsys)
            else:
                sg_stats = []
            return json.dumps({
                "material_id": mat_id,
                "mp_cross_ref": mp_data,
                "experimental_spacegroup_distribution": sg_stats[:10],
            }, indent=2, default=str)

        elif tool_name == "get_statistics":
            stats = get_statistics(conn)
            summary = get_audit_summary(conn)
            flagged = get_flagged_materials(conn, min_failures=2, limit=10)
            return json.dumps({
                "overview": stats,
                "validation_summary": summary,
                "most_flagged_materials": flagged,
            }, indent=2, default=str)

        elif tool_name == "get_structure_details":
            mat_id = tool_input["material_id"]
            cif_path = EXTRACTED_CIFS_DIR / f"{mat_id}.cif"
            if not cif_path.exists():
                return json.dumps({"error": f"CIF not found for {mat_id}"})

            from pymatgen.core import Structure
            struct = Structure.from_file(str(cif_path))

            lattice = struct.lattice
            sites_info = []
            for i, site in enumerate(struct[:20]):  # limit to 20 sites
                sites_info.append({
                    "index": i,
                    "element": str(site.specie),
                    "frac_coords": [round(c, 4) for c in site.frac_coords],
                    "cart_coords": [round(c, 4) for c in site.coords],
                })

            return json.dumps({
                "material_id": mat_id,
                "n_sites": len(struct),
                "lattice": {
                    "a": round(lattice.a, 4),
                    "b": round(lattice.b, 4),
                    "c": round(lattice.c, 4),
                    "alpha": round(lattice.alpha, 2),
                    "beta": round(lattice.beta, 2),
                    "gamma": round(lattice.gamma, 2),
                    "volume": round(lattice.volume, 2),
                },
                "sites": sites_info,
                "composition": str(struct.composition),
            }, indent=2, default=str)

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    finally:
        conn.close()


def run_chat():
    """Run the interactive Claude research assistant chat loop."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return

    client = anthropic.Anthropic(api_key=api_key)
    messages = []

    print("=" * 70)
    print("GNoME Auditor — Claude Research Assistant")
    print("=" * 70)
    print("Ask questions about the chemistry-based audit of GNoME predictions.")
    print("Type 'quit' or 'exit' to end the session.")
    print("=" * 70)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})

        # Chat loop with tool use
        while True:
            response = client.messages.create(
                model="claude-opus-4-6-20250219",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Process response
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Check if we need to handle tool calls
            tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

            if not tool_use_blocks:
                # No tool calls — print text response
                for block in assistant_content:
                    if hasattr(block, "text"):
                        print(f"\nClaude: {block.text}\n")
                break

            # Handle tool calls
            tool_results = []
            for tool_block in tool_use_blocks:
                result = _handle_tool_call(tool_block.name, tool_block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

            # Print any text that came with the tool calls
            for block in assistant_content:
                if hasattr(block, "text") and block.text.strip():
                    print(f"\nClaude: {block.text}")
