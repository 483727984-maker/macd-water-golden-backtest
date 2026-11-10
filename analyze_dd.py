import pandas as pd

nav = pd.read_csv(r"E:\strategy\macd_water_golden\output\nav.csv")
nav["trade_date"] = nav["trade_date"].astype(str)
nav["peak"] = nav["strategy_nav"].cummax()
nav["dd"] = nav["strategy_nav"] / nav["peak"] - 1

idx = nav["dd"].idxmin()
trough = nav.loc[idx]
peak_idx = nav.loc[:idx, "strategy_nav"].idxmax()
peak = nav.loc[peak_idx]
print("WORST_NET")
print("peak", peak["trade_date"], "nav", round(peak["strategy_nav"], 3), "nhold", int(peak["n_hold"]))
print(
    "trough",
    trough["trade_date"],
    "nav",
    round(trough["strategy_nav"], 3),
    "dd",
    round(trough["dd"], 3),
    "nhold",
    int(trough["n_hold"]),
)
after = nav.loc[idx:]
rec = after[after["strategy_nav"] >= peak["strategy_nav"]]
print("recovered", None if rec.empty else rec.iloc[0]["trade_date"])

for start, end in [
    ("20150601", "20150930"),
    ("20180101", "20181231"),
    ("20210201", "20221031"),
    ("20240101", "20240930"),
    ("20210701", "20261109"),
]:
    w = nav[(nav["trade_date"] >= start) & (nav["trade_date"] <= end)].copy()
    if w.empty:
        continue
    w["p"] = w["strategy_nav"].cummax()
    w["d"] = w["strategy_nav"] / w["p"] - 1
    i = w["d"].idxmin()
    j = w.loc[:i, "strategy_nav"].idxmax()
    print(
        f"WINDOW {start}-{end}: peak {w.loc[j,'trade_date']} {w.loc[j,'strategy_nav']:.2f} "
        f"-> trough {w.loc[i,'trade_date']} {w.loc[i,'strategy_nav']:.2f} "
        f"dd={w.loc[i,'d']*100:.1f}% avg_hold={w['n_hold'].mean():.0f}"
    )

print("corr daily ret vs bench", round(nav["port_ret"].corr(nav["bench_ret"]), 3))
print("avg hold when dd<-0.4", round(nav.loc[nav["dd"] < -0.4, "n_hold"].mean(), 1))
print("pct days dd<-0.3", round((nav["dd"] < -0.3).mean() * 100, 1))
print("exposure", round((nav["n_hold"] > 0).mean() * 100, 2))
