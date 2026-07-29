import os
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

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

PRODUCT_TERMS = [
    "pokemon",
    "pokémon",
    "elite trainer box",
    "etb",
    "booster",
    "ultra-premium",
    "ultra premium",
    "upc",
    "collection",
    "tin",
    "blister",
    "battle box",
]

HIGH_PRIORITY_TERMS = [
    "151",
    "prismatic",
    "30th",
    "celebration",
    "elite trainer box",
    "ultra-premium",
    "ultra premium",
    "upc",
]


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK secret is missing.")

    response = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message[:1900]},
        timeout=20,
    )
    response.raise_for_status()


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def fetch_target():
    response = requests.get(
        TARGET_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def looks_like_pokemon(text):
    lowered = text.lower()
    return (
        ("pokemon" in lowered or "pokémon" in lowered)
        and any(term in lowered for term in PRODUCT_TERMS)
    )


def priority_score(text):
    lowered = text.lower()
    return sum(
        1
        for term in HIGH_PRIORITY_TERMS
        if term in lowered
    )


def extract_target_products(html):
    products = {}

    # Target product URLs typically contain /p/
    links = re.findall(
        r'href=["\']([^"\']*/p/[^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    for raw_link in links:
        url = urljoin(TARGET_BASE, raw_link)

        match = re.search(
            re.escape(raw_link),
            html,
            flags=re.IGNORECASE,
        )

        if match:
            start = max(0, match.start() - 500)
            end = min(len(html), match.end() + 500)
            context = html[start:end]
        else:
            context = url

        text = re.sub(r"\s+", " ", context)

        if not looks_like_pokemon(text):
            continue

        products[url] = {
            "url": url,
            "priority": priority_score(text),
        }

    return products


def main():
    previous = load_state()

    html = fetch_target()
    products = extract_target_products(html)

    current_urls = set(products.keys())
    old_urls = set(
        previous.get("Target", {}).get("urls", [])
    )

    new_urls = current_urls - old_urls

    state = {
        "Target": {
            "urls": sorted(current_urls)
        }
    }

    # First real Target scan = baseline only
    if "Target" not in previous:
        print(f"Target baseline: {len(current_urls)} products")
        save_state(state)
        return

    if new_urls:
        ranked = sorted(
            [products[url] for url in new_urls],
            key=lambda x: x["priority"],
            reverse=True,
        )[:8]

        lines = [
            "🚨 **TARGET POKÉMON ALERT** 🚨",
            "",
        ]

        for item in ranked:
            marker = "🔥" if item["priority"] > 0 else "🟢"
            lines.append(f"{marker} {item['url']}")

        send_discord("\n".join(lines))

    print(f"Target products detected: {len(current_urls)}")
    print(f"New Target products: {len(new_urls)}")

    save_state(state)


if __name__ == "__main__":
    main()
