"""MACD water golden-cross long-only backtest on A-shares vs HS300."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DAILY_DIR = ROOT / "data" / "daily"
BENCH_PATH = ROOT / "data" / "hs300.parquet"
OUT_DIR = ROOT / "output"
PANEL_PATH = ROOT / "data" / "panel_close_pct.parquet"
SIG_PATH = ROOT / "data" / "signals.parquet"

# Costs (one-way, fraction of notional)
COMMISSION = 0.0003  # 万三
STAMP_SELL = 0.0005  # 印花税（卖出）
SLIPPAGE = 0.0010  # 单边滑点 0.1%
BUY_COST = COMMISSION + SLIPPAGE  # 0.13%
SELL_COST = COMMISSION + STAMP_SELL + SLIPPAGE  # 0.18%


def load_panel(force: bool = False) -> pd.DataFrame:
    if PANEL_PATH.exists() and not force:
        print(f"load panel cache {PANEL_PATH}")
        return pd.read_parquet(PANEL_PATH)

    files = sorted(DAILY_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError("no daily parquet; run download_data.py first")

    frames = []
    for i, f in enumerate(files, 1):
        df = pd.read_parquet(f, columns=["ts_code", "trade_date", "close", "pct_chg"])
        frames.append(df)
        if i % 500 == 0 or i == len(files):
            print(f"read daily {i}/{len(files)}")
    panel = pd.concat(frames, ignore_index=True)
    panel["trade_date"] = panel["trade_date"].astype(str)
    panel = panel.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    print(f"panel rows={len(panel)} stocks={panel['ts_code'].nunique()}")
    return panel


def _position_from_events(golden: np.ndarray, death: np.ndarray) -> np.ndarray:
    pos = np.zeros(len(golden), dtype=np.int8)
    holding = 0
    for i in range(len(golden)):
        if holding == 0:
            if golden[i]:
                holding = 1
        elif death[i]:
            holding = 0
        pos[i] = holding
    return pos


def compute_signals(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["ts_code", "trade_date"], kind="mergesort")
    parts: list[pd.DataFrame] = []
    codes = df["ts_code"].to_numpy()
    change = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    starts = np.r_[0, change]
    ends = np.r_[change, len(df)]

    close_all = df["close"].to_numpy(dtype=float)
    pct_all = df["pct_chg"].to_numpy(dtype=float)
    date_all = df["trade_date"].to_numpy()

    for i, (s, e) in enumerate(zip(starts, ends), 1):
        n = e - s
        if n < 40:
            continue
        close = pd.Series(close_all[s:e])
        ema12 = close.ewm(span=12, adjust=False).mean().to_numpy()
        ema26 = close.ewm(span=26, adjust=False).mean().to_numpy()
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().to_numpy()
        prev_dif = np.r_[np.nan, dif[:-1]]
        prev_dea = np.r_[np.nan, dea[:-1]]
        golden = (prev_dif <= prev_dea) & (dif > dea) & (dif > 0) & (dea > 0)
        death = (prev_dif >= prev_dea) & (dif < dea)
        golden = np.nan_to_num(golden.astype(float), nan=0.0).astype(bool)
        death = np.nan_to_num(death.astype(float), nan=0.0).astype(bool)
        position = _position_from_events(golden, death)
        active = np.r_[0, position[:-1]]
        parts.append(
            pd.DataFrame(
                {
                    "ts_code": codes[s:e],
                    "trade_date": date_all[s:e],
                    "pct_chg": pct_all[s:e],
                    "golden": golden.astype(np.int8),
                    "death": death.astype(np.int8),
                    "position": position,
                    "active": active.astype(np.int8),
                }
            )
        )
        if i % 1000 == 0:
            print(f"signals stocks {i}/{len(starts)}")

    return pd.concat(parts, ignore_index=True)


def _daily_turnover_costs(holdings_by_day: dict[str, set[str]], dates: list[str]) -> pd.DataFrame:
    """Equal-weight turnover costs between consecutive days."""
    rows = []
    prev: set[str] = set()
    n_prev = 0
    for d in dates:
        cur = holdings_by_day.get(d, set())
        n_cur = len(cur)
        if n_prev == 0 and n_cur == 0:
            buy_to = sell_to = 0.0
        elif n_prev == 0 and n_cur > 0:
            buy_to, sell_to = 1.0, 0.0
        elif n_prev > 0 and n_cur == 0:
            buy_to, sell_to = 0.0, 1.0
        else:
            both = prev & cur
            only_new = cur - prev
            only_old = prev - cur
            delta = (1.0 / n_cur) - (1.0 / n_prev)
            buy_to = len(only_new) / n_cur + len(both) * max(delta, 0.0)
            sell_to = len(only_old) / n_prev + len(both) * max(-delta, 0.0)
        cost = buy_to * BUY_COST + sell_to * SELL_COST
        rows.append(
            {
                "trade_date": d,
                "turnover_buy": buy_to,
                "turnover_sell": sell_to,
                "cost": cost,
            }
        )
        prev, n_prev = cur, n_cur
    return pd.DataFrame(rows)


def _metrics(nav: pd.DataFrame, ret_col: str, nav_col: str) -> dict:
    n_years = len(nav) / 252.0
    total = float(nav[nav_col].iloc[-1] - 1.0)
    ann = float(nav[nav_col].iloc[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else np.nan
    vol = float(nav[ret_col].std() * np.sqrt(252))
    sharpe = float(ann / vol) if vol and vol > 1e-12 else np.nan
    dd = nav[nav_col] / nav[nav_col].cummax() - 1.0
    return {
        "total_return": total,
        "ann_return": ann,
        "vol_ann": vol,
        "sharpe": sharpe,
        "max_drawdown": float(dd.min()),
    }


def run_backtest(panel: pd.DataFrame, reuse_signals: bool = True) -> tuple[pd.DataFrame, dict]:
    if reuse_signals and SIG_PATH.exists():
        print(f"load signals cache {SIG_PATH}")
        sig = pd.read_parquet(SIG_PATH)
    else:
        print("computing MACD signals...")
        sig = compute_signals(panel)
        sig.to_parquet(SIG_PATH, index=False)
        print(f"saved signals rows={len(sig)}")

    print(f"signal rows={len(sig)}")
    active = sig.loc[sig["active"] == 1, ["trade_date", "ts_code", "pct_chg"]].copy()
    active["trade_date"] = active["trade_date"].astype(str)
    active["ret"] = active["pct_chg"].astype(float) / 100.0

    port = (
        active.groupby("trade_date", as_index=False)
        .agg(n_hold=("ts_code", "size"), gross_ret=("ret", "mean"))
        .sort_values("trade_date")
    )

    print("computing turnover costs...")
    holdings_by_day = {
        d: set(g["ts_code"].tolist()) for d, g in active.groupby("trade_date", sort=False)
    }

    bench = pd.read_parquet(BENCH_PATH)
    bench = bench.sort_values("trade_date").copy()
    bench["trade_date"] = bench["trade_date"].astype(str)
    bench["bench_ret"] = bench["pct_chg"].astype(float) / 100.0
    bench = bench[["trade_date", "bench_ret", "close"]].rename(columns={"close": "bench_close"})

    dates = sorted(set(panel["trade_date"].astype(str)))
    costs = _daily_turnover_costs(holdings_by_day, dates)

    nav = pd.DataFrame({"trade_date": dates})
    nav = nav.merge(port, on="trade_date", how="left")
    nav = nav.merge(costs, on="trade_date", how="left")
    nav = nav.merge(bench, on="trade_date", how="left")
    nav["n_hold"] = nav["n_hold"].fillna(0).astype(int)
    nav["gross_ret"] = nav["gross_ret"].fillna(0.0)
    nav["cost"] = nav["cost"].fillna(0.0)
    nav["turnover_buy"] = nav["turnover_buy"].fillna(0.0)
    nav["turnover_sell"] = nav["turnover_sell"].fillna(0.0)
    nav["bench_ret"] = nav["bench_ret"].fillna(0.0)
    nav = nav.dropna(subset=["bench_close"]).reset_index(drop=True)

    # net of costs; also keep zero-cost path for comparison
    nav["port_ret_gross"] = nav["gross_ret"]
    nav["port_ret"] = nav["gross_ret"] - nav["cost"]
    nav["strategy_nav_gross"] = (1.0 + nav["port_ret_gross"]).cumprod()
    nav["strategy_nav"] = (1.0 + nav["port_ret"]).cumprod()
    nav["bench_nav"] = (1.0 + nav["bench_ret"]).cumprod()
    nav["excess_ret"] = nav["port_ret"] - nav["bench_ret"]
    nav["drawdown"] = nav["strategy_nav"] / nav["strategy_nav"].cummax() - 1.0
    nav["drawdown_gross"] = nav["strategy_nav_gross"] / nav["strategy_nav_gross"].cummax() - 1.0
    nav["bench_drawdown"] = nav["bench_nav"] / nav["bench_nav"].cummax() - 1.0

    nav["year"] = nav["trade_date"].str[:4]
    yearly_rows = []
    for y, g in nav.groupby("year"):
        s = (1.0 + g["port_ret"]).prod() - 1.0
        sg = (1.0 + g["port_ret_gross"]).prod() - 1.0
        b = (1.0 + g["bench_ret"]).prod() - 1.0
        yearly_rows.append(
            {
                "year": y,
                "strategy": float(s),
                "strategy_gross": float(sg),
                "hs300": float(b),
                "excess": float(s - b),
                "avg_hold": float(g["n_hold"].mean()),
                "avg_daily_cost": float(g["cost"].mean()),
                "avg_turnover": float((g["turnover_buy"] + g["turnover_sell"]).mean()),
            }
        )
    yearly = pd.DataFrame(yearly_rows)

    net_m = _metrics(nav, "port_ret", "strategy_nav")
    gross_m = _metrics(nav, "port_ret_gross", "strategy_nav_gross")
    bench_total = float(nav["bench_nav"].iloc[-1] - 1.0)
    n_years = len(nav) / 252.0
    bench_ann = float(nav["bench_nav"].iloc[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else np.nan

    summary = {
        "start": nav["trade_date"].iloc[0],
        "end": nav["trade_date"].iloc[-1],
        "n_days": int(len(nav)),
        "n_stocks_universe": int(panel["ts_code"].nunique()),
        "total_return": net_m["total_return"],
        "ann_return": net_m["ann_return"],
        "vol_ann": net_m["vol_ann"],
        "sharpe": net_m["sharpe"],
        "max_drawdown": net_m["max_drawdown"],
        "gross_total_return": gross_m["total_return"],
        "gross_ann_return": gross_m["ann_return"],
        "gross_sharpe": gross_m["sharpe"],
        "gross_max_drawdown": gross_m["max_drawdown"],
        "bench_total_return": bench_total,
        "bench_ann_return": bench_ann,
        "bench_max_drawdown": float(nav["bench_drawdown"].min()),
        "excess_total": net_m["total_return"] - bench_total,
        "avg_holdings": float(nav["n_hold"].mean()),
        "exposure": float((nav["n_hold"] > 0).mean()),
        "avg_daily_cost": float(nav["cost"].mean()),
        "avg_daily_turnover": float((nav["turnover_buy"] + nav["turnover_sell"]).mean()),
        "total_cost_drag": float(gross_m["total_return"] - net_m["total_return"]),
        "n_golden_signals": int(sig["golden"].sum()),
        "n_death_signals": int(sig["death"].sum()),
        "assumptions": {
            "signal": "MACD water golden cross (DIF upcross DEA with DIF>0 and DEA>0)",
            "exit": "any death cross (DIF downcross DEA)",
            "macd": "EMA12/26/9 on raw close",
            "portfolio": "equal-weight all active holdings; cash return=0 when empty",
            "execution": "signal at T close, earn T+1 return (1-day lag)",
            "costs": {
                "commission": COMMISSION,
                "stamp_sell": STAMP_SELL,
                "slippage_one_way": SLIPPAGE,
                "buy_cost": BUY_COST,
                "sell_cost": SELL_COST,
                "method": "daily equal-weight turnover",
            },
            "benchmark": "000300.SH",
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nav.to_parquet(OUT_DIR / "nav.parquet", index=False)
    nav.to_csv(OUT_DIR / "nav.csv", index=False)
    yearly.to_csv(OUT_DIR / "yearly.csv", index=False)
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    nav["month"] = nav["trade_date"].str[:6]
    monthly = nav.groupby("month", as_index=False).agg(
        trade_date=("trade_date", "last"),
        strategy_nav=("strategy_nav", "last"),
        strategy_nav_gross=("strategy_nav_gross", "last"),
        bench_nav=("bench_nav", "last"),
        drawdown=("drawdown", "last"),
        n_hold=("n_hold", "mean"),
        cost=("cost", "mean"),
    )
    monthly.to_csv(OUT_DIR / "monthly.csv", index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return nav, summary


def main() -> None:
    panel = load_panel(force=False)
    # first run with costs: rebuild signals cache if missing
    run_backtest(panel, reuse_signals=True)


if __name__ == "__main__":
    main()
