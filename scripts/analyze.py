"""
Analyze the main run: cell metrics, paired effects with task-clustered bootstrap CIs, and figures.

Usage:
    python scripts/analyze.py results/main.jsonl

Outputs:
    results/cells.csv     per arm x setting x condition: n, accuracy, PAR, detection, flag_T, confidence (+ 95% CIs)
    results/effects.csv   paired effects vs the C0 baseline of the same arm and setting, and S2 - S1 tool uplift
    results/position.csv  PAR in C0 by whether P was shown before T
    results/detect_action.csv  in C2/C3: how often P is still chosen when the model flagged it vs did not
    results/matched.csv   each reasoning arm vs Command A on exactly the same (task, repeat) blocks
    results/coverage.csv  complete (task, repeat) blocks per arm
    figures/fig1_par_by_condition.png
    figures/fig2_blindness_gap.png

Missing data: calls refused by the API (rate or quota limits) are excluded, not scored. Each arm is then
restricted to complete (task, repeat) blocks, i.e. all 12 condition x setting cells present, so every
paired comparison uses the same source order and the same repeats.

CIs: 95% percentile bootstrap, resampling tasks (2,000 draws), so repeats of the same task are not
treated as independent. Effects are paired: each task's mean in a condition minus its mean in C0.
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_record  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
N_BOOT, SEED = 2000, 0
CONDITIONS = ["C0", "C1", "C2", "C3", "C4", "C5"]
COND_LABELS = {
    "C0": "C0\nnone",
    "C1": "C1\nT valid",
    "C2": "C2\nP tampered",
    "C3": "C3\nP forged",
    "C4": "C4\nP official",
    "C5": "C5\nT valid,\nP tampered",
}
ARM_LABELS = {
    "command-r7b-12-2024": "Command R7B",
    "command-a-03-2025": "Command A",
    "command-a-reasoning-08-2025": "Command A Reasoning",
    "command-a-plus-05-2026@think": "Command A+ (thinking)",
}
ARM_ORDER = list(ARM_LABELS)
# Reference palette, categorical slots 1-2 (validated adjacent pair), text inks, surface.
COLOR = {"S1": "#2a78d6", "S2": "#eb6834"}
SETTING_LABELS = {"S1": "S1: manifest only", "S2": "S2: manifest + verifier result"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def load(path):
    import json

    rows = []
    n_api_fail = 0
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("parsed") is None and r.get("error"):
                n_api_fail += 1  # refused by the API: missing data, not model behaviour
                continue
            row = score_record(r)
            row["p_first"] = r.get("p_first")
            rows.append(row)
    df = pd.DataFrame(rows)
    df["correct"] = (df.outcome == "true").astype(float)
    df["planted"] = (df.outcome == "planted").astype(float)
    df["invalid"] = (df.outcome == "invalid").astype(float)
    df["detect_P"] = df.detect_P.astype(float)
    df["flag_T"] = df.flag_T.astype(float)
    print(f"excluded {n_api_fail} calls refused by the API")
    return df


def complete_blocks(df):
    """Keep only (arm, task, repeat) blocks that have all 12 condition x setting cells."""
    cells = df.groupby(["model", "task_id", "repeat"]).apply(lambda g: len(set(zip(g.condition, g.setting))))
    full = cells[cells == len(CONDITIONS) * 2].index
    keep = df.set_index(["model", "task_id", "repeat"]).index.isin(full)
    cov = (cells == len(CONDITIONS) * 2).groupby(level=["model", "task_id"]).sum().reset_index(name="complete_repeats")
    return df[keep].copy(), cov


def boot_mean(task_means, rng):
    """Mean over tasks with a task-resampling bootstrap CI."""
    x = np.asarray(task_means, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    draws = rng.choice(x, size=(N_BOOT, len(x)), replace=True).mean(axis=1)
    return x.mean(), np.percentile(draws, 2.5), np.percentile(draws, 97.5)


def per_task(df, metric):
    return df.groupby("task_id")[metric].mean()


def cell_table(df, rng):
    out = []
    for (arm, setting, cond), g in df.groupby(["model", "setting", "condition"]):
        row = {"arm": arm, "setting": setting, "condition": cond, "n": len(g), "invalid": g.invalid.mean()}
        for m in ("correct", "planted", "detect_P", "flag_T"):
            est, lo, hi = boot_mean(per_task(g, m), rng)
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = est, lo, hi
        row["confidence"] = g.confidence.mean()
        out.append(row)
    ren = {}
    for old, new in (("correct", "accuracy"), ("planted", "PAR")):
        ren.update({old: new, f"{old}_lo": f"{new}_lo", f"{old}_hi": f"{new}_hi"})
    return pd.DataFrame(out).rename(columns=ren)


def paired(a, b, rng):
    """Paired difference of per-task means: a - b, over tasks present in both."""
    d = (a - b).dropna()
    return boot_mean(d.values, rng) + (len(d),)


EFFECTS = [
    # name, condition, metric, description
    ("blindness_gap_tampered", "C2", "planted", "PAR(C2) - PAR(C0): boost to planted answer from a tampered credential"),
    ("blindness_gap_forged", "C3", "planted", "PAR(C3) - PAR(C0): boost to planted answer from a forged credential"),
    ("authority_effect", "C4", "planted", "PAR(C4) - PAR(C0): boost from an official-sounding outlet"),
    ("provenance_uplift", "C1", "correct", "Accuracy(C1) - Accuracy(C0): help from a valid credential on T"),
    ("head_to_head", "C5", "correct", "Accuracy(C5) - Accuracy(C0): valid T vs tampered P"),
]


def effects_table(df, rng):
    out = []
    for arm, ga in df.groupby("model"):
        by = {}
        for setting, gs in ga.groupby("setting"):
            base = {m: per_task(gs[gs.condition == "C0"], m) for m in ("planted", "correct")}
            for name, cond, metric, desc in EFFECTS:
                cur = per_task(gs[gs.condition == cond], metric)
                est, lo, hi, n = paired(cur, base[metric], rng)
                by[(name, setting)] = cur - base[metric]
                out.append(dict(arm=arm, setting=setting, effect=name, estimate=est, lo=lo, hi=hi, n_tasks=n, description=desc))
            # Detection in C2/C3 relative to false flags on P in C0 (concerns raised with no credential present)
            for name, cond in (("detection_tampered", "C2"), ("detection_forged", "C3")):
                cur = per_task(gs[gs.condition == cond], "detect_P")
                est, lo, hi, n = boot_mean(cur.values, rng) + (len(cur),)
                out.append(dict(arm=arm, setting=setting, effect=name, estimate=est, lo=lo, hi=hi, n_tasks=n,
                                description=f"Share of {cond} answers flagging P with a verification-related concern"))
        # Tool uplift: how much each effect changes when the verifier result is shown (S2 - S1)
        for name, *_ in EFFECTS:
            if (name, "S1") in by and (name, "S2") in by:
                est, lo, hi, n = paired(by[(name, "S2")], by[(name, "S1")], rng)
                out.append(dict(arm=arm, setting="S2-S1", effect=f"tool_uplift_{name}", estimate=est, lo=lo, hi=hi,
                                n_tasks=n, description=f"Change in {name} when the verifier result is shown"))
    return pd.DataFrame(out)


def position_table(df, rng):
    out = []
    g0 = df[df.condition == "C0"]
    for (arm, setting), g in g0.groupby(["model", "setting"]):
        for pf, gp in g.groupby("p_first"):
            est, lo, hi = boot_mean(per_task(gp, "planted"), rng)
            out.append(dict(arm=arm, setting=setting, p_first=pf, PAR=est, lo=lo, hi=hi, n=len(gp)))
    return pd.DataFrame(out)


REFERENCE_ARM = "command-a-03-2025"
KEY_EFFECTS = ["blindness_gap_tampered", "blindness_gap_forged", "authority_effect", "provenance_uplift", "head_to_head"]


def matched_table(df, rng):
    """Each arm with reduced coverage vs Command A on exactly the same (task, repeat) blocks."""
    out = []
    blocks = df.groupby("model").apply(lambda g: set(zip(g.task_id, g.repeat)))
    ref_blocks = blocks.get(REFERENCE_ARM, set())
    for arm, b in blocks.items():
        if arm == REFERENCE_ARM or b == ref_blocks:
            continue
        shared = b & ref_blocks
        sub = df[[(t, r) in shared for t, r in zip(df.task_id, df.repeat)]]
        sub = sub[sub.model.isin([arm, REFERENCE_ARM])]
        eff = effects_table(sub, rng)
        eff = eff[eff.effect.isin(KEY_EFFECTS + [f"tool_uplift_{e}" for e in KEY_EFFECTS]
                                  + ["detection_tampered", "detection_forged"])]
        eff = eff.assign(comparison=f"{arm} vs {REFERENCE_ARM}", n_blocks=len(shared),
                         n_tasks_matched=len({t for t, _ in shared}))
        out.append(eff)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def detect_action_table(df):
    """Does flagging P translate into not choosing P? Pooled over tasks (descriptive)."""
    out = []
    g = df[df.condition.isin(["C2", "C3"])]
    for (arm, setting, cond), gc in g.groupby(["model", "setting", "condition"]):
        flagged, unflagged = gc[gc.detect_P == 1], gc[gc.detect_P == 0]
        out.append(dict(
            arm=arm, setting=setting, condition=cond, n=len(gc),
            flag_rate=gc.detect_P.mean(),
            PAR_when_flagged=flagged.planted.mean() if len(flagged) else float("nan"),
            n_flagged=len(flagged),
            PAR_when_not_flagged=unflagged.planted.mean() if len(unflagged) else float("nan"),
            n_not_flagged=len(unflagged),
        ))
    return pd.DataFrame(out)


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


TASK_COUNTS = {}


def arm_label(arm):
    n = TASK_COUNTS.get(arm)
    return f"{ARM_LABELS.get(arm, arm)}" + (f" ({n} tasks)" if n and n < 30 else "")


def fig1(cells, path):
    arms = [a for a in ARM_ORDER if a in set(cells.arm)]
    fig, axes = plt.subplots(1, len(arms), figsize=(3.4 * len(arms), 3.4), sharey=True, facecolor=SURFACE)
    axes = np.atleast_1d(axes)
    x = np.arange(len(CONDITIONS))
    w = 0.38
    for ax, arm in zip(axes, arms):
        style(ax)
        for i, s in enumerate(("S1", "S2")):
            c = cells[(cells.arm == arm) & (cells.setting == s)].set_index("condition").reindex(CONDITIONS)
            pos = x + (i - 0.5) * (w + 0.02)
            ax.bar(pos, c.PAR, width=w, color=COLOR[s], edgecolor=SURFACE, linewidth=1, label=SETTING_LABELS[s], zorder=2)
            ax.errorbar(pos, c.PAR, yerr=[c.PAR - c.PAR_lo, c.PAR_hi - c.PAR], fmt="none", ecolor=INK2, elinewidth=1, capsize=0, zorder=3)
        base = cells[(cells.arm == arm) & (cells.condition == "C0")].PAR.mean()
        ax.axhline(base, color=INK2, linewidth=1, linestyle=(0, (3, 3)), zorder=1)
        ax.set_title(arm_label(arm), fontsize=10, color=INK)
        ax.set_xticks(x)
        ax.set_xticklabels([COND_LABELS[c] for c in CONDITIONS], fontsize=6.5)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("Planted answer rate (PAR)", color=INK, fontsize=9)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, fontsize=8, labelcolor=INK)
    fig.text(0.5, -0.02, "Dashed line: average C0 baseline. Error bars: 95% CI, bootstrap over tasks.",
             ha="center", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def fig2(effects, path):
    names = [("blindness_gap_tampered", "Tampered credential (C2)"), ("blindness_gap_forged", "Forged credential (C3)")]
    arms = [a for a in ARM_ORDER if a in set(effects.arm)]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), sharey=True, facecolor=SURFACE)
    y = np.arange(len(arms))
    for ax, (name, title) in zip(axes, names):
        style(ax)
        ax.yaxis.grid(False)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        for i, s in enumerate(("S1", "S2")):
            e = effects[(effects.effect == name) & (effects.setting == s)].set_index("arm").reindex(arms)
            yy = y + (i - 0.5) * 0.3
            ax.errorbar(e.estimate, yy, xerr=[e.estimate - e.lo, e.hi - e.estimate], fmt="o", color=COLOR[s],
                        ecolor=COLOR[s], elinewidth=1.5, markersize=6, label=SETTING_LABELS[s])
        ax.axvline(0, color=INK2, linewidth=1)
        ax.set_title(title, fontsize=10, color=INK)
        ax.set_xlabel("Blindness gap: PAR minus C0 baseline", fontsize=8, color=INK)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([arm_label(a) for a in arms], fontsize=8)
    axes[0].invert_yaxis()
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, fontsize=8, labelcolor=INK)
    fig.text(0.5, -0.03, "Right of zero: the broken credential pushed the model toward the planted answer. "
             "95% CI, bootstrap over tasks.", ha="center", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/analyze.py results/main.jsonl")
    rng = np.random.default_rng(SEED)
    df = load(sys.argv[1])
    df, coverage = complete_blocks(df)
    coverage.to_csv(ROOT / "results" / "coverage.csv", index=False)
    TASK_COUNTS.update(df.groupby("model").task_id.nunique().to_dict())
    print(f"{len(df)} trials in complete blocks, {df.task_id.nunique()} tasks")
    for m, g in df.groupby("model"):
        print(f"  {ARM_LABELS.get(m, m):24s} {g.task_id.nunique():2d} tasks, {len(set(zip(g.task_id, g.repeat))):3d} complete blocks")
    print(f"invalid (unparseable) rate: {df.invalid.mean():.3%}")

    (ROOT / "figures").mkdir(exist_ok=True)
    cells = cell_table(df, rng)
    effects = effects_table(df, rng)
    position = position_table(df, rng)
    cells.to_csv(ROOT / "results" / "cells.csv", index=False)
    effects.to_csv(ROOT / "results" / "effects.csv", index=False)
    position.to_csv(ROOT / "results" / "position.csv", index=False)
    detect_action = detect_action_table(df)
    detect_action.to_csv(ROOT / "results" / "detect_action.csv", index=False)
    matched = matched_table(df, rng)
    matched.to_csv(ROOT / "results" / "matched.csv", index=False)
    fig1(cells, ROOT / "figures" / "fig1_par_by_condition.png")
    fig2(effects, ROOT / "figures" / "fig2_blindness_gap.png")

    pd.set_option("display.width", 200)
    show = effects[effects.effect.isin(["blindness_gap_tampered", "blindness_gap_forged", "detection_tampered",
                                        "detection_forged", "tool_uplift_blindness_gap_tampered",
                                        "tool_uplift_blindness_gap_forged", "provenance_uplift"])]
    print("\nKey effects (estimate [95% CI]):")
    for _, r in show.iterrows():
        print(f"  {ARM_LABELS.get(r.arm, r.arm):24s} {r.setting:6s} {r.effect:38s} {r.estimate:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}]")
    if len(matched):
        print("\nMatched comparisons (same task x repeat blocks as Command A):")
        for _, r in matched[matched.effect.isin(["blindness_gap_tampered", "blindness_gap_forged"])].iterrows():
            print(f"  {r.comparison:55s} {ARM_LABELS.get(r.arm, r.arm):24s} {r.setting} {r.effect:24s} "
                  f"{r.estimate:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}]  ({r.n_tasks_matched} tasks)")
    print("\nDetection vs action (C2/C3): PAR when the model flagged P vs did not")
    for _, r in detect_action.iterrows():
        print(f"  {ARM_LABELS.get(r.arm, r.arm):24s} {r.setting} {r.condition}  flagged {r.flag_rate:.0%}  "
              f"PAR|flagged {r.PAR_when_flagged:.2f} (n={r.n_flagged})  PAR|not {r.PAR_when_not_flagged:.2f} (n={r.n_not_flagged})")
    print("\nWrote results/cells.csv, results/effects.csv, results/position.csv, results/detect_action.csv, results/matched.csv, results/coverage.csv, figures/fig1_*.png, figures/fig2_*.png")


if __name__ == "__main__":
    main()
