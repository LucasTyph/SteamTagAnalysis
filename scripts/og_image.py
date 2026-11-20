"""Draw the link-preview image (web/public/og-image.png, 1200x630) from the exported data.

The right side is the tag co-occurrence network (the most common tags, linked when
they often appear together), laid out with a small force simulation; the left side is
the title, a one-line pitch and headline counts. Colours follow the site's dark theme.

    python scripts/og_image.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from matplotlib import font_manager, patheffects  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "public" / "data"
OUT = ROOT / "web" / "public" / "og-image.png"

BG, SURFACE, FG, MUTED, BORDER = "#0f1215", "#171b20", "#e6e9ed", "#98a1ab", "#2a3038"
ACCENT, POS, NEG = "#7db3ee", "#5cc6a1", "#ef8a73"
N_TAGS = 46
SKIP = {"Singleplayer", "Indie", "Casual", "Multiplayer", "2D", "3D"}  # everywhere: clutter


def font() -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Inter", "Segoe UI", "Helvetica Neue", "Arial"):
        if name in names:
            return name
    return "DejaVu Sans"


def layout(n: int, edges: list[tuple[int, int, float]], seed: int = 3, steps: int = 600):
    """Fruchterman-Reingold in a unit box (numpy, no extra dependencies)."""
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1, 1, (n, 2))
    k = 1.6 / np.sqrt(n)
    for step in range(steps):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=-1) + 1e-6
        force = (delta / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        for i, j, w in edges:
            d = pos[i] - pos[j]
            dd = np.linalg.norm(d) + 1e-6
            pull = d / dd * (dd * dd / k) * w
            force[i] -= pull
            force[j] += pull
        force -= pos * 0.6  # gravity keeps it compact
        temp = 0.08 * (1 - step / steps) + 0.002
        length = np.linalg.norm(force, axis=1, keepdims=True) + 1e-9
        pos += force / length * np.minimum(length, temp)
    pos -= pos.mean(axis=0)
    return pos / np.abs(pos).max(axis=0)


def main() -> None:
    tags = [t for t in json.loads((DATA / "tags.json").read_text("utf-8")) if t["name"] not in SKIP]
    tags = tags[:N_TAGS]
    index = {t["tagid"]: i for i, t in enumerate(tags)}
    combos = pq.read_table(
        DATA / "combos.parquet", columns=["size", "t1", "t2", "n_games"]
    ).to_pylist()
    meta = json.loads((DATA / "meta.json").read_text("utf-8"))

    edges = []
    for c in combos:
        if c["size"] != 2 or c["t1"] not in index or c["t2"] not in index:
            continue
        i, j = index[c["t1"]], index[c["t2"]]
        share = c["n_games"] / min(tags[i]["n_games"], tags[j]["n_games"])
        if share >= 0.25:
            edges.append((i, j, min(share, 1.0)))
    pos = layout(len(tags), edges)

    plt.rcParams["font.family"] = font()
    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)

    net = fig.add_axes((0.55, 0.1, 0.44, 0.86))
    net.set_facecolor(BG)
    net.axis("off")
    for i, j, w in edges:
        net.plot(*zip(pos[i], pos[j], strict=True), color=BORDER, lw=0.6 + 1.6 * w, zorder=1)
    sizes = np.array([t["n_games"] for t in tags], float)
    radius = 40 + 900 * np.sqrt(sizes / sizes.max())
    coef = np.array([t["coef"] or 0.0 for t in tags])
    colors = [POS if c > 0.08 else NEG if c < -0.08 else ACCENT for c in coef]
    net.scatter(
        pos[:, 0], pos[:, 1], s=radius, c=colors, alpha=0.9, lw=1.5, edgecolors=BG, zorder=2
    )
    halo = [patheffects.withStroke(linewidth=4, foreground=BG)]
    for i in np.argsort(-sizes)[:10]:
        net.text(
            pos[i, 0],
            pos[i, 1] - 0.05 - 0.0035 * np.sqrt(radius[i]),
            tags[i]["name"],
            color=FG,
            fontsize=12,
            ha="center",
            va="top",
            zorder=4,
            path_effects=halo,
        )
    net.set_xlim(-1.18, 1.18)
    net.set_ylim(-1.18, 1.12)

    counts = meta["counts"]
    fig.text(0.06, 0.80, "Steam Tag Analysis", color=FG, fontsize=44, fontweight="bold")
    for k, line in enumerate(
        [
            "Which genre mixes beat",
            "expectations on Steam, and how",
            "reception changes after launch.",
        ]
    ):
        fig.text(0.06, 0.70 - k * 0.058, line, color=FG, fontsize=24)
    stats = [
        (f"{counts['games'] / 1000:.0f}k", "games with 20+ reviews"),
        (f"{(counts['pairs'] + counts['triples']) / 1000:.0f}k", "tag mixes tested"),
        (f"{counts.get('timeline_games', 5000) / 1000:.0f}k", "review timelines"),
    ]
    for k, (value, label) in enumerate(stats):
        y = 0.43 - k * 0.095
        fig.text(0.06, y, value, color=ACCENT, fontsize=26, fontweight="bold")
        fig.text(0.155, y + 0.008, label, color=MUTED, fontsize=17)
    fig.text(
        0.06,
        0.07,
        "Interactive site · DuckDB in the browser · updated monthly",
        color=MUTED,
        fontsize=14,
    )
    for k, (color, label) in enumerate([(POS, "tag raises scores"), (NEG, "lowers them")]):
        x = 0.62 + k * 0.17
        fig.text(x, 0.065, "●", color=color, fontsize=16)
        fig.text(x + 0.02, 0.07, label, color=MUTED, fontsize=13)

    fig.savefig(OUT, facecolor=BG, dpi=100)
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
