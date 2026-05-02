from pathlib import Path
import textwrap
import zipfile

base = Path("/mnt/data/fertility_updated_plot_folder")
(base / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

script = r'''
from pathlib import Path
from io import StringIO
import re

import pandas as pd
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

# New output folder for the generated plot
PLOT_DIR = BASE_DIR / "plots"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)

START_YEAR = 2020
END_YEAR = 2024
YEARS = list(range(START_YEAR, END_YEAR + 1))

# Original fertility source:
# Nomis / ONS dataset: LEBIRTHRATES
# Dataset page: https://www.nomisweb.co.uk/datasets/lebirthrates
NOMIS_FERTILITY_URL = "https://www.nomisweb.co.uk/api/v01/dataset/LEBIRTHRATES.data.csv"

# Original social media sources:
# DataReportal yearly UK reports.
DATAREPORTAL_REPORTS = {
    2020: "https://datareportal.com/reports/digital-2020-united-kingdom",
    2021: "https://datareportal.com/reports/digital-2021-united-kingdom",
    2022: "https://datareportal.com/reports/digital-2022-united-kingdom",
    2023: "https://datareportal.com/reports/digital-2023-united-kingdom",
    2024: "https://datareportal.com/reports/digital-2024-united-kingdom",
}


def fetch_text(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 source-driven-fertility-chart"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.text


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [
        str(col).strip().lower().replace(" ", "_").replace("-", "_")
        for col in out.columns
    ]
    return out


def find_column(columns, candidates):
    columns = list(columns)

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

    raise KeyError(f"Could not find any of {candidates}. Available columns: {columns}")


def get_fertility_from_nomis() -> pd.DataFrame:
    """
    Download fertility data from the original Nomis/ONS API.

    Raw source file is saved to data/raw/.
    Processed values are extracted from the downloaded source, not manually typed.
    """
    params = {
        "date": ",".join(str(year) for year in YEARS),
        "ExcludeMissingValues": "true",
    }

    response = requests.get(NOMIS_FERTILITY_URL, params=params, timeout=90)
    response.raise_for_status()

    raw_path = RAW_DIR / "nomis_ons_lebirthrates_2020_2024.csv"
    raw_path.write_text(response.text, encoding="utf-8")

    raw = pd.read_csv(StringIO(response.text))
    raw = normalise_columns(raw)

    date_col = find_column(raw.columns, ["date_name", "time_name", "date", "time"])
    geography_col = find_column(raw.columns, ["geography_name", "geography"])
    measure_col = find_column(raw.columns, ["measure_name", "measure"])
    value_col = find_column(raw.columns, ["obs_value", "value"])

    filtered = raw[
        raw[geography_col].astype(str).str.contains("England and Wales", case=False, na=False)
        & raw[measure_col].astype(str).str.contains(
            "Total Fertility Rate|TFR",
            case=False,
            regex=True,
            na=False,
        )
    ].copy()

    if filtered.empty:
        print("Nomis columns found:")
        print(raw.columns.tolist())
        print("\nSample Nomis rows:")
        print(raw.head(25).to_string())
        raise ValueError(
            "Could not find England and Wales Total Fertility Rate rows in Nomis data."
        )

    filtered["year"] = (
        filtered[date_col]
        .astype(str)
        .str.extract(r"(\d{4})", expand=False)
        .astype(int)
    )

    filtered["england_wales_total_fertility_rate"] = pd.to_numeric(
        filtered[value_col],
        errors="coerce",
    )

    result = (
        filtered[["year", "england_wales_total_fertility_rate"]]
        .dropna()
        .drop_duplicates(subset=["year"])
        .sort_values("year")
        .reset_index(drop=True)
    )

    result = result[result["year"].between(START_YEAR, END_YEAR)]

    missing_years = set(YEARS) - set(result["year"].tolist())
    if missing_years:
        raise ValueError(f"Missing fertility years from Nomis extraction: {sorted(missing_years)}")

    return result


def extract_social_media_users_from_text(text: str, year: int) -> float:
    """
    Extract the published DataReportal UK social media user figure from source HTML text.
    """
    patterns = [
        rf"There were\s+([0-9]+(?:\.[0-9]+)?)\s+million\s+social media users\s+in\s+the\s+United Kingdom\s+in\s+January\s+{year}",
        rf"The UK was home to\s+([0-9]+(?:\.[0-9]+)?)\s+million\s+social media users\s+in\s+January\s+{year}",
        rf"([0-9]+(?:\.[0-9]+)?)\s+million\s+social media users\s+in\s+the\s+United Kingdom\s+in\s+January\s+{year}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))

    raise ValueError(f"Could not extract DataReportal social media figure for {year}.")


def get_social_media_from_datareportal() -> pd.DataFrame:
    rows = []

    for year, url in DATAREPORTAL_REPORTS.items():
        html = fetch_text(url)

        raw_path = RAW_DIR / f"datareportal_{year}.html"
        raw_path.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        users_millions = extract_social_media_users_from_text(text, year)

        rows.append(
            {
                "year": year,
                "uk_social_media_users_millions": users_millions,
                "datareportal_source_url": url,
            }
        )

    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def build_dataset() -> pd.DataFrame:
    fertility = get_fertility_from_nomis()
    social = get_social_media_from_datareportal()

    df = fertility.merge(social, on="year", how="inner").sort_values("year")

    if len(df) != len(YEARS):
        raise ValueError(f"Expected {len(YEARS)} years, but got {len(df)} rows after merging.")

    output_path = PROCESSED_DIR / "fertility_social_media_2020_2024.csv"
    df.to_csv(output_path, index=False)

    print("Processed dataset:")
    print(df.to_string(index=False))

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
    ax2.set_ylim(0, 60)

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

    # Plot is saved into the new folder: plots/
    output_file = PLOT_DIR / "fertility_social_media_zero_scale.png"
    plt.savefig(output_file, bbox_inches="tight")
    print(f"Saved plot to: {output_file}")


def main() -> None:
    df = build_dataset()
    plot_zero_baseline_chart(df)


if __name__ == "__main__":
    main()
'''

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

      - name: Show repository files
        run: |
          echo "Current repo files:"
          ls -la

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pandas matplotlib requests beautifulsoup4

      - name: Create output folders
        run: |
          mkdir -p data/raw
          mkdir -p data/processed
          mkdir -p plots

      - name: Generate plot from original source data
        run: |
          test -f plot_from_original_sources.py || (echo "Missing plot_from_original_sources.py in repo root" && exit 1)
          python plot_from_original_sources.py

      - name: Check generated files
        run: |
          test -f plots/fertility_social_media_zero_scale.png
          test -f data/processed/fertility_social_media_2020_2024.csv

      - name: Upload generated plot
        uses: actions/upload-artifact@v4
        with:
          name: fertility-social-media-zero-scale-plot
          path: plots/fertility_social_media_zero_scale.png

      - name: Upload processed dataset
        uses: actions/upload-artifact@v4
        with:
          name: fertility-social-media-processed-data
          path: data/processed/fertility_social_media_2020_2024.csv

      - name: Commit generated source extracts, data and plot
        if: github.event_name != 'pull_request'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/raw data/processed plots/fertility_social_media_zero_scale.png
          git commit -m "Generate source-driven fertility plot" || echo "No changes to commit"
          git push
'''

(base / "plot_from_original_sources.py").write_text(textwrap.dedent(script).strip() + "\n", encoding="utf-8")
(base / "main.yml").write_text(textwrap.dedent(workflow).strip() + "\n", encoding="utf-8")

zip_path = Path("/mnt/data/fertility_updated_plot_folder.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(base / "plot_from_original_sources.py", arcname="plot_from_original_sources.py")
    z.write(base / "main.yml", arcname=".github/workflows/main.yml")

print(base / "plot_from_original_sources.py")
print(base / "main.yml")
print(zip_path)
