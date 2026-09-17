"""streamlit run dashboard.py

Reads output/state.json (written every cycle by `python main.py live`, or
once by `python main.py advise`) and renders it. Does not itself call any
API -- keeps the dashboard fast and rate-limit-safe. Auto-refreshes the page
so it picks up new state.json snapshots as the background `live` process
writes them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_PATH = PROJECT_ROOT / "output" / "state.json"

try:
    import yaml
    _config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text())
    REFRESH_SECONDS = _config["general"]["refresh_interval_seconds"]
except Exception:
    REFRESH_SECONDS = 300

st.set_page_config(page_title="Crypto Advisor", page_icon="\U0001FA99", layout="wide")
st.markdown(f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">', unsafe_allow_html=True)

st.title("Crypto Screening & Advisory -- Live Dashboard")
st.caption("Rule-based research output. Not financial advice.")

if not STATE_PATH.exists():
    st.warning("No output/state.json found yet.")
    if st.button("Run `python main.py advise` now"):
        with st.spinner("Running the full pipeline (this can take a few minutes on the free API tier)..."):
            result = subprocess.run([sys.executable, "main.py", "advise"], cwd=PROJECT_ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            st.rerun()
        else:
            st.error(result.stderr[-3000:])
    st.stop()

state = json.loads(STATE_PATH.read_text())

stale = state.get("stale_sources") or []
header_cols = st.columns([3, 1])
with header_cols[0]:
    st.write(f"**Last updated:** {state['fetch_time']} UTC")
with header_cols[1]:
    if stale:
        st.error(f"STALE: {', '.join(stale)}")
    else:
        st.success("Data fresh")

overview = state.get("overview", {})
ov_cols = st.columns(6)
labels = [
    ("total_mcap", "Total mcap", "total_mcap_chg"),
    ("btc_price", "BTC", "btc_chg"),
    ("eth_price", "ETH", "eth_chg"),
    ("btc_dominance", "BTC dominance", None),
    ("breadth_24h", "Breadth 24h", None),
    ("breadth_7d", "Breadth 7d", None),
]
for col, (key, label, delta_key) in zip(ov_cols, labels):
    col.metric(label, overview.get(key, "N/A"), overview.get(delta_key) if delta_key else None)

if state.get("summary_text"):
    st.subheader("Today, in plain English")
    st.info(state["summary_text"])

st.subheader("Top insights")
for i, insight in enumerate(state.get("insights", [])[:5], start=1):
    st.write(f"**{i}.** {insight['message']}")
with st.expander(f"{max(0, len(state.get('insights', [])) - 5)} more insights"):
    for insight in state.get("insights", [])[5:]:
        st.write(f"- {insight['message']}")

st.subheader("Actions -- portfolio & watchlist")
actions = state.get("actions", [])
if actions:
    st.dataframe(
        [{"Coin": a["coin_id"], "Action": a["action"], "Confidence": a["confidence"], "Score": round(a["score"], 2),
          "Suggested (AUD)": a.get("suggested_aud"), "Entry": a.get("entry_price_aud"), "Stop": a.get("stop_price_aud"),
          "Held": a.get("held")} for a in actions],
        use_container_width=True,
    )
    picked = st.selectbox("View full reasons for:", [a["coin_id"] for a in actions])
    picked_action = next(a for a in actions if a["coin_id"] == picked)
    for r in picked_action["reasons"]:
        st.write(f"- {r}")
else:
    st.write("No actions computed (run `python main.py advise`).")

st.subheader("Allocation")
alloc = state.get("allocation", {})
alloc_cols = st.columns(4)
alloc_cols[0].metric("Total value (AUD)", f"A${alloc.get('total_value_aud', 0):,.2f}")
alloc_cols[1].metric("Cash (AUD)", f"A${alloc.get('cash_aud', 0):,.2f}")
alloc_cols[2].metric("Core %", f"{alloc.get('core_pct', 0):.1f}%")
alloc_cols[3].metric("Speculative %", f"{alloc.get('speculative_pct', 0):.1f}%")

st.subheader("Top movers")
tabs = st.tabs(["1h", "24h", "7d"])
for tab, tf in zip(tabs, ["1h", "24h", "7d"]):
    with tab:
        m = state.get("movers", {}).get(tf, {})
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Gainers**")
            st.dataframe([{"Coin": r["symbol"], "Price": r["price_aud"], "%": round(r["pct_change"], 2),
                           "Class": r["classification"], "Held": r["held"]} for r in m.get("gainers", [])],
                         use_container_width=True)
        with c2:
            st.write("**Losers**")
            st.dataframe([{"Coin": r["symbol"], "Price": r["price_aud"], "%": round(r["pct_change"], 2),
                           "Class": r["classification"], "Held": r["held"]} for r in m.get("losers", [])],
                         use_container_width=True)
        with st.expander("High-risk movers (below liquidity filter)"):
            st.dataframe([{"Coin": r["symbol"], "Price": r["price_aud"], "%": round(r["pct_change"], 2)}
                          for r in m.get("high_risk_gainers", []) + m.get("high_risk_losers", [])],
                         use_container_width=True)

st.caption("Signals and insights are rule-based research output, not financial advice. "
           "See output/report.md for the full data-quality section.")
