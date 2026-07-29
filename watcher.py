import os
import json
import re
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

TARGET_URL = "https://www.target.com/s?searchTerm=pokemon+cards"
TARGET_BASE = "https://www.target.com"

# Public community feeds used only as early-warning signals
FEEDS = [
    "https://www.reddit.com/r/PokemonDeals/new/.rss",
    "https://www.reddit.com/r/PKMNTCGDeals/new/.rss",
]

HEADERS = {
    "User-Agent": "PokemonRadar/1.0 stock-monitor",
    "Accept-Language": "en-US,en;q=0.9",
}

TARGET_TERMS = [
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

HIGH_PRIORITY = [
    "151",
    "prismatic",
    "30th",
    "celebration",
    "elite trainer box",
    "upc",
    "ultra-premium",
    "booster bundle",
]

PC_TERMS = [
    "pokemon center",
    "pokémon center",
]

WALMART_TERMS = [
    "walmart",
]

ACTIVITY_TERMS = [
    "restock",
    "stock",
    "drop",
    "loaded",
    "loading",
    "live",
    "available",
    "preorder",
    "pre-order",
    "inventory",
    "sku",
    "listing",
]


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK is missing.")

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


def fetch(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


# ---------------- TARGET ----------------

def target_score(text):
    lowered = text.lower()

    return sum(
        1
        for term in HIGH_PRIORITY
        if term in lowered
    )


def extract_target_products(html):
    products = {}

    links = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

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

        context = re.sub(
            r"\s+",
            " ",
            html[start:end],
        )

        lowered = context.lower()

        if not (
            "pokemon" in lowered
            or "pokémon" in lowered
        ):
            continue

        if not any(
            term in lowered
            for term in TARGET_TERMS
        ):
            continue

        products[url] = {
            "url": url,
            "score": target_score(context),
            "available": (
                "add to cart" in lowered
                or "ship it" in lowered
            ),
        }

    return products


def check_target(previous):
    try:
        response = fetch(TARGET_URL)
        products = extract_target_products(response.text)

        old = (
            previous
            .get("Target", {})
            .get("products", {})
        )

        alerts = []

        for url, data in products.items():
            old_data = old.get(url)

            if old_data is None:
                alerts.append(data)

            elif (
                not old_data.get("available", False)
                and data.get("available", False)
            ):
                alerts.append(data)

        if alerts:
            alerts.sort(
                key=lambda x: x["score"],
                reverse=True,
            )

            lines = [
                "🚨 **TARGET POKÉMON ALERT**",
                "",
            ]

            for item in alerts[:8]:
                marker = (
                    "🔥"
                    if item["score"] > 0
                    else "🟢"
                )

                status = (
                    "IN STOCK"
                    if item["available"]
                    else "NEW LISTING"
                )

                lines.append(
                    f"{marker} **{status}**\n"
                    f"{item['url']}"
                )

            send_discord("\n\n".join(lines))

        return {
            "status": "working",
            "count": len(products),
            "products": products,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


# ---------------- EARLY WARNING FEEDS ----------------

def parse_feed(feed_url):
    response = fetch(feed_url)

    root = ET.fromstring(response.content)

    entries = []

    # Reddit uses Atom feeds
    namespace = {
        "atom": "http://www.w3.org/2005/Atom"
    }

    for entry in root.findall(
        "atom:entry",
        namespace,
    ):
        title_el = entry.find(
            "atom:title",
            namespace,
        )

        link_el = entry.find(
            "atom:link",
            namespace,
        )

        id_el = entry.find(
            "atom:id",
            namespace,
        )

        title = (
            title_el.text
            if title_el is not None
            else ""
        )

        link = (
            link_el.attrib.get("href", "")
            if link_el is not None
            else ""
        )

        entry_id = (
            id_el.text
            if id_el is not None
            else link
        )

        entries.append(
            {
                "id": entry_id,
                "title": title,
                "link": link,
            }
        )

    return entries


def looks_like_activity(title, retailer_terms):
    lowered = title.lower()

    retailer_hit = any(
        term in lowered
        for term in retailer_terms
    )

    activity_hit = any(
        term in lowered
        for term in ACTIVITY_TERMS
    )

    pokemon_hit = (
        "pokemon" in lowered
        or "pokémon" in lowered
        or "tcg" in lowered
        or retailer_hit
    )

    return (
        retailer_hit
        and activity_hit
        and pokemon_hit
    )


def check_early_warnings(previous):
    old_ids = set(
        previous
        .get("Early Warnings", {})
        .get("seen_ids", [])
    )

    current_ids = set(old_ids)

    pc_alerts = []
    walmart_alerts = []

    for feed in FEEDS:
        try:
            entries = parse_feed(feed)
        except Exception as exc:
            print(
                f"Feed failed: {feed}: {exc}"
            )
            continue

        for entry in entries:
            entry_id = entry["id"]

            current_ids.add(entry_id)

            if entry_id in old_ids:
                continue

            title = entry["title"]

            if looks_like_activity(
                title,
                PC_TERMS,
            ):
                pc_alerts.append(entry)

            if looks_like_activity(
                title,
                WALMART_TERMS,
            ):
                walmart_alerts.append(entry)

    if pc_alerts:
        lines = [
            "👀 **POKÉMON CENTER ACTIVITY**",
            "",
            "Possible TCG inventory/drop activity detected.",
            "**CHECK POKÉMON CENTER NOW.**",
            "",
        ]

        for item in pc_alerts[:5]:
            lines.append(
                f"• {item['title']}\n"
                f"{item['link']}"
            )

        send_discord("\n\n".join(lines))

    if walmart_alerts:
        lines = [
            "👀 **WALMART POKÉMON ACTIVITY**",
            "",
            "Possible inventory/listing activity detected.",
            "**CHECK WALMART NOW.**",
            "",
        ]

        for item in walmart_alerts[:5]:
            lines.append(
                f"• {item['title']}\n"
                f"{item['link']}"
            )

        send_discord("\n\n".join(lines))

    return {
        "seen_ids": sorted(current_ids)[-500:]
    }


def main():
    previous = load_state()

    current = {}

    current["Target"] = check_target(
        previous
    )

    current["Early Warnings"] = (
        check_early_warnings(previous)
    )

    save_state(current)

    print(
        json.dumps(
            current,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
