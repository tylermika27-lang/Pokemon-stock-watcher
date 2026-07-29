import os
import json
import re
from pathlib import Path

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
DEBUG_FILE = Path("target_debug.json")

TARGET_URL = "https://www.target.com/s?searchTerm=pokemon+cards"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


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

    scripts = re.findall(
        r'<script[^>]*type=["\']application/(?:ld\+json|json)["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    results = []

    for index, script in enumerate(scripts):
        raw = script.strip()

        try:
            parsed = json.loads(raw)

            results.append(
                {
                    "index": index,
                    "valid_json": True,
                    "data": parsed,
                }
            )

        except Exception:
            results.append(
                {
                    "index": index,
                    "valid_json": False,
                    "preview": raw[:5000],
                }
            )

    DEBUG_FILE.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    pokemon_hits = html.lower().count("pokemon")
    add_to_cart_hits = html.lower().count("add to cart")

    send_discord(
        "🧪 **TARGET JSON DIAGNOSTIC**\n\n"
        f"HTTP: {response.status_code}\n"
        f"Page bytes: {len(response.content)}\n"
        f"JSON scripts found: {len(scripts)}\n"
        f"'pokemon' occurrences: {pokemon_hits}\n"
        f"'add to cart' occurrences: {add_to_cart_hits}\n\n"
        "Saved Target JSON to `target_debug.json`."
    )


if __name__ == "__main__":
    main()
