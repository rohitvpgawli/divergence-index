"""Offline checks on the Airbyte declarative manifests (no network)."""

from pathlib import Path

import yaml
from airbyte_cdk.sources.declarative.concurrent_declarative_source import ConcurrentDeclarativeSource

MANIFESTS = Path(__file__).resolve().parents[1] / "pipeline" / "ingest" / "airbyte" / "manifests"

EXPECTED = {
    "source_oecd_sdmx.yaml": {
        "h1_real_gdp_per_capita",
        "h2_share_price_index",
        "h3_unemployment_rate",
        "k1_real_hh_disposable_income_pc",
        "k1_hh_disposable_income_nominal",
        "k3_house_price_to_income",
        "k4_cpi_components",
        "ref_population",
        "ref_hh_consumption",
        "ref_gdp_volume",
        "ref_cpi_weights",
    },
    "source_bis_sdmx.yaml": {"k2_household_dsr"},
}
COUNTRIES = {
    "source_oecd_sdmx.yaml": {"countries": ["USA", "KOR"], "start_period": "2009"},
    "source_bis_sdmx.yaml": {"countries": ["US", "KR"], "start_period": "2009"},
}


def test_manifests_validate_and_declare_expected_streams():
    for name, expected in EXPECTED.items():
        manifest = yaml.safe_load((MANIFESTS / name).read_text())
        source = ConcurrentDeclarativeSource(source_config=manifest, config=COUNTRIES[name])
        streams = {s.name for s in source.streams(config=COUNTRIES[name])}
        assert streams == expected, name
