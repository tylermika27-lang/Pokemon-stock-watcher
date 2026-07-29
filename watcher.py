import os
import json
import re
from pathlib import Path

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

SOURCES = {
    "Pokemon Center": "https://www.pokemoncenter.com/category/trading-card-game",
    "Target": "https://www.target.com/s?searchTerm=pokemon+cards",
    "Walmart": "https://www.walmart.com/browse/collectibles/pokemon-cards/5967908_9807313_4252400",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

WATCH_TERMS = [
    "pokemon",
    "pokémon",
    "tcg",
    "elite trainer box",
    "etb",
    "booster bundle",
    "booster box",
    "booster pack",
    "ultra-premium",
    "ultra premium",
    "upc",
    "mini tin",
    "tin",
    "blister",
    "collection",
    "151",
    "prismatic",
    "30th",
    "celebration",
    "pitch black",
]

AVAILABILITY_TERMS = [
    "add to cart",
    "add",
    "in stock",
    "preorder",
    "pre-order",
    "available",
    "out of stock",
    "sold out",
]


def send_discord(message):
    if not DISCORD_WEBHOOK:
        return

    r = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message[:1900]},
        timeout=20,
    )
    r.raise_for_status()


def fetch(url):
    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=True,
    )
    return r


def normalize(text):
    text = text.replace("\\u0026", "&")
    text = text.replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def inspect_page(name, url):
    try:
        response = fetch(url)

        text = normalize(response.text)

        found_watch_terms = [
            term for term in WATCH_TERMS
            if term in text
        ]

        found_availability_terms = [
            term for term in AVAILABILITY_TERMS
            if term in text
        ]

        href_count = len(
            re.findall(
                r'href=["\'][^"\']+["\']',
                response.text,
                flags=re.I,
            )
        )

        product_path_count = len(
            re.findall(
                r'/(?:p|ip|product)/[^"\'> ]+',
                response.text,
                flags=re.I,
            )
        )

        json_script_count = len(
            re.findall(
                r'<script[^>]+type=["\']application/(?:ld\+json|json)["\']',
                response.text,
                flags=re.I,
            )
        )

        return {
            "status": response.status_code,
            "bytes": len(response.content),
            "watch_terms": found_watch_terms,
            "availability_terms": found_availability_terms,
            "href_count": href_count,
            "product_path_count": product_path_count,
            "json_script_count": json_script_count,
        }

    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {e}"
        }


def main():
    results = {}

    for name, url in SOURCES.items():
        results[name] = inspect_page(name, url)

    STATE_FILE.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    lines = [
        "🧪 **POKÉMON RETAILER DIAGNOSTIC**",
        "",
    ]

    for retailer, info in results.items():
        if "error" in info:
            lines.append(
                f"❌ **{retailer}** — {info['error']}"
            )
            continue

        lines.append(
            f"**{retailer}**"
            f"\nHTTP: {info['status']}"
            f"\nPage bytes: {info['bytes']}"
            f"\nLinks: {info['href_count']}"
            f"\nProduct paths: {info['product_path_count']}"
            f"\nJSON scripts: {info['json_script_count']}"
            f"\nWatch terms: {len(info['watch_terms'])}"
            f"\nAvailability terms: {len(info['availability_terms'])}"
            "\n"
        )

    send_discord("\n".join(lines))


if __name__ == "__main__":
    main()
