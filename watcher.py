import os
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

SOURCES = [
    {
        "retailer": "Pokemon Center",
        "url": "https://www.pokemoncenter.com/category/trading-card-game",
        "base_url": "https://www.pokemoncenter.com",
    },
    {
        "retailer": "Target",
        "url": "https://www.target.com/s?searchTerm=pokemon+cards",
        "base_url": "https://www.target.com",
    },
    {
        "retailer": "Walmart",
        "url": "https://www.walmart.com/search?q=pokemon+cards",
        "base_url": "https://www.walmart.com",
    },
]

POKEMON_TERMS = [
    "pokemon",
    "pokémon",
]

PRODUCT_TERMS = [
    "elite trainer box",
    "etb",
    "booster bundle",
    "booster box",
    "booster pack",
    "ultra-premium",
    "ultra premium",
    "upc",
    "collection",
    "tin",
    "blister",
    "battle deck",
    "trainer box",
]

HIGH_PRIORITY_TERMS = [
    "151",
    "prismatic",
    "30th",
    "celebration",
    "pokemon center elite trainer box",
    "pokémon center elite trainer box",
    "ultra-premium",
    "ultra premium",
    "upc",
]

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


def fetch_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def clean_text(value):
    value = re.sub(r"\\u0026", "&", value)
    value = re.sub(r"\\/", "/", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def looks_like_pokemon_product(text):
    lowered = text.lower()

    has_pokemon = any(
        term in lowered
        for term in POKEMON_TERMS
    )

    has_product = any(
        term in lowered
        for term in PRODUCT_TERMS
    )

    return has_pokemon and has_product


def priority_score(text):
    lowered = text.lower()

    return sum(
        1
        for term in HIGH_PRIORITY_TERMS
        if term in lowered
    )


def extract_links(html, source):
    discoveries = {}

    patterns = [
        r'href=["\']([^"\']+)["\']',
        r'"url"\s*:\s*"([^"]+)"',
        r'"canonicalUrl"\s*:\s*"([^"]+)"',
    ]

    raw_links = []

    for pattern in patterns:
        raw_links.extend(
            re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            )
        )

    for raw_link in raw_links:
        raw_link = clean_text(raw_link)

        if not raw_link:
            continue

        absolute_url = urljoin(
            source["base_url"],
            raw_link,
        )

        # Keep links likely related to Pokemon product pages.
        surrounding_match = re.search(
            re.escape(raw_link),
            html,
            flags=re.IGNORECASE,
        )

        if surrounding_match:
            start = max(
                0,
                surrounding_match.start() - 350,
            )
            end = min(
                len(html),
                surrounding_match.end() + 350,
            )
            context = clean_text(
                html[start:end]
            )
        else:
            context = absolute_url

        candidate_text = (
            context + " " + absolute_url
        )

        if not looks_like_pokemon_product(
            candidate_text
        ):
            continue

        # Ignore obvious non-product/navigation links.
        bad_terms = [
            "/help",
            "/account",
            "/cart",
            "/privacy",
            "/terms",
            "/login",
            "/search?",
        ]

        if any(
            bad in absolute_url.lower()
            for bad in bad_terms
        ):
            continue

        discoveries[absolute_url] = {
            "url": absolute_url,
            "context": context[:300],
            "priority": priority_score(
                candidate_text
            ),
        }

    return discoveries


def alert_new_products(
    retailer,
    new_products,
):
    ranked = sorted(
        new_products.values(),
        key=lambda item: item["priority"],
        reverse=True,
    )

    # Avoid enormous Discord spam.
    ranked = ranked[:8]

    lines = [
        "🚨 **POKÉMON RADAR ALERT** 🚨",
        "",
        f"**Retailer:** {retailer}",
        "",
    ]

    for product in ranked:
        if product["priority"] >= 1:
            marker = "🔥"
        else:
            marker = "🟢"

        lines.append(
            f"{marker} {product['url']}"
        )

    lines.extend(
        [
            "",
            "New Pokémon TCG listing(s) "
            "detected since the last scan.",
        ]
    )

    send_discord("\n".join(lines))


def main():
    previous_state = load_state()
    current_state = {}

    for source in SOURCES:
        retailer = source["retailer"]

        try:
            html = fetch_html(source["url"])
            discoveries = extract_links(
                html,
                source,
            )

            current_urls = set(
                discoveries.keys()
            )

            old_urls = set(
                previous_state
                .get(retailer, {})
                .get("urls", [])
            )

            current_state[retailer] = {
                "urls": sorted(current_urls),
            }

            # First successful scan = baseline.
            # Do not alert on everything already there.
            if retailer not in previous_state:
                print(
                    f"{retailer}: baseline "
                    f"created with "
                    f"{len(current_urls)} items."
                )
                continue

            new_urls = (
                current_urls - old_urls
            )

            if new_urls:
                new_products = {
                    url: discoveries[url]
                    for url in new_urls
                }

                alert_new_products(
                    retailer,
                    new_products,
                )

                print(
                    f"{retailer}: "
                    f"{len(new_urls)} new "
                    f"listing(s) detected."
                )
            else:
                print(
                    f"{retailer}: no changes."
                )

        except Exception as error:
            print(
                f"{retailer}: check failed: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            # Preserve old state if the retailer
            # temporarily blocks or fails.
            if retailer in previous_state:
                current_state[retailer] = (
                    previous_state[retailer]
                )

    save_state(current_state)


if __name__ == "__main__":
    main()
