import os
import json
import re
import hashlib
from pathlib import Path
from urllib.parse import urljoin

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

TARGET_URL = "https://www.target.com/s?searchTerm=pokemon+cards"
TARGET_BASE = "https://www.target.com"

WALMART_SITEMAPS = [
    "https://www.walmart.com/sitemap_category.xml",
    "https://www.walmart.com/sitemap_browse_fst.xml",
]

POKEMON_CENTER_URL = (
    "https://www.pokemoncenter.com/category/trading-card-game"
)

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
    "tcg",
    "elite trainer box",
    "booster",
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
    "booster bundle",
    "upc",
    "ultra-premium",
]


def send_discord(message):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK missing.")

    r = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message[:1900]},
        timeout=20,
    )
    r.raise_for_status()


def fetch(url):
    return requests.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=True,
    )


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


def priority_score(text):
    lowered = text.lower()

    return sum(
        1
        for term in HIGH_PRIORITY
        if term in lowered
    )


# ---------------- TARGET ----------------

def extract_target_products(html):
    products = {}

    links = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        re.I,
    )

    for raw_link in links:
        url = urljoin(TARGET_BASE, raw_link)

        if "/p/" not in url.lower():
            continue

        match = re.search(
            re.escape(raw_link),
            html,
            re.I,
        )

        if not match:
            continue

        start = max(0, match.start() - 900)
        end = min(len(html), match.end() + 900)

        context = re.sub(
            r"\s+",
            " ",
            html[start:end],
        )

        lowered = context.lower()

        if not any(
            term in lowered
            for term in POKEMON_TERMS
        ):
            continue

        available = (
            "add to cart" in lowered
            or "ship it" in lowered
        )

        products[url] = {
            "available": available,
            "score": priority_score(context),
        }

    return products


def check_target(previous):
    response = fetch(TARGET_URL)
    response.raise_for_status()

    products = extract_target_products(
        response.text
    )

    old_products = (
        previous
        .get("Target", {})
        .get("products", {})
    )

    alerts = []

    for url, data in products.items():
        old = old_products.get(url)

        if old is None:
            alerts.append((url, data, "NEW LISTING"))

        elif (
            not old.get("available", False)
            and data["available"]
        ):
            alerts.append((url, data, "IN STOCK"))

    if alerts:
        alerts.sort(
            key=lambda x: x[1]["score"],
            reverse=True,
        )

        lines = [
            "🚨 **TARGET POKÉMON ALERT**",
            "",
        ]

        for url, data, status in alerts[:8]:
            marker = (
                "🔥"
                if data["score"] > 0
                else "🟢"
            )

            lines.append(
                f"{marker} **{status}**\n{url}"
            )

        send_discord("\n\n".join(lines))

    return {
        "status": "working",
        "count": len(products),
        "products": products,
    }


# ---------------- WALMART ----------------

def walmart_snapshot():
    snapshot_parts = []
    reachable = 0

    for url in WALMART_SITEMAPS:
        try:
            response = fetch(url)

            if response.status_code != 200:
                continue

            reachable += 1

            text = response.text.lower()

            # Keep only lines that look Pokemon-related.
            pokemon_lines = [
                line.strip()
                for line in text.splitlines()
                if "pokemon" in line
            ]

            snapshot_parts.extend(
                pokemon_lines
            )

        except Exception:
            continue

    combined = "\n".join(
        sorted(set(snapshot_parts))
    )

    digest = hashlib.sha256(
        combined.encode("utf-8")
    ).hexdigest()

    return {
        "reachable": reachable,
        "matches": len(snapshot_parts),
        "hash": digest,
    }


def check_walmart(previous):
    current = walmart_snapshot()

    old_hash = (
        previous
        .get("Walmart", {})
        .get("hash")
    )

    # Only alert after baseline exists.
    if (
        old_hash
        and current["hash"] != old_hash
        and current["matches"] > 0
    ):
        send_discord(
            "👀 **WALMART POKÉMON ACTIVITY**\n\n"
            "Walmart's public catalog/index changed "
            "around Pokémon-related pages.\n\n"
            "⚠️ This does NOT guarantee stock.\n"
            "**Check Walmart now.**"
        )

    return {
        "status": (
            "watching"
            if current["reachable"] > 0
            else "unavailable"
        ),
        "reachable_sitemaps": current["reachable"],
        "pokemon_matches": current["matches"],
        "hash": current["hash"],
    }


# ---------------- POKEMON CENTER ----------------

def check_pokemon_center(previous):
    try:
        response = fetch(POKEMON_CENTER_URL)

        body = response.text

        digest = hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()

        old_hash = (
            previous
            .get("Pokemon Center", {})
            .get("hash")
        )

        usable = (
            response.status_code == 200
            and len(response.content) > 10000
        )

        if (
            usable
            and old_hash
            and digest != old_hash
        ):
            send_discord(
                "🚨 **POKÉMON CENTER TCG ACTIVITY**\n\n"
                "Pokémon Center's TCG page changed.\n\n"
                "⚠️ This does NOT guarantee stock.\n"
                "**Check Pokémon Center immediately.**\n\n"
                "https://www.pokemoncenter.com/category/"
                "trading-card-game"
            )

        return {
            "status": (
                "watching"
                if usable
                else "limited"
            ),
            "http": response.status_code,
            "bytes": len(response.content),
            "hash": digest,
        }

    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
        }


def main():
    previous = load_state()

    current = {}

    try:
        current["Target"] = check_target(
            previous
        )
    except Exception as exc:
        current["Target"] = {
            "status": "error",
            "error": str(exc),
        }

    current["Walmart"] = check_walmart(
        previous
    )

    current["Pokemon Center"] = (
        check_pokemon_center(previous)
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
