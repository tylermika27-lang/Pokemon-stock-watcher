import os
import re
from urllib.parse import urljoin

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

TARGET_URL = "https://www.target.com/s?searchTerm=pokemon+cards"
TARGET_BASE = "https://www.target.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

POKEMON_TERMS = [
    "pokemon",
    "pokémon",
    "elite trainer box",
    "booster",
    "bundle",
    "collection",
    "tin",
    "blister",
    "upc",
    "ultra-premium",
]


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK missing.")

    response = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message[:1900]},
        timeout=20,
    )
    response.raise_for_status()


def main():
    response = requests.get(
        TARGET_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    html = response.text

    links = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    found = []

    for raw_link in links:
        url = urljoin(TARGET_BASE, raw_link)

        if "/p/" not in url.lower():
            continue

        match = re.search(
            re.escape(raw_link),
            html,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        start = max(0, match.start() - 1000)
        end = min(len(html), match.end() + 1000)

        context = html[start:end].lower()

        if not any(
            term in context
            for term in POKEMON_TERMS
        ):
            continue

        if url not in found:
            found.append(url)

    if found:
        lines = [
            "🧪 **TARGET RADAR TEST**",
            "",
            f"✅ Detector found {len(found)} Target product links.",
            "",
        ]

        for url in found[:8]:
            lines.append(f"🎯 {url}")

        send_discord("\n\n".join(lines))

    else:
        send_discord(
            "❌ **TARGET RADAR TEST FAILED**\n\n"
            "Target page loaded, but the detector found "
            "ZERO qualifying product links.\n\n"
            "Do NOT trust the Target monitor yet."
        )


if __name__ == "__main__":
    main()
