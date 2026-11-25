"""Compare two Indian (NSE/BSE) stocks for a short-term trade.

Usage:
    python compare.py RELIANCE TCS [--date 2026-11-23] [--out ./out]

Pulls from Yahoo Finance (free, ~15 min delayed intraday):
  1. 5 years of daily history          -> returns, CAGR, volatility, drawdown, beta
  2. 2 years of technicals             -> SMA/EMA, RSI, MACD, Bollinger, ATR, ADX, Stochastic, OBV
  3. Last 15 minutes of the session    -> 1-minute bars for the as-of date
  4. Candlestick charts (PNG)          -> daily 6 months + intraday 5-minute for the as-of date

Writes report.md, data.json and charts/*.png into --out.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEX = "^NSEI"  # NIFTY 50


# ----------------------------------------------------------------------------- helpers
def to_ticker(sym: str) -> str:
    sym = sym.strip().upper()
    if sym.startswith("^") or sym.endswith((".NS", ".BO")):
        return sym
    return f"{sym}.NS"


def fetch(ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                   interval=interval, auto_adjust=False, actions=False)
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)
    return df


def pct(a, b):
    return None if b in (0, None) or pd.isna(b) or pd.isna(a) else round((a / b - 1) * 100, 2)


def r(x, n=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n)


# ----------------------------------------------------------------------------- indicators
def rsi(close: pd.Series, n=14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def atr(df: pd.DataFrame, n=14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n=14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = df["High"].diff()
    dn = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / a
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), plus_di, minus_di


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    for n in (20, 50, 200):
        df[f"SMA{n}"] = c.rolling(n).mean()
    for n in (9, 21):
        df[f"EMA{n}"] = c.ewm(span=n, adjust=False).mean()
    df["RSI14"] = rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACDsig"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACDhist"] = df["MACD"] - df["MACDsig"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["BBup"], df["BBlo"] = mid + 2 * sd, mid - 2 * sd
    df["ATR14"] = atr(df)
    df["ADX14"], df["+DI"], df["-DI"] = adx(df)
    lo14, hi14 = df["Low"].rolling(14).min(), df["High"].rolling(14).max()
    df["StochK"] = 100 * (c - lo14) / (hi14 - lo14)
    df["StochD"] = df["StochK"].rolling(3).mean()
    df["OBV"] = (np.sign(c.diff()).fillna(0) * df["Volume"]).cumsum()
    df["Vol20"] = df["Volume"].rolling(20).mean()
    return df


# ----------------------------------------------------------------------------- sections
def long_term(daily5y: pd.DataFrame, index5y: pd.DataFrame) -> dict:
    c = daily5y["Close"]
    last = c.iloc[-1]
    years = (c.index[-1] - c.index[0]).days / 365.25
    rets = c.pct_change().dropna()
    dd = (c / c.cummax() - 1).min()

    def back(days):
        target = c.index[-1] - timedelta(days=days)
        s = c[c.index <= target]
        return pct(last, s.iloc[-1]) if len(s) else None

    yearly = c.groupby(c.index.year).agg(["first", "last"])
    yearly_ret = {int(y): pct(row["last"], row["first"]) for y, row in yearly.iterrows()}

    beta = None
    if not index5y.empty:
        j = pd.concat([rets, index5y["Close"].pct_change()], axis=1, join="inner").dropna().iloc[-250:]
        if len(j) > 30:
            beta = j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var()

    last252 = daily5y.iloc[-252:]
    return {
        "years_of_data": r(years, 1),
        "first_date": str(c.index[0].date()),
        "close": r(last),
        "return_1w_pct": back(7), "return_1m_pct": back(30), "return_3m_pct": back(91),
        "return_6m_pct": back(182), "return_1y_pct": back(365), "return_3y_pct": back(3 * 365),
        "return_5y_pct": pct(last, c.iloc[0]),
        "cagr_pct": r(((last / c.iloc[0]) ** (1 / years) - 1) * 100) if years > 0 else None,
        "ann_volatility_pct": r(rets.std() * np.sqrt(252) * 100),
        "max_drawdown_pct": r(dd * 100),
        "high_52w": r(last252["High"].max()), "low_52w": r(last252["Low"].min()),
        "pct_from_52w_high": pct(last, last252["High"].max()),
        "beta_vs_nifty_1y": r(beta),
        "yearly_return_pct": yearly_ret,
    }


def technicals(daily2y: pd.DataFrame, index2y: pd.DataFrame) -> dict:
    t = add_indicators(daily2y)
    x, p = t.iloc[-1], t.iloc[-2]
    close = x["Close"]
    recent = t.iloc[-20:]
    # classic floor pivots for the NEXT session, from the as-of day's bar
    pp = (x["High"] + x["Low"] + close) / 3
    rel = None
    if not index2y.empty:
        idx = index2y["Close"]
        s_1m = t["Close"].iloc[-1] / t["Close"].iloc[-22] - 1
        i_1m = idx.iloc[-1] / idx.iloc[-22] - 1 if len(idx) > 22 else np.nan
        rel = (s_1m - i_1m) * 100

    signals = []
    def sig(cond, bull, bear):
        signals.append(bull if cond else bear)
    sig(close > x["SMA20"], "Price above 20-DMA", "Price below 20-DMA")
    sig(close > x["SMA50"], "Price above 50-DMA", "Price below 50-DMA")
    if not pd.isna(x["SMA200"]):
        sig(close > x["SMA200"], "Price above 200-DMA (long uptrend)", "Price below 200-DMA (long downtrend)")
    sig(x["EMA9"] > x["EMA21"], "EMA9 > EMA21 (short-term momentum up)", "EMA9 < EMA21 (short-term momentum down)")
    sig(x["MACD"] > x["MACDsig"], "MACD above signal", "MACD below signal")
    if (p["MACD"] - p["MACDsig"]) * (x["MACD"] - x["MACDsig"]) < 0:
        signals.append("MACD crossover on the as-of day (" + ("bullish" if x["MACD"] > x["MACDsig"] else "bearish") + ")")
    if x["RSI14"] >= 70:
        signals.append("RSI overbought (>=70) - pullback risk")
    elif x["RSI14"] <= 30:
        signals.append("RSI oversold (<=30) - bounce candidate")
    if close > x["BBup"]:
        signals.append("Closed above upper Bollinger band")
    elif close < x["BBlo"]:
        signals.append("Closed below lower Bollinger band")
    if x["ADX14"] >= 25:
        signals.append(f"Strong trend (ADX {x['ADX14']:.0f}, " + ("+DI leads)" if x["+DI"] > x["-DI"] else "-DI leads)"))
    else:
        signals.append(f"Weak/rangebound trend (ADX {x['ADX14']:.0f})")
    if x["Volume"] > 1.5 * x["Vol20"]:
        signals.append("Volume spike (>1.5x 20-day average)")

    return {
        "as_of": str(t.index[-1].date()),
        "close": r(close), "prev_close": r(p["Close"]), "day_change_pct": pct(close, p["Close"]),
        "day_open": r(x["Open"]), "day_high": r(x["High"]), "day_low": r(x["Low"]),
        "sma20": r(x["SMA20"]), "sma50": r(x["SMA50"]), "sma200": r(x["SMA200"]),
        "ema9": r(x["EMA9"]), "ema21": r(x["EMA21"]),
        "rsi14": r(x["RSI14"]), "macd": r(x["MACD"], 3), "macd_signal": r(x["MACDsig"], 3),
        "macd_hist": r(x["MACDhist"], 3), "macd_hist_prev": r(p["MACDhist"], 3),
        "bb_upper": r(x["BBup"]), "bb_lower": r(x["BBlo"]),
        "bb_position_pct": r((close - x["BBlo"]) / (x["BBup"] - x["BBlo"]) * 100, 1),
        "atr14": r(x["ATR14"]), "atr_pct": r(x["ATR14"] / close * 100),
        "adx14": r(x["ADX14"], 1), "plus_di": r(x["+DI"], 1), "minus_di": r(x["-DI"], 1),
        "stoch_k": r(x["StochK"], 1), "stoch_d": r(x["StochD"], 1),
        "obv_trend_20d": "rising" if t["OBV"].iloc[-1] > t["OBV"].iloc[-20] else "falling",
        "volume": int(x["Volume"]), "volume_vs_20d_avg": r(x["Volume"] / x["Vol20"]),
        "support_20d": r(recent["Low"].min()), "resistance_20d": r(recent["High"].max()),
        "high_2y": r(t["High"].max()), "low_2y": r(t["Low"].min()),
        "pivots_next_session": {
            "PP": r(pp), "R1": r(2 * pp - x["Low"]), "R2": r(pp + x["High"] - x["Low"]),
            "S1": r(2 * pp - x["High"]), "S2": r(pp - (x["High"] - x["Low"])),
        },
        "rel_strength_vs_nifty_1m_pct": r(rel),
        "signals": signals,
    }, t


def last_15(intra: pd.DataFrame) -> dict:
    if intra.empty:
        return {"available": False, "note": "No 1-minute data (Yahoo keeps ~30 days of 1m bars)."}
    # strict clock window: Yahoo's 1m feed skips minutes, so don't just take the last 15 rows
    tail = intra[intra.index > intra.index[-1] - timedelta(minutes=15)]
    tp = (intra["High"] + intra["Low"] + intra["Close"]) / 3
    vwap = (tp * intra["Volume"]).cumsum() / intra["Volume"].cumsum().replace(0, np.nan)
    avg15 = intra["Volume"].sum() / max(len(intra) / 15, 1)
    start_px = tail["Open"].iloc[0]
    end_px = tail["Close"].iloc[-1]
    ups = int((tail["Close"] > tail["Open"]).sum())
    move = pct(end_px, start_px)
    return {
        "available": True,
        "window": f"{tail.index[0].strftime('%H:%M')}-{(tail.index[-1] + timedelta(minutes=1)).strftime('%H:%M')} IST",
        "start_price": r(start_px), "end_price": r(end_px), "change_pct": move,
        "high": r(tail["High"].max()), "low": r(tail["Low"].min()),
        "range_pct": pct(tail["High"].max(), tail["Low"].min()),
        "green_bars": f"{ups}/{len(tail)}",
        "volume": int(tail["Volume"].sum()),
        "volume_vs_avg_15m_block": r(tail["Volume"].sum() / avg15) if avg15 else None,
        "day_vwap": r(vwap.iloc[-1]),
        "close_vs_vwap_pct": pct(end_px, vwap.iloc[-1]),
        "intraday_open": r(intra["Open"].iloc[0]), "intraday_change_pct": pct(end_px, intra["Open"].iloc[0]),
        "read": ("buying into the close" if (move or 0) > 0.15 and ups > len(tail) / 2 else
                 "selling into the close" if (move or 0) < -0.15 and ups <= len(tail) / 2 else "flat / indecisive close"),
    }


# ----------------------------------------------------------------------------- scoring
def score(tech: dict, lt: dict, l15: dict) -> dict:
    """Short-term (1-10 trading day) swing score, -10..+10. Transparent, rule based."""
    pts, why = 0, []
    def add(n, reason):
        nonlocal pts
        pts += n
        why.append(f"{n:+d} {reason}")
    c = tech["close"]
    add(1 if c > tech["sma20"] else -1, "vs 20-DMA")
    add(1 if c > tech["sma50"] else -1, "vs 50-DMA")
    add(1 if tech["ema9"] > tech["ema21"] else -1, "EMA9 vs EMA21")
    add(1 if tech["macd"] > tech["macd_signal"] else -1, "MACD vs signal")
    add(1 if tech["macd_hist"] > tech["macd_hist_prev"] else -1, "MACD histogram expanding/contracting")
    rsi_v = tech["rsi14"]
    if 50 <= rsi_v < 70:
        add(2, f"RSI {rsi_v} in bullish momentum zone")
    elif rsi_v >= 70:
        add(-1, f"RSI {rsi_v} overbought")
    elif 30 < rsi_v < 50:
        add(-1, f"RSI {rsi_v} weak")
    else:
        add(1, f"RSI {rsi_v} oversold - bounce potential")
    if tech["adx14"] and tech["adx14"] >= 20:
        add(1 if tech["plus_di"] > tech["minus_di"] else -1, "ADX trend direction")
    add(1 if tech["obv_trend_20d"] == "rising" else -1, "OBV 20-day trend")
    if tech["rel_strength_vs_nifty_1m_pct"] is not None:
        add(1 if tech["rel_strength_vs_nifty_1m_pct"] > 0 else -1, "1-month relative strength vs NIFTY")
    if l15.get("available"):
        if l15["read"] == "buying into the close":
            add(1, "last-15-min buying")
        elif l15["read"] == "selling into the close":
            add(-1, "last-15-min selling")
        if l15["close_vs_vwap_pct"] is not None:
            add(1 if l15["close_vs_vwap_pct"] > 0 else -1, "close vs day VWAP")
    bias = "LONG" if pts >= 3 else "SHORT/AVOID" if pts <= -3 else "NEUTRAL"
    a = tech["atr14"]
    plan = None
    if bias == "LONG":
        plan = {"entry": c, "stop": r(c - 1.5 * a), "target1": r(c + 1.5 * a), "target2": r(c + 3 * a)}
    elif bias == "SHORT/AVOID":
        plan = {"entry": c, "stop": r(c + 1.5 * a), "target1": r(c - 1.5 * a), "target2": r(c - 3 * a),
                "note": "Short only via F&O/intraday; cash-segment traders should simply avoid."}
    return {"score": pts, "bias": bias, "breakdown": why, "atr_trade_plan": plan}


# ----------------------------------------------------------------------------- charts
def charts(sym: str, t: pd.DataFrame, intra5: pd.DataFrame, outdir: Path) -> list[str]:
    outdir.mkdir(parents=True, exist_ok=True)
    files = []
    style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":")
    d = t.iloc[-126:].copy()
    d.index = d.index.tz_localize(None)
    ap = [
        mpf.make_addplot(d["SMA20"], color="tab:blue", width=0.8),
        mpf.make_addplot(d["SMA50"], color="tab:orange", width=0.8),
        mpf.make_addplot(d["BBup"], color="grey", width=0.5, linestyle="--"),
        mpf.make_addplot(d["BBlo"], color="grey", width=0.5, linestyle="--"),
        mpf.make_addplot(d["RSI14"], panel=2, color="purple", ylabel="RSI", ylim=(0, 100)),
        mpf.make_addplot(d["MACDhist"], panel=3, type="bar", color="dimgray", ylabel="MACD"),
        mpf.make_addplot(d["MACD"], panel=3, color="tab:blue", width=0.8),
        mpf.make_addplot(d["MACDsig"], panel=3, color="tab:red", width=0.8),
    ]
    f = outdir / f"{sym}_daily_6m.png"
    mpf.plot(d, type="candle", style=style, volume=True, addplot=ap, panel_ratios=(4, 1, 1.2, 1.2),
             title=f"{sym} daily, 6 months (SMA20 blue, SMA50 orange, BB20)", figsize=(12, 9),
             savefig=dict(fname=f, dpi=110, bbox_inches="tight"))
    files.append(str(f))
    if not intra5.empty:
        i = intra5.copy()
        tp = (i["High"] + i["Low"] + i["Close"]) / 3
        i["VWAP"] = (tp * i["Volume"]).cumsum() / i["Volume"].cumsum().replace(0, np.nan)
        i.index = i.index.tz_localize(None)
        f = outdir / f"{sym}_intraday_5m.png"
        mpf.plot(i, type="candle", style=style, volume=True,
                 addplot=[mpf.make_addplot(i["VWAP"], color="tab:purple", width=1)],
                 title=f"{sym} intraday 5-min, {i.index[0].date()} (VWAP purple)", figsize=(12, 6),
                 savefig=dict(fname=f, dpi=110, bbox_inches="tight"))
        files.append(str(f))
    return files


# ----------------------------------------------------------------------------- driver
def analyse(sym: str, asof: date, idx5: pd.DataFrame, outdir: Path) -> dict:
    tk = to_ticker(sym)
    end = asof + timedelta(days=1)
    d5 = fetch(tk, asof - timedelta(days=5 * 365 + 2), end)
    if d5.empty:
        raise SystemExit(f"No data for {tk}. Check the NSE symbol (e.g. RELIANCE, HDFCBANK, TATAMOTORS).")
    actual = d5.index[-1].date()
    d2 = d5[d5.index.date >= asof - timedelta(days=2 * 365)]
    i2 = idx5[idx5.index.date >= asof - timedelta(days=2 * 365)] if not idx5.empty else idx5
    lt = long_term(d5, idx5)
    tech, t = technicals(d2, i2)
    intra1 = pd.DataFrame()
    intra5 = pd.DataFrame()
    try:
        intra1 = fetch(tk, actual, actual + timedelta(days=1), "1m")
        intra5 = fetch(tk, actual, actual + timedelta(days=1), "5m")
    except Exception as e:  # yfinance raises for dates beyond its intraday window
        print(f"[warn] intraday fetch failed for {tk}: {e}", file=sys.stderr)
    l15 = last_15(intra1)
    sc = score(tech, lt, l15)
    pngs = charts(tk.replace(".", "_"), t, intra5, outdir / "charts")
    return {"symbol": sym.upper(), "ticker": tk, "trading_day": str(actual), "long_term_5y": lt,
            "technicals_2y": tech, "last_15_min": l15, "short_term_score": sc, "charts": pngs}


def fmt_row(label, a, b):
    return f"| {label} | {'-' if a is None else a} | {'-' if b is None else b} |"


def report(A: dict, B: dict, asof_req: date, idx_note: str) -> str:
    a, b = A["symbol"], B["symbol"]
    L = [f"# {a} vs {b} - short-term comparison",
         f"Requested date: {asof_req} | Trading day used: {A['trading_day']} | {idx_note}",
         "Source: Yahoo Finance (NSE). Intraday data may be delayed ~15 min.", ""]
    def table(title, section, keys):
        L.append(f"## {title}")
        L.append(f"| Metric | {a} | {b} |")
        L.append("|---|---|---|")
        for k in keys:
            L.append(fmt_row(k, A[section].get(k), B[section].get(k)))
        L.append("")
    table("1. Five-year history", "long_term_5y",
          ["close", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct",
           "return_3y_pct", "return_5y_pct", "cagr_pct", "ann_volatility_pct", "max_drawdown_pct",
           "high_52w", "low_52w", "pct_from_52w_high", "beta_vs_nifty_1y"])
    table("2. Technicals (2-year window)", "technicals_2y",
          ["close", "day_change_pct", "sma20", "sma50", "sma200", "ema9", "ema21", "rsi14", "macd",
           "macd_signal", "macd_hist", "bb_position_pct", "atr14", "atr_pct", "adx14", "plus_di", "minus_di",
           "stoch_k", "obv_trend_20d", "volume_vs_20d_avg", "support_20d", "resistance_20d",
           "rel_strength_vs_nifty_1m_pct"])
    for X in (A, B):
        L.append(f"**{X['symbol']} signals:** " + "; ".join(X["technicals_2y"]["signals"]))
        L.append(f"**{X['symbol']} next-session pivots:** {X['technicals_2y']['pivots_next_session']}")
        L.append("")
    table("3. Last 15 minutes of the session", "last_15_min",
          ["window", "start_price", "end_price", "change_pct", "range_pct", "green_bars",
           "volume_vs_avg_15m_block", "day_vwap", "close_vs_vwap_pct", "intraday_change_pct", "read"])
    L.append("## 4. Short-term score (-12..+12)")
    for X in (A, B):
        s = X["short_term_score"]
        L.append(f"### {X['symbol']}: {s['score']:+d} -> {s['bias']}")
        L.append("- " + "\n- ".join(s["breakdown"]))
        if s["atr_trade_plan"]:
            L.append(f"- ATR plan: {s['atr_trade_plan']}")
        L.append("")
    L.append("## 5. Charts")
    for X in (A, B):
        for p in X["charts"]:
            L.append(f"- {p}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_a")
    ap.add_argument("stock_b")
    ap.add_argument("--date", help="As-of date YYYY-MM-DD (default: yesterday, IST)")
    ap.add_argument("--out", default="stock_compare_out")
    args = ap.parse_args()

    asof = (date.fromisoformat(args.date) if args.date
            else datetime.now(IST).date() - timedelta(days=1))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    idx5 = fetch(INDEX, asof - timedelta(days=5 * 365 + 2), asof + timedelta(days=1))
    idx_note = ""
    if not idx5.empty:
        ic = idx5["Close"]
        idx_note = f"NIFTY 50 close {ic.iloc[-1]:.2f} ({pct(ic.iloc[-1], ic.iloc[-2]):+.2f}%)"

    A = analyse(args.stock_a, asof, idx5, out)
    B = analyse(args.stock_b, asof, idx5, out)
    if A["trading_day"] != str(asof):
        print(f"[info] {asof} was not a trading day; used {A['trading_day']}.", file=sys.stderr)

    (out / "data.json").write_text(json.dumps({"requested_date": str(asof), "A": A, "B": B}, indent=2, default=str))
    md = report(A, B, asof, idx_note)
    (out / "report.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[done] {out.resolve() / 'report.md'}")


if __name__ == "__main__":
    main()
