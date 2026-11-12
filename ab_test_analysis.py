"""
A/B test analysis: Cookie Cats (gate_30 vs gate_40)

Question: does moving the first gate from level 30 to level 40
change how many players come back after 1 day and after 7 days?

How to run (in the black window, inside the ab-test-cookie-cats folder):
    python ab_test_analysis.py

It reads  data_raw\\cookie_cats.csv
It writes outputs\\results.txt and outputs\\retention_chart.png
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

def wilson_ci(successes, n, z=1.96):
    """95% Wilson confidence interval for a proportion."""
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def two_prop_ztest(s1, n1, s2, n2):
    """Two-sided z-test for a difference between two proportions."""
    p_pool = (s1 + s2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = (s1 / n1 - s2 / n2) / se
    return z, 2 * (1 - stats.norm.cdf(abs(z)))

HERE = Path(__file__).resolve().parent
DATA = HERE / "data_raw" / "cookie_cats.csv"
OUT = HERE / "outputs"
OUT.mkdir(exist_ok=True)

lines = []


def say(text=""):
    """Print and also keep the text for results.txt"""
    print(text)
    lines.append(str(text))


# ------------------------------------------------------------------
# 1. Load and check the data
# ------------------------------------------------------------------
df = pd.read_csv(DATA)
say("1. DATA CHECK")
say(f"Rows (players): {len(df):,}")
say(f"Columns: {list(df.columns)}")
say(f"Missing values: {int(df.isna().sum().sum())}")
say(f"Duplicate userids: {int(df['userid'].duplicated().sum())}")
say("")

counts = df["version"].value_counts().sort_index()
say("Players per group:")
for name, n in counts.items():
    say(f"  {name}: {n:,} ({n / len(df):.1%})")

# Sample ratio check: a fair 50/50 split should not be far from equal
chi2, p_srm = stats.chisquare(counts.values)
say(f"Sample ratio check (50/50 split): p = {p_srm:.3f}")
say("  (a very small p, such as below 0.01, would mean the split was not fair)")
say("")

# ------------------------------------------------------------------
# 2. Look at game rounds (extreme players, players who never played)
# ------------------------------------------------------------------
say("2. GAME ROUNDS (first 14 days)")
r = df["sum_gamerounds"]
say(f"Players with 0 rounds: {(r == 0).sum():,} ({(r == 0).mean():.1%})")
say(f"Median rounds: {r.median():.0f}")
say(f"99th percentile: {r.quantile(0.99):.0f}")
say(f"Maximum: {r.max():,}")
say("  (a maximum far above the 99th percentile is an extreme player)")
say("")

a = df[df["version"] == "gate_30"]
b = df[df["version"] == "gate_40"]

# ------------------------------------------------------------------
# 3. Retention by group with 95% confidence intervals
# ------------------------------------------------------------------
rng = np.random.default_rng(42)


def bootstrap_diff(x30, x40, n_boot=2000):
    """95% bootstrap CI for (gate_40 rate - gate_30 rate), in points."""
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        s30 = rng.choice(x30, size=len(x30), replace=True).mean()
        s40 = rng.choice(x40, size=len(x40), replace=True).mean()
        diffs[i] = (s40 - s30) * 100
    return np.percentile(diffs, [2.5, 97.5])


say("3. RETENTION BY GROUP")
results = {}
for col, label in [("retention_1", "1-day"), ("retention_7", "7-day")]:
    x30 = a[col].astype(int).to_numpy()
    x40 = b[col].astype(int).to_numpy()
    p30, p40 = x30.mean(), x40.mean()
    ci30 = wilson_ci(x30.sum(), len(x30))
    ci40 = wilson_ci(x40.sum(), len(x40))
    diff = (p40 - p30) * 100
    lo, hi = bootstrap_diff(x30, x40)
    z, p_val = two_prop_ztest(x40.sum(), len(x40), x30.sum(), len(x30))
    results[label] = (p30, p40, ci30, ci40)

    say(f"{label} retention")
    say(f"  gate_30: {p30:.2%}  (95% CI {ci30[0]:.2%} to {ci30[1]:.2%})")
    say(f"  gate_40: {p40:.2%}  (95% CI {ci40[0]:.2%} to {ci40[1]:.2%})")
    say(f"  Difference (gate_40 minus gate_30): {diff:+.2f} points")
    say(f"  95% bootstrap CI for the difference: {lo:+.2f} to {hi:+.2f} points")
    say(f"  Two-proportion z-test p-value: {p_val:.4f}")
    say("")

# ------------------------------------------------------------------
# 4. Smallest difference this test could reliably detect
# ------------------------------------------------------------------
say("4. SENSITIVITY OF THE TEST")
n_each = int(min(len(a), len(b)))
for col, label in [("retention_1", "1-day"), ("retention_7", "7-day")]:
    base = a[col].astype(int).mean()
    # smallest effect (Cohen's h) detectable with 80% power at 5% significance
    h = (stats.norm.ppf(0.975) + stats.norm.ppf(0.80)) / np.sqrt(n_each / 2)
    p_alt = np.sin(np.arcsin(np.sqrt(base)) + h / 2) ** 2
    say(
        f"{label}: with about {n_each:,} players per group, a difference of "
        f"about {abs(p_alt - base) * 100:.2f} points would be detected 80% of the time"
    )
say("")

# ------------------------------------------------------------------
# 5. Guardrail: did the change affect how much people play?
# ------------------------------------------------------------------
say("5. GUARDRAIL: GAME ROUNDS BY GROUP")
for name, g in [("gate_30", a), ("gate_40", b)]:
    say(
        f"  {name}: mean {g['sum_gamerounds'].mean():.1f}, "
        f"median {g['sum_gamerounds'].median():.0f}"
    )
u, p_mw = stats.mannwhitneyu(
    a["sum_gamerounds"], b["sum_gamerounds"], alternative="two-sided"
)
say(f"  Mann-Whitney U test p-value (median-style comparison): {p_mw:.4f}")
say("")

# ------------------------------------------------------------------
# 6. Chart
# ------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7, 4.5))
labels = ["1-day", "7-day"]
x = np.arange(len(labels))
w = 0.35
for i, (name, idx_rate, idx_ci, colour) in enumerate(
    [("gate_30", 0, 2, "#4C72B0"), ("gate_40", 1, 3, "#DD8452")]
):
    rates = [results[l][idx_rate] * 100 for l in labels]
    lows = [(results[l][idx_rate] - results[l][idx_ci][0]) * 100 for l in labels]
    highs = [(results[l][idx_ci][1] - results[l][idx_rate]) * 100 for l in labels]
    ax.bar(x + (i - 0.5) * w, rates, w, yerr=[lows, highs], capsize=4,
           label=name, color=colour)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylabel("Players who came back (%)")
ax.set_title("Cookie Cats: retention by gate position (95% CI)")
ax.legend()
fig.tight_layout()
fig.savefig(OUT / "retention_chart.png", dpi=150)
say("Chart saved: outputs/retention_chart.png")

(OUT / "results.txt").write_text("\n".join(lines), encoding="utf-8")
print("Results saved: outputs/results.txt")
