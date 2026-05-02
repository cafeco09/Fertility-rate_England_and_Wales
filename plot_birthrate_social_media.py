"""
Plot UK social media users against England & Wales total fertility rate.

How to run:
    python plot_birthrate_social_media.py

Inputs:
    birthrate_social_media_data.csv

Outputs:
    birthrate_social_media_chart.png

Important:
    This chart shows an inverse trend over time. It does not prove that social media
    causes fertility decline. Birth rates are influenced by housing, childcare costs,
    income security, partnership formation, policy, culture, age at first birth, and
    other structural factors.
"""

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


DATA_FILE = Path("birthrate_social_media_data.csv")
OUTPUT_FILE = Path("birthrate_social_media_chart.png")


def main():
    df = pd.read_csv(DATA_FILE)

    years = df["year"]
    fertility_rate = df["england_wales_total_fertility_rate_children_per_woman"]
    social_media_users = df["uk_social_media_users_millions"]

    fig, ax1 = plt.subplots(figsize=(12, 8), dpi=200)

    # Fertility rate line
    line1 = ax1.plot(
        years,
        fertility_rate,
        marker="o",
        linewidth=3,
        label="Fertility rate",
    )

    ax1.set_xlabel("Year", fontsize=12)
    ax1.set_ylabel("Total fertility rate (children per woman)", fontsize=12)
    ax1.set_ylim(1.35, 1.65)
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

    # Social media users line, second axis
    ax2 = ax1.twinx()

    line2 = ax2.plot(
        years,
        social_media_users,
        marker="s",
        linewidth=3,
        label="Social media users",
    )

    ax2.set_ylabel("UK social media users (millions)", fontsize=12)
    ax2.set_ylim(40, 60)

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
        "UK social media users vs England & Wales total fertility rate, 2020–2024",
        fontsize=12,
        pad=16,
    )

    lines = line1 + line2
    labels = [line.get_label() for line in lines]
    ax1.legend(lines, labels, loc="upper right", frameon=False)

    fig.text(
        0.08,
        0.06,
        "Interpretation: this shows an inverse trend over time. It supports the idea that social media may\n"
        "amplify delay, comparison and uncertainty around family formation. It does not prove causation on its own.",
        fontsize=10,
    )

    fig.text(
        0.08,
        0.02,
        "Sources: ONS Births in England and Wales: 2024; DataReportal UK Digital reports 2020–2024.",
        fontsize=9,
    )

    plt.tight_layout(rect=[0.04, 0.1, 0.96, 0.92])
    plt.savefig(OUTPUT_FILE, bbox_inches="tight")
    print(f"Saved chart to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
