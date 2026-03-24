"""
Generate publication-quality figures for the ETCG paper.

Outputs (all saved to figures/ in the repo root):
  figure-02-boxplot.pdf   — RQ1: Score distribution, ETCG vs Baseline
  figure-03-radar.pdf     — RQ2: Five-dimension quality profile
  figure-04-barchart.pdf  — RQ4: Mean score by spec richness group × condition

Usage:
  cd etcg-supplementary
  python scripts/generate_figures.py

Requirements:
  pip install matplotlib numpy
"""

import json
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless — no display required
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent.parent          # repo root
SCORES_FILE = BASE_DIR / "data" / "etcg-scores.json"
OUT_DIR     = BASE_DIR / "figures"
OUT_DIR.mkdir(exist_ok=True)

# ── Style ──────────────────────────────────────────────────────────────────────
# Springer-compatible: Times-style serif, minimal grid, no top/right spines

plt.rcParams.update({
    "font.family":       "serif",
    "font.serif":        ["Times New Roman", "DejaVu Serif", "serif"],
    "font.size":         10,
    "axes.titlesize":    10,
    "axes.labelsize":    10,
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "legend.fontsize":   9,
    "figure.dpi":        300,
    "savefig.dpi":       300,
    "savefig.bbox":      "tight",
    "savefig.pad_inches": 0.05,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "grid.linestyle":    "--",
})

# Colour palette (accessible, print-safe)
ETCG_COLOR     = "#2166AC"   # strong blue
BASELINE_COLOR = "#D6604D"   # muted red
SPARSE_COLOR   = "#74ADD1"   # light blue
STRUCT_COLOR   = "#1A6699"   # deep blue

# ── Load data ──────────────────────────────────────────────────────────────────

with open(SCORES_FILE) as f:
    data = json.load(f)

scores = data["scores"]

# Separate conditions
etcg_scores     = [s for s in scores if s["condition"] == "etcg"     and "error" not in s]
baseline_scores = [s for s in scores if s["condition"] == "baseline" and "error" not in s]

# Spec richness classification
SPARSE_SPECS     = {f"SPEC-{i:02d}" for i in range(1, 19)}   # SPEC-01 to SPEC-18
STRUCTURED_SPECS = {f"SPEC-{i:02d}" for i in range(19, 26)}  # SPEC-19 to SPEC-25

def richness(spec_id):
    return "structured" if spec_id in STRUCTURED_SPECS else "sparse"

etcg_pcts     = [s["percentage"] for s in etcg_scores]
baseline_pcts = [s["percentage"] for s in baseline_scores]

dims = ["specificity", "testability", "risk_coverage", "clarity", "actionability"]
dim_labels = ["Specificity", "Testability", "Risk\nCoverage", "Clarity", "Actionability"]

# ── Figure 2: Box plot — score distribution ───────────────────────────────────

def make_boxplot():
    fig, ax = plt.subplots(figsize=(3.5, 4.0))

    bp = ax.boxplot(
        [etcg_pcts, baseline_pcts],
        labels=["ETCG", "Baseline"],
        patch_artist=True,
        notch=False,
        widths=0.45,
        medianprops=dict(color="white", linewidth=2),
        whiskerprops=dict(linewidth=1.2),
        capprops=dict(linewidth=1.2),
        flierprops=dict(marker="o", markersize=4, linestyle="none",
                        markeredgewidth=0.8),
    )

    bp["boxes"][0].set_facecolor(ETCG_COLOR)
    bp["boxes"][0].set_alpha(0.85)
    bp["fliers"][0].set_markerfacecolor(ETCG_COLOR)
    bp["fliers"][0].set_markeredgecolor(ETCG_COLOR)

    bp["boxes"][1].set_facecolor(BASELINE_COLOR)
    bp["boxes"][1].set_alpha(0.85)
    bp["fliers"][1].set_markerfacecolor(BASELINE_COLOR)
    bp["fliers"][1].set_markeredgecolor(BASELINE_COLOR)

    # Annotate mean
    for i, (vals, color) in enumerate([(etcg_pcts, ETCG_COLOR),
                                        (baseline_pcts, BASELINE_COLOR)], 1):
        m = np.mean(vals)
        ax.plot(i, m, marker="D", color="white", markersize=5,
                markeredgecolor=color, markeredgewidth=1.5, zorder=5)
        ax.text(i + 0.28, m, f"{m:.1f}%", va="center", ha="left",
                fontsize=8, color=color, fontweight="bold")

    ax.set_ylabel("Charter Quality Score (%)")
    ax.set_ylim(25, 108)
    ax.set_yticks(range(30, 105, 10))
    ax.yaxis.grid(True, alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)

    # Annotate SD
    ax.text(1, 29, f"SD = {np.std(etcg_pcts, ddof=1):.1f}%",
            ha="center", fontsize=8, color=ETCG_COLOR)
    ax.text(2, 29, f"SD = {np.std(baseline_pcts, ddof=1):.1f}%",
            ha="center", fontsize=8, color=BASELINE_COLOR)

    diamond_patch = plt.Line2D([0], [0], marker="D", color="grey",
                               linestyle="none", markersize=6,
                               label="Mean")
    ax.legend(handles=[diamond_patch], loc="lower right", frameon=True,
              framealpha=0.9, edgecolor="lightgrey")

    fig.tight_layout()
    out = OUT_DIR / "figure-02-boxplot.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved: {out}")


# ── Figure 3: Radar chart — dimension quality profile ─────────────────────────

def make_radar():
    etcg_means     = [np.mean([s["scores"][d] for s in etcg_scores])     for d in dims]
    baseline_means = [np.mean([s["scores"][d] for s in baseline_scores]) for d in dims]

    N = len(dims)
    angles = [n / float(N) * 2 * math.pi for n in range(N)]
    angles += angles[:1]   # close the polygon

    etcg_vals     = etcg_means     + etcg_means[:1]
    baseline_vals = baseline_means + baseline_means[:1]

    fig, ax = plt.subplots(figsize=(3.8, 3.8), subplot_kw=dict(polar=True))

    # Draw gridlines
    ax.set_ylim(1.5, 3.15)
    ax.set_yticks([2.0, 2.5, 3.0])
    ax.set_yticklabels(["2.0", "2.5", "3.0"], fontsize=7.5, color="grey")

    # Set axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dim_labels, fontsize=9)

    # Adjust label distance
    ax.tick_params(axis="x", pad=8)

    # Plot ETCG
    ax.plot(angles, etcg_vals, color=ETCG_COLOR, linewidth=2, linestyle="-")
    ax.fill(angles, etcg_vals, color=ETCG_COLOR, alpha=0.18)

    # Plot Baseline
    ax.plot(angles, baseline_vals, color=BASELINE_COLOR, linewidth=2,
            linestyle="--")
    ax.fill(angles, baseline_vals, color=BASELINE_COLOR, alpha=0.10)

    # Data point markers
    ax.plot(angles[:-1], etcg_means,     "o", color=ETCG_COLOR,
            markersize=5, zorder=5)
    ax.plot(angles[:-1], baseline_means, "s", color=BASELINE_COLOR,
            markersize=5, zorder=5)

    # Legend
    etcg_patch     = mpatches.Patch(color=ETCG_COLOR,     alpha=0.7, label="ETCG")
    baseline_patch = mpatches.Patch(color=BASELINE_COLOR, alpha=0.5, label="Baseline")
    ax.legend(handles=[etcg_patch, baseline_patch],
              loc="upper right", bbox_to_anchor=(1.32, 1.12),
              frameon=True, framealpha=0.9, edgecolor="lightgrey")

    ax.spines["polar"].set_visible(False)
    ax.grid(color="grey", alpha=0.3, linestyle="--")

    fig.tight_layout()
    out = OUT_DIR / "figure-03-radar.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved: {out}")


# ── Figure 4: Bar chart — richness group × condition ─────────────────────────

def make_barchart():
    # Compute means and SDs by richness group for both conditions
    etcg_sparse     = [s["percentage"] for s in etcg_scores
                       if richness(s["spec_id"]) == "sparse"]
    etcg_structured = [s["percentage"] for s in etcg_scores
                       if richness(s["spec_id"]) == "structured"]
    bl_sparse       = [s["percentage"] for s in baseline_scores
                       if richness(s["spec_id"]) == "sparse"]
    bl_structured   = [s["percentage"] for s in baseline_scores
                       if richness(s["spec_id"]) == "structured"]

    groups     = ["Sparse\n(SPEC-01–18)", "Structured\n(SPEC-19–25)"]
    etcg_means = [np.mean(etcg_sparse),     np.mean(etcg_structured)]
    etcg_sds   = [np.std(etcg_sparse, ddof=1), np.std(etcg_structured, ddof=1)]
    bl_means   = [np.mean(bl_sparse),       np.mean(bl_structured)]
    bl_sds     = [np.std(bl_sparse, ddof=1),   np.std(bl_structured, ddof=1)]

    x     = np.arange(len(groups))
    width = 0.32

    fig, ax = plt.subplots(figsize=(4.5, 4.0))

    bars_etcg = ax.bar(x - width / 2, etcg_means, width,
                       yerr=etcg_sds, capsize=5,
                       color=ETCG_COLOR, alpha=0.85,
                       error_kw=dict(elinewidth=1.2, ecolor="#1a1a2e"),
                       label="ETCG")

    bars_bl   = ax.bar(x + width / 2, bl_means, width,
                       yerr=bl_sds, capsize=5,
                       color=BASELINE_COLOR, alpha=0.85,
                       error_kw=dict(elinewidth=1.2, ecolor="#5c1010"),
                       label="Baseline")

    # Value labels on bars
    for bar, mean, sd in zip(bars_etcg, etcg_means, etcg_sds):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + sd + 0.8,
                f"{mean:.1f}%", ha="center", va="bottom",
                fontsize=8, color=ETCG_COLOR, fontweight="bold")

    for bar, mean, sd in zip(bars_bl, bl_means, bl_sds):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + sd + 0.8,
                f"{mean:.1f}%", ha="center", va="bottom",
                fontsize=8, color=BASELINE_COLOR, fontweight="bold")

    ax.set_ylabel("Mean Charter Quality Score (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylim(75, 115)
    ax.set_yticks(range(75, 106, 5))
    ax.yaxis.grid(True, alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=True, framealpha=0.9,
              edgecolor="lightgrey")

    # Annotate SD reduction arrow for ETCG structured
    ax.annotate(
        "SD: 11.1% → 1.1%",
        xy=(0.72, 102), fontsize=7.5, color=ETCG_COLOR,
        ha="center",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor=ETCG_COLOR, alpha=0.8),
    )

    fig.tight_layout()
    out = OUT_DIR / "figure-04-barchart.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved: {out}")


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating ETCG paper figures...")
    print(f"Reading scores from: {SCORES_FILE.relative_to(BASE_DIR)}")
    print(f"Writing figures to:  {OUT_DIR.relative_to(BASE_DIR)}")
    print()
    make_boxplot()
    make_radar()
    make_barchart()
    print()
    print("Done. Three figures generated.")
