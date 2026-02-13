"""Gold data calibration analysis: do chemistry-rule scores predict synthesizability?

Compares validator score distributions across:
- Novel vs computationally_known (MP match type)
- Compound classes (pure_oxide vs mixed-anion)
- Oxidation state confidence levels

Generates distribution plots and statistical tests.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats as scipy_stats

from gnome_auditor.config import DB_PATH

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "analysis_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_data():
    """Pull all validator scores joined with material metadata."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            m.material_id,
            m.reduced_formula,
            m.compound_class,
            m.oxide_type,
            m.crystal_system,
            m.n_sites,
            osa.confidence AS oxi_confidence,
            osa.has_mixed_valence,
            mc.match_type,
            mc.synth_status,
            -- Validator scores (NULL if not computed)
            MAX(CASE WHEN vr.check_name='charge_neutrality' AND vr.status='completed' THEN vr.score END) AS charge_score,
            MAX(CASE WHEN vr.check_name='shannon_radii' AND vr.status='completed' THEN vr.score END) AS shannon_score,
            MAX(CASE WHEN vr.check_name='pauling_rule2' AND vr.status='completed' THEN vr.score END) AS pauling_score,
            MAX(CASE WHEN vr.check_name='bond_valence_sum' AND vr.status='completed' THEN vr.score END) AS bvs_score,
            MAX(CASE WHEN vr.check_name='space_group' AND vr.status='completed' THEN vr.score END) AS spacegroup_score
        FROM materials m
        LEFT JOIN oxidation_state_assignments osa ON m.material_id = osa.material_id
        LEFT JOIN mp_cross_ref mc ON m.material_id = mc.material_id
        LEFT JOIN validation_results vr ON m.material_id = vr.material_id
        GROUP BY m.material_id
    """).fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    print(f"Loaded {len(data)} materials")
    return data


def plot_score_distributions(data):
    """Histograms of each validator score, segmented by MP match type."""
    checks = [
        ("bvs_score", "Global Instability Index (v.u.)", "Bond Valence Sum"),
        ("pauling_score", "Violation Fraction", "Pauling Rule 2"),
        ("shannon_score", "Violation Fraction", "Shannon Radii"),
        ("charge_score", "Total Charge", "Charge Neutrality"),
        ("spacegroup_score", "Fraction in Experimental DB", "Space Group"),
    ]

    fig, axes = plt.subplots(len(checks), 1, figsize=(10, 4 * len(checks)))

    for ax, (col, xlabel, title) in zip(axes, checks):
        novel = [d[col] for d in data if d["match_type"] == "novel" and d[col] is not None]
        comp_known = [d[col] for d in data if d["match_type"] == "computationally_known" and d[col] is not None]

        if not novel and not comp_known:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            continue

        bins = 50
        if col == "charge_score":
            all_vals = novel + comp_known
            lo, hi = np.percentile(all_vals, [2, 98])
            bins = np.linspace(lo, hi, 50)

        ax.hist(novel, bins=bins, alpha=0.6, label=f"Novel (n={len(novel)})",
                color="#2196F3", density=True)
        ax.hist(comp_known, bins=bins, alpha=0.6, label=f"Comp. known (n={len(comp_known)})",
                color="#FF9800", density=True)

        # Mann-Whitney U test
        if len(novel) > 10 and len(comp_known) > 10:
            u_stat, p_val = scipy_stats.mannwhitneyu(novel, comp_known, alternative="two-sided")
            # Effect size: rank-biserial correlation
            n1, n2 = len(novel), len(comp_known)
            r_rb = 1 - (2 * u_stat) / (n1 * n2)
            ax.text(0.98, 0.95,
                    f"Mann-Whitney p={p_val:.2e}\nEffect size r={r_rb:.3f}\n"
                    f"Novel median={np.median(novel):.4f}\n"
                    f"Comp. known median={np.median(comp_known):.4f}",
                    transform=ax.transAxes, ha="right", va="top", fontsize=8,
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

        ax.set_xlabel(xlabel)
        ax.set_ylabel("Density")
        ax.set_title(title)
        ax.legend()

    plt.tight_layout()
    path = OUTPUT_DIR / "score_distributions_by_match_type.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved: {path}")


def plot_compound_class_comparison(data):
    """Box plots of validator scores by compound class."""
    checks = [
        ("bvs_score", "GII (v.u.)", "Bond Valence Sum"),
        ("pauling_score", "Violation Fraction", "Pauling Rule 2"),
        ("shannon_score", "Violation Fraction", "Shannon Radii"),
    ]

    classes = ["pure_oxide", "oxyhalide", "oxychalcogenide", "oxynitride", "oxyhydride"]
    colors = ["#4CAF50", "#FF5722", "#9C27B0", "#00BCD4", "#795548"]

    fig, axes = plt.subplots(1, len(checks), figsize=(5 * len(checks), 6))

    for ax, (col, ylabel, title) in zip(axes, checks):
        box_data = []
        labels = []
        for cls in classes:
            vals = [d[col] for d in data if d["compound_class"] == cls and d[col] is not None]
            if vals:
                box_data.append(vals)
                labels.append(f"{cls}\n(n={len(vals)})")

        if box_data:
            bp = ax.boxplot(box_data, tick_labels=labels, patch_artist=True, showfliers=False)
            for patch, color in zip(bp["boxes"], colors[:len(box_data)]):
                patch.set_facecolor(color)
                patch.set_alpha(0.6)

        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=30)

    plt.tight_layout()
    path = OUTPUT_DIR / "scores_by_compound_class.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved: {path}")


def plot_oxi_confidence_effect(data):
    """How does oxi-state confidence affect downstream validator scores?"""
    checks = [
        ("bvs_score", "GII (v.u.)", "Bond Valence Sum"),
        ("pauling_score", "Violation Fraction", "Pauling Rule 2"),
        ("charge_score", "Total Charge", "Charge Neutrality"),
    ]

    conf_levels = ["both_agree", "single_method", "methods_disagree"]
    colors = ["#4CAF50", "#FFC107", "#F44336"]

    fig, axes = plt.subplots(1, len(checks), figsize=(5 * len(checks), 6))

    for ax, (col, ylabel, title) in zip(axes, checks):
        box_data = []
        labels = []
        for conf in conf_levels:
            vals = [d[col] for d in data if d["oxi_confidence"] == conf and d[col] is not None]
            if vals:
                box_data.append(vals)
                labels.append(f"{conf}\n(n={len(vals)})")

        if box_data:
            bp = ax.boxplot(box_data, tick_labels=labels, patch_artist=True, showfliers=False)
            for patch, color in zip(bp["boxes"], colors[:len(box_data)]):
                patch.set_facecolor(color)
                patch.set_alpha(0.6)

        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)

    plt.tight_layout()
    path = OUTPUT_DIR / "scores_by_oxi_confidence.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved: {path}")


def plot_cross_validator_correlations(data):
    """Scatter matrix: do materials that score poorly on one check also score poorly on others?"""
    checks = [
        ("bvs_score", "GII"),
        ("pauling_score", "Pauling"),
        ("shannon_score", "Shannon"),
    ]

    n = len(checks)
    fig, axes = plt.subplots(n, n, figsize=(4 * n, 4 * n))

    for i, (col_i, label_i) in enumerate(checks):
        for j, (col_j, label_j) in enumerate(checks):
            ax = axes[i][j]
            if i == j:
                # Diagonal: histogram
                vals = [d[col_i] for d in data if d[col_i] is not None]
                ax.hist(vals, bins=50, color="#2196F3", alpha=0.7)
                ax.set_xlabel(label_i)
            else:
                # Off-diagonal: scatter
                pairs = [(d[col_j], d[col_i]) for d in data
                         if d[col_i] is not None and d[col_j] is not None]
                if pairs:
                    x, y = zip(*pairs)
                    ax.scatter(x, y, alpha=0.1, s=5, color="#333")
                    # Spearman correlation
                    if len(pairs) > 10:
                        rho, p = scipy_stats.spearmanr(x, y)
                        ax.text(0.05, 0.95, f"ρ={rho:.3f}\np={p:.1e}",
                                transform=ax.transAxes, va="top", fontsize=9,
                                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
                ax.set_xlabel(label_j)
                ax.set_ylabel(label_i)

    plt.tight_layout()
    path = OUTPUT_DIR / "cross_validator_correlations.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved: {path}")


def plot_novelty_summary(data):
    """Combined figure: novel vs comp. known across all validators."""
    checks = [
        ("bvs_score", "GII (v.u.)"),
        ("pauling_score", "Pauling viol. frac."),
        ("shannon_score", "Shannon viol. frac."),
    ]

    fig, axes = plt.subplots(1, len(checks), figsize=(5 * len(checks), 5))

    for ax, (col, ylabel) in zip(axes, checks):
        novel = [d[col] for d in data if d["match_type"] == "novel" and d[col] is not None]
        known = [d[col] for d in data if d["match_type"] == "computationally_known" and d[col] is not None]

        positions = [1, 2]
        bp = ax.boxplot([novel, known], positions=positions, patch_artist=True,
                        showfliers=False, widths=0.6)
        bp["boxes"][0].set_facecolor("#2196F3")
        bp["boxes"][0].set_alpha(0.6)
        bp["boxes"][1].set_facecolor("#FF9800")
        bp["boxes"][1].set_alpha(0.6)

        ax.set_xticks(positions)
        ax.set_xticklabels([f"Novel\n(n={len(novel)})", f"Comp. known\n(n={len(known)})"])
        ax.set_ylabel(ylabel)

        if len(novel) > 10 and len(known) > 10:
            u, p = scipy_stats.mannwhitneyu(novel, known, alternative="two-sided")
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "n.s."
            ax.text(0.5, 0.95, f"p={p:.2e} ({sig})",
                    transform=ax.transAxes, ha="center", va="top", fontsize=10)

    fig.suptitle("Validator Scores: Novel GNoME Predictions vs Computationally Known (MP)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout()
    path = OUTPUT_DIR / "novelty_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved: {path}")


def generate_summary_stats(data):
    """Print and save a text summary of all statistical comparisons."""
    lines = []
    lines.append("=" * 80)
    lines.append("GNoME Auditor — Gold Data Calibration Summary")
    lines.append("=" * 80)

    # 1. Novel vs Computationally Known
    lines.append("\n## Novel vs Computationally Known (MP)\n")
    checks = [
        ("bvs_score", "Bond Valence Sum (GII)"),
        ("pauling_score", "Pauling Rule 2 (violation fraction)"),
        ("shannon_score", "Shannon Radii (violation fraction)"),
        ("charge_score", "Charge Neutrality (total charge)"),
        ("spacegroup_score", "Space Group (experimental fraction)"),
    ]

    for col, name in checks:
        novel = [d[col] for d in data if d["match_type"] == "novel" and d[col] is not None]
        known = [d[col] for d in data if d["match_type"] == "computationally_known" and d[col] is not None]

        lines.append(f"  {name}:")
        lines.append(f"    Novel:      n={len(novel):>5}, median={np.median(novel):.4f}, "
                     f"mean={np.mean(novel):.4f}, std={np.std(novel):.4f}" if novel else
                     f"    Novel:      n=0")
        lines.append(f"    Comp known: n={len(known):>5}, median={np.median(known):.4f}, "
                     f"mean={np.mean(known):.4f}, std={np.std(known):.4f}" if known else
                     f"    Comp known: n=0")

        if len(novel) > 10 and len(known) > 10:
            u, p = scipy_stats.mannwhitneyu(novel, known, alternative="two-sided")
            n1, n2 = len(novel), len(known)
            r_rb = 1 - (2 * u) / (n1 * n2)
            lines.append(f"    Mann-Whitney U: p={p:.4e}, effect size r={r_rb:.4f}")
            ks_stat, ks_p = scipy_stats.ks_2samp(novel, known)
            lines.append(f"    KS test: D={ks_stat:.4f}, p={ks_p:.4e}")
        lines.append("")

    # 2. By compound class
    lines.append("\n## By Compound Class\n")
    classes = ["pure_oxide", "oxyhalide", "oxychalcogenide", "oxynitride", "oxyhydride"]
    for col, name in [("bvs_score", "GII"), ("pauling_score", "Pauling")]:
        lines.append(f"  {name}:")
        for cls in classes:
            vals = [d[col] for d in data if d["compound_class"] == cls and d[col] is not None]
            if vals:
                lines.append(f"    {cls:>20s}: n={len(vals):>5}, "
                             f"median={np.median(vals):.4f}, mean={np.mean(vals):.4f}")
        lines.append("")

    # 3. By oxi confidence
    lines.append("\n## By Oxidation State Confidence\n")
    for col, name in [("bvs_score", "GII"), ("pauling_score", "Pauling")]:
        lines.append(f"  {name}:")
        for conf in ["both_agree", "single_method", "methods_disagree"]:
            vals = [d[col] for d in data if d["oxi_confidence"] == conf and d[col] is not None]
            if vals:
                lines.append(f"    {conf:>20s}: n={len(vals):>5}, "
                             f"median={np.median(vals):.4f}, mean={np.mean(vals):.4f}")
        lines.append("")

    # 4. Mixed valence effect
    lines.append("\n## Mixed Valence Effect on BVS\n")
    mixed = [d["bvs_score"] for d in data if d["has_mixed_valence"] and d["bvs_score"] is not None]
    not_mixed = [d["bvs_score"] for d in data if not d["has_mixed_valence"] and d["bvs_score"] is not None]
    lines.append(f"  Mixed valence:     n={len(mixed):>5}, median={np.median(mixed):.4f}" if mixed else
                 f"  Mixed valence:     n=0")
    lines.append(f"  Not mixed valence: n={len(not_mixed):>5}, median={np.median(not_mixed):.4f}" if not_mixed else
                 f"  Not mixed valence: n=0")
    if len(mixed) > 10 and len(not_mixed) > 10:
        u, p = scipy_stats.mannwhitneyu(mixed, not_mixed, alternative="two-sided")
        lines.append(f"  Mann-Whitney U: p={p:.4e}")

    # 5. Key findings
    lines.append("\n" + "=" * 80)
    lines.append("KEY FINDINGS")
    lines.append("=" * 80)

    # Check if novel materials have significantly different scores
    for col, name in [("bvs_score", "BVS/GII"), ("pauling_score", "Pauling")]:
        novel = [d[col] for d in data if d["match_type"] == "novel" and d[col] is not None]
        known = [d[col] for d in data if d["match_type"] == "computationally_known" and d[col] is not None]
        if len(novel) > 10 and len(known) > 10:
            u, p = scipy_stats.mannwhitneyu(novel, known, alternative="two-sided")
            direction = "higher" if np.median(novel) > np.median(known) else "lower"
            if p < 0.05:
                lines.append(f"\n- {name}: Novel predictions have significantly {direction} scores "
                             f"than computationally known materials (p={p:.2e})")
                lines.append(f"  Novel median: {np.median(novel):.4f}, "
                             f"Comp. known median: {np.median(known):.4f}")
            else:
                lines.append(f"\n- {name}: No significant difference between novel and "
                             f"computationally known (p={p:.2e})")

    text = "\n".join(lines)
    print(text)

    path = OUTPUT_DIR / "calibration_summary.txt"
    path.write_text(text)
    print(f"\nSaved: {path}")
    return text


def run_analysis():
    """Run the full calibration analysis."""
    print("Loading data...")
    data = get_data()

    print("\nGenerating plots...")
    plot_score_distributions(data)
    plot_compound_class_comparison(data)
    plot_oxi_confidence_effect(data)
    plot_cross_validator_correlations(data)
    plot_novelty_summary(data)

    print("\nComputing summary statistics...")
    generate_summary_stats(data)

    print(f"\nAll outputs saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    run_analysis()
