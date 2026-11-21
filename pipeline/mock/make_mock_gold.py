"""Generate MOCK Gold files that follow docs/DATA_CONTRACT.md v1.0.0-draft.

Purpose: let the L&E / dashboard track build against the exact Gold schema
before real Silver/Gold models exist. Every number here is SYNTHETIC.
The raw series are invented random walks with a few hand-placed shocks
(2020-Q2 GDP collapse, 2022-23 DSR rise) so charts look realistic.

The derived columns (_z, _idx100, composites, contributions) are computed
exactly as the contract specifies, so the mock files pass the same
invariants as real Gold (Q2, Q4, Q5, Q6, Q8).

Run:  uv run python pipeline/mock/make_mock_gold.py
Out:  data/gold_mock/
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_VERSION = "1.0.0-mock"
OUT = Path(__file__).resolve().parents[2] / "data" / "gold_mock"

COUNTRIES = ["AUS", "CAN", "DEU", "GBR", "JPN", "KOR", "USA"]  # sorted ASC
FIRST_Q, LAST_PUBLISHED_Q, LAST_COMMON_Q = "2010Q1", "2026Q3", "2026Q2"
BASELINE = ("2010Q1", "2019Q4")
ANCHOR = "2019Q4"
HERO_START = "2015Q1"
SHARE_THRESHOLD = 0.25

# id, stem, polarity sign, basket, label, unit, source, dataset, native freq
INDICATORS = [
    ("H1", "h1_real_gdp_pc", +1, "headline", "Real GDP per capita",
     "Chained-volume national currency per person, SA", "OECD", "QNA", "Q"),
    ("H2", "h2_real_equity", +1, "headline", "Real equity prices",
     "Quarterly avg. of index level / headline CPI x 100", "OECD", "MEI_FIN", "M"),
    ("H3", "h3_unemployment", -1, "headline", "Unemployment rate",
     "% of labour force, SA, quarterly avg.", "OECD", "LFS", "M"),
    ("K1", "k1_real_hhdi_pc", +1, "kitchen_table", "Real household disposable income per capita",
     "Real HHDI per person, national currency, SA", "OECD", "NAAG", "Q"),
    ("K2", "k2_hh_dsr", -1, "kitchen_table", "Household debt service ratio",
     "% of household disposable income", "BIS", "WS_DSR", "Q"),
    ("K3", "k3_house_price_income", -1, "kitchen_table", "House price-to-income ratio",
     "OECD standardised ratio index", "OECD", "HOUSE_PRICES", "Q"),
    ("K4", "k4_essentials_cpi", -1, "kitchen_table", "Essentials CPI (food + energy)",
     "Cumulative price-level index, food + energy", "OECD", "PRICES_CPI", "M"),
]
QUARTERLY_ONLY = {"K1", "K2", "K3"}  # these lag: null in LAST_PUBLISHED_Q

# Plausible starting levels per country (purely illustrative)
START = {
    "h1_real_gdp_pc": dict(AUS=72000, CAN=55000, DEU=36000, GBR=31000, JPN=4.1e6, KOR=3.0e7, USA=58000),
    "h2_real_equity": dict.fromkeys(COUNTRIES, 100.0),
    "h3_unemployment": dict(AUS=5.3, CAN=8.1, DEU=7.2, GBR=7.9, JPN=5.1, KOR=3.7, USA=9.8),
    "k1_real_hhdi_pc": dict(AUS=48000, CAN=33000, DEU=22000, GBR=19500, JPN=2.4e6, KOR=1.6e7, USA=42000),
    "k2_hh_dsr": dict(AUS=12.5, CAN=13.8, DEU=6.9, GBR=10.2, JPN=7.5, KOR=11.8, USA=11.9),
    "k3_house_price_income": dict(AUS=95, CAN=88, DEU=82, GBR=97, JPN=104, KOR=101, USA=84),
    "k4_essentials_cpi": dict.fromkeys(COUNTRIES, 90.0),
}


def quarters() -> pd.PeriodIndex:
    return pd.period_range(FIRST_Q, LAST_PUBLISHED_Q, freq="Q")


def synth_raw(stem: str, iso: str, q: pd.PeriodIndex, rng: np.random.Generator) -> np.ndarray:
    n = len(q)
    lvl = START[stem][iso]
    t = np.arange(n)
    is_2020q2 = q == pd.Period("2020Q2")
    is_2020q3 = q == pd.Period("2020Q3")
    in_2022_23 = (q >= pd.Period("2022Q1")) & (q <= pd.Period("2023Q4"))
    in_2021_22 = (q >= pd.Period("2021Q2")) & (q <= pd.Period("2022Q4"))

    if stem in ("h1_real_gdp_pc", "k1_real_hhdi_pc"):
        g = rng.normal(0.004, 0.004, n)
        g[is_2020q2] = -0.09 if stem.startswith("h1") else 0.03
        g[is_2020q3] = 0.07 if stem.startswith("h1") else -0.02
        if stem.startswith("k1"):
            g[in_2022_23] -= 0.006  # real income squeeze
        return lvl * np.cumprod(1 + g)
    if stem == "h2_real_equity":
        g = rng.normal(0.015, 0.06, n)
        g[q == pd.Period("2020Q1")] = -0.22
        return lvl * np.cumprod(1 + g)
    if stem == "h3_unemployment":
        x = lvl - 0.06 * t + rng.normal(0, 0.12, n)
        x[is_2020q2] += 4.0
        x[is_2020q3] += 2.0
        return np.clip(x, 2.5, None)
    if stem == "k2_hh_dsr":
        x = lvl + np.cumsum(rng.normal(-0.02, 0.08, n))
        x[in_2022_23] += np.linspace(0.3, 2.0, in_2022_23.sum()) * (1.6 if iso in ("CAN", "AUS") else 0.8)
        x[q > pd.Period("2023Q4")] += 1.8 if iso in ("CAN", "AUS") else 0.9
        return x
    if stem == "k3_house_price_income":
        g = rng.normal(0.006, 0.01, n)
        g[(q >= pd.Period("2020Q3")) & (q <= pd.Period("2022Q2"))] += 0.02
        return lvl * np.cumprod(1 + g)
    if stem == "k4_essentials_cpi":
        g = rng.normal(0.004, 0.004, n)
        g[in_2021_22] += 0.02
        return lvl * np.cumprod(1 + g)
    raise ValueError(stem)


def build_panel() -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(20261121)
    q = quarters()
    in_base = (q >= pd.Period(BASELINE[0])) & (q <= pd.Period(BASELINE[1]))
    anchor_ix = int(np.where(q == pd.Period(ANCHOR))[0][0])
    stats: dict = {i[0]: {} for i in INDICATORS}
    frames = []

    for iso in COUNTRIES:
        df = pd.DataFrame({
            "country_iso": iso,
            "quarter": [f"{p.year}-Q{p.quarter}" for p in q],
            "quarter_start_date": q.start_time.date,
            "is_baseline_window": in_base,
        })
        for cid, stem, sign, *_ in INDICATORS:
            raw = synth_raw(stem, iso, q, rng)
            if cid in QUARTERLY_ONLY:
                raw[-1] = np.nan  # quarterly sources lag one quarter
            mu, sd = raw[in_base].mean(), raw[in_base].std(ddof=1)
            stats[cid][iso] = {"mean": float(mu), "sd": float(sd), "n_quarters": int(in_base.sum())}
            ratio = raw / raw[anchor_ix] * 100
            df[f"{stem}_raw"] = raw
            df[f"{stem}_z"] = sign * (raw - mu) / sd
            df[f"{stem}_idx100"] = ratio if sign > 0 else 200 - ratio
        frames.append(df)

    p = pd.concat(frames, ignore_index=True)
    raw_cols = [f"{s}_raw" for _, s, *_ in INDICATORS]
    p["n_components_available"] = p[raw_cols].notna().sum(axis=1).astype("int64")
    p["is_complete"] = p["n_components_available"] == 7
    p["is_composite_eligible"] = p["is_complete"] & (
        p["quarter"] <= f"{LAST_COMMON_Q[:4]}-Q{LAST_COMMON_Q[-1]}"
    )

    h = [s for c, s, *_ in INDICATORS if c.startswith("H")]
    k = [s for c, s, *_ in INDICATORS if c.startswith("K")]
    for form in ("z", "idx100"):
        # skipna=False → no partial composites
        p[f"headline_{form}"] = p[[f"{s}_{form}" for s in h]].mean(axis=1, skipna=False)
        p[f"kitchen_table_{form}"] = p[[f"{s}_{form}" for s in k]].mean(axis=1, skipna=False)
        p[f"divergence_gap_{form}"] = p[f"headline_{form}"] - p[f"kitchen_table_{form}"]
    for cid, stem, *_ in INDICATORS:
        w = 1 / 3 if cid.startswith("H") else -1 / 4
        p[f"contrib_{cid.lower()}_z"] = w * p[f"{stem}_z"]

    cols = (
        ["country_iso", "quarter", "quarter_start_date", "is_baseline_window",
         "is_complete", "is_composite_eligible", "n_components_available"]
        + [f"{s}_{f}" for _, s, *_ in INDICATORS for f in ("raw", "z", "idx100")]
        + ["headline_z", "kitchen_table_z", "divergence_gap_z",
           "headline_idx100", "kitchen_table_idx100", "divergence_gap_idx100"]
        + [f"contrib_{c.lower()}_z" for c, *_ in INDICATORS]
    )
    assert len(cols) == 41
    p = p[cols].sort_values(["country_iso", "quarter"], ignore_index=True)
    return p, stats


def validate(p: pd.DataFrame) -> int:
    """Subset of contract §7 checks; raises on failure, returns count run."""
    assert not p.duplicated(["country_iso", "quarter"]).any()  # Q2
    assert len(p) == 7 * p["quarter"].nunique()  # Q2 balanced
    anchor = p[p["quarter"] == "2019-Q4"]
    for c in [c for c in p.columns if c.endswith("_idx100")]:
        # Q4. The gap is a difference of two indexes, so at the anchor it is 0, not 100.
        target = 0.0 if c.startswith("divergence_gap") else 100.0
        assert np.allclose(anchor[c], target, atol=1e-9), c
    base = p[p["is_baseline_window"]]
    for c in [c for c in p.columns if c.endswith("_z") and not c.startswith(("contrib", "headline", "kitchen", "divergence"))]:
        g = base.groupby("country_iso")[c]
        assert (g.mean().abs() < 1e-6).all() and ((g.std(ddof=1) - 1).abs() < 1e-6).all(), c  # Q5
    elig = p[p["is_composite_eligible"]]
    s = elig[[c for c in p.columns if c.startswith("contrib_")]].sum(axis=1)
    assert np.allclose(s, elig["divergence_gap_z"], atol=1e-9)  # Q6
    return 5


def build_contributions(p: pd.DataFrame) -> dict:
    out = {
        "schema_version": SCHEMA_VERSION,
        "model": "z",
        "latest_complete_common_quarter": "2026-Q2",
        "components": [
            {"id": c, "label": lab, "basket": b,
             "weight": round(1 / 3 if c.startswith("H") else 1 / 4, 4),
             "sign_in_gap": 1 if c.startswith("H") else -1}
            for c, _, _, b, lab, *_ in INDICATORS
        ],
        "countries": {},
    }
    rows = p[p["is_composite_eligible"] & (p["quarter"] >= "2015-Q1")]
    for iso, g in rows.groupby("country_iso"):
        out["countries"][iso] = {}
        for _, r in g.iterrows():
            contrib = {c: float(r[f"contrib_{c.lower()}_z"]) for c, *_ in INDICATORS}
            gap = float(r["divergence_gap_z"])
            ok = abs(gap) >= SHARE_THRESHOLD
            out["countries"][iso][r["quarter"]] = {
                "divergence_gap_z": gap,
                "headline_z": float(r["headline_z"]),
                "kitchen_table_z": float(r["kitchen_table_z"]),
                "contributions": contrib,
                "shares": {c: v / gap for c, v in contrib.items()} if ok else None,
                "shares_suppressed": not ok,
            }
    return out


def build_metadata(stats: dict, checks: int) -> dict:
    ts = "2026-11-21T06:00:00Z"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{ts}_mock",
        "run_timestamp_utc": ts,
        "git_commit": "mock",
        "run_status": "mock",
        "latest_published_quarter": "2026-Q3",
        "latest_complete_common_quarter": "2026-Q2",
        "latest_complete_quarter_by_country": dict.fromkeys(COUNTRIES, "2026-Q2"),
        "baseline": {"z_window": ["2010-Q1", "2019-Q4"], "idx100_anchor": "2019-Q4"},
        "indicators": {
            cid: {
                "label": lab, "source": src, "dataset": ds,
                "series_keys": dict.fromkeys(COUNTRIES, "MOCK"),
                "native_frequency": freq, "unit": unit,
                "sa_status": dict.fromkeys(COUNTRIES, "SA"),
                "source_base_year": None,
                "vintage_date": dict.fromkeys(COUNTRIES, "2026-11-21"),
                "z_baseline_stats": stats[cid],
                "baseline_window_override": {},
            }
            for cid, _, _, _, lab, unit, src, ds, freq in INDICATORS
        },
        "validation": {"checks_run": checks, "checks_failed": 0, "warnings": [], "revision_alerts": []},
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel, stats = build_panel()
    checks = validate(panel)

    table = pa.Table.from_pandas(panel, preserve_index=False)
    meta = {**(table.schema.metadata or {}), b"divergence.schema_version": SCHEMA_VERSION.encode()}
    pq.write_table(table.replace_schema_metadata(meta), OUT / "divergence_panel.parquet")
    panel.to_csv(OUT / "divergence_panel.csv", index=False, float_format="%.17g")

    (OUT / "component_contributions.json").write_text(json.dumps(build_contributions(panel), indent=2))
    (OUT / "pipeline_metadata.json").write_text(json.dumps(build_metadata(stats, checks), indent=2))
    print(f"Wrote {len(panel)} rows x {panel.shape[1]} cols to {OUT}")


if __name__ == "__main__":
    main()
