"""Generate portfolio charts for README."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
FIG = ROOT / "docs" / "figures"


def setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.grid": True,
            "grid.alpha": 0.25,
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def main() -> None:
    setup_style()
    FIG.mkdir(parents=True, exist_ok=True)

    nav = pd.read_csv(OUT / "nav.csv")
    # CSV may store dates as ints like 20100104; force YYYYMMDD parsing
    nav["trade_date"] = pd.to_datetime(nav["trade_date"].astype(str), format="%Y%m%d")
    yearly = pd.read_csv(OUT / "yearly.csv")

    # 1) NAV curves — dual panel so gross scale does not crush net/bench
    fig, axes = plt.subplots(2, 1, figsize=(11, 7.2), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]})
    axes[0].plot(nav["trade_date"], nav["strategy_nav"], label="Strategy (net of costs)", color="#1f77b4", lw=1.6)
    axes[0].plot(nav["trade_date"], nav["bench_nav"], label="CSI 300", color="#2ca02c", lw=1.4)
    axes[0].set_ylabel("NAV (start = 1)")
    axes[0].set_title("Equity Curve: MACD Water Golden-Cross vs CSI 300")
    axes[0].legend(frameon=False, loc="upper left")

    axes[1].plot(nav["trade_date"], nav["strategy_nav_gross"], label="Strategy (gross, no costs)", color="#ff7f0e", lw=1.4)
    axes[1].plot(nav["trade_date"], nav["strategy_nav"], label="Strategy (net)", color="#1f77b4", lw=1.2, alpha=0.85)
    axes[1].set_xlabel("Date")
    axes[1].set_ylabel("NAV (start = 1)")
    axes[1].legend(frameon=False, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "equity_curve.png", dpi=160)
    plt.close(fig)

    # 2) Drawdown
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.fill_between(nav["trade_date"], nav["drawdown"] * 100, 0, alpha=0.45, color="#1f77b4", label="Strategy net drawdown")
    ax.plot(nav["trade_date"], nav["bench_drawdown"] * 100, color="#2ca02c", lw=1.2, label="CSI 300 drawdown")
    ax.set_title("Drawdown")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "drawdown.png", dpi=160)
    plt.close(fig)

    # 3) Yearly returns
    fig, ax = plt.subplots(figsize=(11, 4.8))
    x = range(len(yearly))
    w = 0.28
    ax.bar([i - w for i in x], yearly["strategy"] * 100, width=w, label="Strategy net")
    ax.bar(list(x), yearly["strategy_gross"] * 100, width=w, label="Strategy gross")
    ax.bar([i + w for i in x], yearly["hs300"] * 100, width=w, label="CSI 300")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(yearly["year"].astype(str), rotation=45, ha="right")
    ax.set_title("Calendar-Year Returns (%)")
    ax.set_ylabel("Return (%)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "yearly_returns.png", dpi=160)
    plt.close(fig)

    # 4) Holdings + turnover proxy
    fig, ax1 = plt.subplots(figsize=(11, 4.2))
    ax1.plot(nav["trade_date"], nav["n_hold"], color="#1f77b4", lw=0.9, label="Holdings")
    ax1.set_ylabel("Number of holdings")
    ax1.set_xlabel("Date")
    ax2 = ax1.twinx()
    tmp = nav.copy()
    tmp["tw_turnover"] = (tmp["turnover_buy"] + tmp["turnover_sell"]) * 100
    tmp["month"] = tmp["trade_date"].dt.to_period("M")
    m = tmp.groupby("month", as_index=False).agg(
        trade_date=("trade_date", "last"),
        turnover=("tw_turnover", "mean"),
    )
    ax2.plot(
        m["trade_date"],
        m["turnover"],
        color="#ff7f0e",
        lw=1.3,
        alpha=0.9,
        label="Avg daily turnover %",
    )
    ax2.set_ylabel("Avg daily two-way turnover (%)")
    ax1.set_title("Holdings Count and Turnover")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "holdings_turnover.png", dpi=160)
    plt.close(fig)

    print("wrote figures to", FIG)


if __name__ == "__main__":
    main()
