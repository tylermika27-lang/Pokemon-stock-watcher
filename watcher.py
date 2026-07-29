import os
import requests
from datetime import datetime

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# Retailer Pokémon TCG category/search pages.
# This is the starting discovery layer. We will improve each retailer
# separately because their sites expose inventory differently.
SOURCES = [
    {
        "retailer": "Pokemon Center",
        "url": "https://www.pokemoncenter.com/category/trading-card-game",
    },
    {
        "retailer": "Target",
        "url": "https://www.target.com/s?searchTerm=pokemon+cards",
    },
    {
        "retailer": "Walmart",
        "url": "https://www.walmart.com/search?q=pokemon+cards",
    },
]

KEYWORDS = [
    "pokemon",
    "elite trainer box",
    "etb",
    "booster bundle",
    "booster box",
    "ultra-premium",
    "ultra premium",
    "upc",
    "collection",
    "tin",
    "blister",
    "151",
    "prismatic",
    "30th celebration",
    "pitch black",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    )
}


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK secret is missing.")

    response = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message},
        timeout=20,
    )
    response.raise_for_status()


def check_source(source):
    response = requests.get(
        source["url"],
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    text = response.text.lower()

    matches = [
        keyword
        for keyword in KEYWORDS
        if keyword.lower() in text
    ]

    return matches


def main():
    results = []

    for source in SOURCES:
        try:
            matches = check_source(source)

            results.append(
                f"**{source['retailer']}**: "
                f"page reachable — {len(matches)} watch terms detected."
            )

        except Exception as error:
            results.append(
                f"**{source['retailer']}**: check failed — "
                f"{type(error).__name__}"
            )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    message = (
        "🧪 **POKÉMON RADAR TEST**\n"
        f"{timestamp}\n\n"
        + "\n".join(results)
        + "\n\nMonitor connected successfully."
    )

    send_discord(message)


if __name__ == "__main__":
    main()
