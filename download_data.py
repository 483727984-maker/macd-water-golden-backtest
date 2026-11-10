"""Download A-share daily bars + HS300 since 2010 via Tushare, with resume cache."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts

ROOT = Path(__file__).resolve().parent
DAILY_DIR = ROOT / "data" / "daily"
BENCH_PATH = ROOT / "data" / "hs300.parquet"
START = "20100101"
END = pd.Timestamp.today().strftime("%Y%m%d")
SLEEP = 0.12
MAX_RETRY = 5


def get_pro():
    token = os.environ.get("TUSHARE_TOKEN") or os.environ.get("TS_TOKEN")
    return ts.pro_api(token) if token else ts.pro_api()


def trade_days(pro) -> list[str]:
    cal = pro.trade_cal(exchange="SSE", start_date=START, end_date=END, is_open="1")
    return sorted(cal["cal_date"].astype(str).tolist())


def fetch_day(pro, trade_date: str) -> pd.DataFrame:
    last_err = None
    for i in range(MAX_RETRY):
        try:
            df = pro.daily(trade_date=trade_date)
            if df is None or df.empty:
                return pd.DataFrame(
                    columns=[
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "change",
                        "pct_chg",
                        "vol",
                        "amount",
                    ]
                )
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(SLEEP * (i + 2))
    raise RuntimeError(f"failed {trade_date}: {last_err}")


def download_daily(pro) -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    days = trade_days(pro)
    # only keep days up to latest available market data (skip future calendar)
    today = pd.Timestamp.today().strftime("%Y%m%d")
    days = [d for d in days if d <= today]

    done = {p.stem for p in DAILY_DIR.glob("*.parquet")}
    todo = [d for d in days if d not in done]
    print(f"trade_days={len(days)} cached={len(done)} todo={len(todo)}")

    for i, d in enumerate(todo, 1):
        df = fetch_day(pro, d)
        df.to_parquet(DAILY_DIR / f"{d}.parquet", index=False)
        if i % 50 == 0 or i == len(todo):
            print(f"daily progress {i}/{len(todo)} last={d} rows={len(df)}")
        time.sleep(SLEEP)


def download_bench(pro) -> None:
    if BENCH_PATH.exists():
        print("hs300 cache hit")
        return
    df = pro.index_daily(ts_code="000300.SH", start_date=START, end_date=END)
    if df is None or df.empty:
        raise RuntimeError("empty HS300")
    df = df.sort_values("trade_date").reset_index(drop=True)
    BENCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(BENCH_PATH, index=False)
    print(f"hs300 rows={len(df)}")


def main() -> None:
    # unbuffered progress for long downloads
    try:
        import sys

        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass
    pro = get_pro()
    download_bench(pro)
    download_daily(pro)
    print("download done", flush=True)


if __name__ == "__main__":
    main()
