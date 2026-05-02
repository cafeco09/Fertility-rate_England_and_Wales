from pathlib import Path
import zipfile
import textwrap

base = Path("/mnt/data/source_driven_fertility_project")
(base / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
(base / "data" / "raw").mkdir(parents=True, exist_ok=True)
(base / "data" / "processed").mkdir(parents=True, exist_ok=True)
(base / "graph").mkdir(parents=True, exist_ok=True)

script = r'''
"""
Source-driven chart builder.

This script does NOT hard-code the fertility or social-media data points.

It:
1. downloads fertility data from the Nomis/ONS API
2. downloads the original DataReportal UK report pages
3. extracts the relevant values from those source files
4. saves raw source files under data/raw/
5. saves the cleaned joined dataset under data/processed/
6. creates a zero-baseline chart under graph/

Run:
    python plot_from_original_sources.py
"""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
GRAPH_DIR = BASE_DIR / "graph"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_DIR.mkdir(parents=True, exist_ok=True)


START_YEAR = 2020
END_YEAR = 2024
YEARS = list(range(START_YEAR, END_YEAR + 1))


# Original fertility data source:
# Nomis dataset LEBIRTHRATES, maintained from ONS source data.
# Dataset page: https://www.nomisweb.co.uk/datasets/lebirthrates
NOMIS_FERTILITY_URL = "https://www.nomisweb.co.uk/api/v01/dataset/LEBIRTHRATES.data.csv"


# Original social media source pages:
# DataReportal publishes yearly UK reports as HTML pages.
DATAREPORTAL_REPORTS = {
    2020: "https://datareportal.com/reports/digital-2020-united-kingdom",
    2021: "https://datareportal.com/reports/digital-2021-united-kingdom",
    2022: "https://datareportal.com/reports/digital-2022-united-kingdom",
    2023: "https://datareportal.com/reports/digital-2023-united-kingdom",
    2024: "https://datareportal.com/reports/digital-2024-united-kingdom",
}


def fetch_text(url: str) -> str:
    """Download a URL and return text."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; source-driven-fertility-chart/1.0; "
            "+https://github.com/)"
        )
    }
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    return response.text


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names to lower snake-like names."""
    out = df.copy()
    out.columns = [
        str(c).strip().lower().replace(" ", "_").replace("-", "_")
        for c in out.columns
    ]
    return out


def find_column(columns: list[str], candidates: list[str]) -> str:
    """Find the first matching column by exact or partial match."""
    for candidate in candidates:
        candidate = candidate.lower()
        for col in columns:
            if col == candidate:
                return col

    for candidate in candidates:
        candidate = candidate.lower()
        for col in columns:
            if candidate in col:
                return col

    raise KeyError(f"Could not find any of these columns: {candidates}. Available: {columns}")


def get_fertility_from_nomis() -> pd.DataFrame:
    """
    Download fertility data from the Nomis/ONS API.

    The query pulls the original dataset for 2020-2024 and then filters for:
    - geography: England and Wales
    - measure: Total Fertility Rate / TFR

    This avoids hard-coding yearly fertility values.
    """
    params = {
        # The Nomis API supports date filters. This requests the exact years we need.
        "date": ",".join(str(y) for y in YEARS),
        "ExcludeMissingValues": "true",
    }

    response = requests.get(NOMIS_FERTILITY_URL, params=params, timeout=60)
    response.raise_for_status()

    raw_csv_path = RAW_DIR / "nomis_ons_lebirthrates_2020_2024.csv"
    raw_csv_path.write_text(response.text, encoding="utf-8")

    raw = pd.read_csv(StringIO(response.text))
    raw = normalise_columns(raw)

    date_col = find_column(raw.columns.tolist(), ["date_name", "time_name", "date", "time"])
    geography_col = find_column(raw.columns.tolist(), ["geography_name", "geography"])
    measure_col = find_column(raw.columns.tolist(), ["measure_name", "measure"])
    value_col = find_column(raw.columns.tolist(), ["obs_value", "value"])

    filtered = raw[
        raw[geography_col].astype(str).str.contains("England and Wales", case=False, na=False)
        & raw[measure_col].astype(str).str.contains("Total Fertility Rate|TFR", case=False, regex=True, na=False)
    ].copy()

    if filtered.empty:
        raise ValueError(
            "Could not find England and Wales Total Fertility Rate rows in the Nomis/ONS data. "
            "Inspect data/raw/nomis_ons_lebirthrates_2020_2024.csv and adjust the filters."
        )

    filtered["year"] = (
        filtered[date_col]
        .astype(str)
        .str.extract(r"(\d{4})", expand=False)
        .astype(int)
    )

    filtered["england_wales_total_fertility_rate"] = pd.to_numeric(
        filtered[value_col], errors="coerce"
    )

    result = (
        filtered[["year", "england_wales_total_fertility_rate"]]
        .dropna()
        .drop_duplicates(subset=["year"])
        .sort_values("year")
        .reset_index(drop=True)
    )

    missing_years = set(YEARS) - set(result["year"].tolist())
    if missing_years:
        raise ValueError(f"Missing fertility years from Nomis/ONS extraction: {sorted(missing_years)}")

    return result


def extract_social_media_users_from_text(text: str, year: int) -> float:
    """
    Extract UK social media users in millions from a DataReportal report page.

    Examples handled:
    - "There were 45.00 million social media users in the United Kingdom in January 2020"
    - "The UK was home to 56.20 million social media users in January 2024"
    - "There were 57.60 million social media users in the United Kingdom in January 2022"
    """
    patterns = [
        r"There were\s+([0-9]+(?:\.[0-9]+)?)\s+million\s+(?:active\s+)?social media users\s+in\s+the\s+United Kingdom\s+in\s+January\s+%d" % year,
        r"The UK was home to\s+([0-9]+(?:\.[0-9]+)?)\s+million\s+(?:active\s+)?social media users\s+in\s+January\s+%d" % year,
        r"there were\s+([0-9]+(?:\.[0-9]+)?)\s+million\s+(?:active\s+)?social media user identities\s+in\s+the\s+United Kingdom\s+in\s+January\s+%d" % year,
        r"([0-9]+(?:\.[0-9]+)?)\s+million\s+(?:active\s+)?social media users\s+in\s+the\s+United Kingdom\s+in\s+January\s+%d" % year,
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))

    raise ValueError(
        f"Could not extract social media users for {year} from DataReportal text. "
        f"Check data/raw/datareportal_{year}.html and update the regex patterns."
    )


def get_social_media_from_datareportal() -> pd.DataFrame:
    """
    Download original DataReportal pages and extract social media user figures.

    DataReportal does not provide a simple raw CSV endpoint for these yearly UK
    report figures, so this script saves the original HTML and extracts the
    published figure from the source page text.
    """
    rows = []

    for year, url in DATAREPORTAL_REPORTS.items():
        html = fetch_text(url)

        raw_html_path = RAW_DIR / f"datareportal_{year}.html"
        raw_html_path.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        value = extract_social_media_users_from_text(text, year)

        rows.append(
            {
                "year": year,
                "uk_social_media_users_millions": value,
                "datareportal_source_url": url,
            }
        )

    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def build_dataset() -> pd.DataFrame:
    fertility = get_fertility_from_nomis()
    social = get_social_media_from_datareportal()

    df = fertility.merge(social, on="year", how="inner").sort_values("year")

    if len(df) != len(YEARS):
        raise ValueError(
            f"Expected {len(YEARS)} rows after merging, got {len(df)}. "
            "Check source extraction."
        )

    output_path = PROCESSED_DIR / "fertility_social_media_2020_2024.csv"
    df.to_csv(output_path, index=False)

    return df


def plot_zero_baseline_chart(df: pd.DataFrame) -> None:
    years = df["year"]
    fertility_rate = df["england_wales_total_fertility_rate"]
    social_media_users = df["uk_social_media_users_millions"]

    fig, ax1 = plt.subplots(figsize=(12, 8), dpi=200)

    line1 = ax1.plot(
        years,
        fertility_rate,
        marker="o",
        linewidth=3,
        label="Fertility rate",
    )

    ax1.set_xlabel("Year", fontsize=12)
    ax1.set_ylabel("Total fertility rate (children per woman)", fontsize=12)
    ax1.set_ylim(0, 2.0)
    ax1.set_xticks(years)
    ax1.grid(True, axis="y", alpha=0.25)

    for x, y in zip(years, fertility_rate):
        ax1.annotate(
            f"{y:.2f}",
            (x, y),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=10,
        )

    ax2 = ax1.twinx()

    line2 = ax2.plot(
        years,
        social_media_users,
        marker="s",
        linewidth=3,
        linestyle="--",
        label="Social media users",
    )

    ax2.set_ylabel("UK social media users (millions)", fontsize=12)
    ax2.set_ylim(0, max(60, social_media_users.max() * 1.05))

    for x, y in zip(years, social_media_users):
        ax2.annotate(
            f"{y:.1f}m",
            (x, y),
            textcoords="offset points",
            xytext=(0, -18),
            ha="center",
            fontsize=10,
        )

    fig.suptitle(
        "Rising social media use, falling fertility",
        fontsize=18,
        fontweight="bold",
        y=0.96,
    )

    ax1.set_title(
        "Zero-baseline view: UK social media users vs England & Wales total fertility rate, 2020–2024",
        fontsize=12,
        pad=16,
    )

    lines = line1 + line2
    labels = [line.get_label() for line in lines]
    ax1.legend(lines, labels, loc="upper right", frameon=False)

    fig.text(
        0.08,
        0.06,
        "Interpretation: this zero-baseline version is less visually dramatic. It still shows fertility falling while\n"
        "social media use remains high, but it avoids overstating the size of the fertility movement.",
        fontsize=10,
    )

    fig.text(
        0.08,
        0.02,
        "Sources: ONS/Nomis LEBIRTHRATES API; DataReportal UK Digital reports 2020–2024.",
        fontsize=9,
    )

    plt.tight_layout(rect=[0.04, 0.1, 0.96, 0.92])

    output_file = GRAPH_DIR / "birthrate_social_media_chart_zero_scale.png"
    plt.savefig(output_file, bbox_inches="tight")
    print(f"Saved chart to: {output_file}")


def main() -> None:
    df = build_dataset()
    print(df)
    plot_zero_baseline_chart(df)


if __name__ == "__main__":
    main()
'''

requirements = """\
pandas
matplotlib
requests
beautifulsoup4
"""

workflow = r'''name: Generate source-driven fertility chart

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-chart:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          persist-credentials: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Generate chart from original source data
        run: |
          python plot_from_original_sources.py

      - name: Upload generated chart
        uses: actions/upload-artifact@v4
        with:
          name: fertility-social-media-zero-scale-chart
          path: graph/birthrate_social_media_chart_zero_scale.png

      - name: Commit generated data and chart
        if: github.event_name != 'pull_request'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/raw data/processed graph/birthrate_social_media_chart_zero_scale.png
          git commit -m "Generate chart from original source data" || echo "No changes to commit"
          git push
'''

readme = r'''# Fertility Rate in England & Wales vs UK Social Media Consumption

This project creates a zero-baseline chart comparing:

- England & Wales total fertility rate
- UK social media users

The chart is generated from original source files rather than manually entered chart points.

## How the data is sourced

### Fertility data

The script downloads fertility data from the Nomis/ONS API using the `LEBIRTHRATES` dataset.

Raw source file saved to:

```text
data/raw/nomis_ons_lebirthrates_2020_2024.csv
