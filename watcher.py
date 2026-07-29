import os
import json
import gzip
import io
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
STATE_FILE = Path("state.json")

TARGET_SITEMAP_INDEX = "https://www.target.com/sitemap_pdp-index.xml.gz"

WALMART_SITEMAPS = [
    "https://www.walmart.com/sitemap_category.xml",
    "https://www.walmart.com/sitemap_browse_fst.xml",
    "https://www.walmart.com/sitemap_brp_02.xml",
    "https://www.walmart.com/sitemap_brp_03.xml",
    "https://www.walmart.com/sitemap_brp_04.xml",
    "https://www.walmart.com/sitemap_brp_05.xml",
]

POKEMON_CENTER_SITEMAPS = [
    "https://www.pokemoncenter.com/sitemaps/pages.xml",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PokemonRadar/1.0; "
        "+https://github.com/)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

POKEMON_TERMS = [
    "pokemon",
    "pokémon",
]

TCG_TERMS = [
    "tcg",
    "trading-card",
    "trading-card-game",
    "elite-trainer",
    "trainer-box",
    "booster",
    "bundle",
    "ultra-premium",
    "collection",
    "mini-tin",
    "tin",
    "blister",
    "151",
    "prismatic",
    "celebration",
    "pitch-black",
]


def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK secret is missing.")

    response = requests.post(
        DISCORD_WEBHOOK,
        json={"content": message[:1900]},
        timeout=20,
    )
    response.raise_for_status()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def fetch_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40,
        allow_redirects=True,
    )
    response.raise_for_status()

    content = response.content

    # Some sitemap files are gzipped.
    if (
        url.endswith(".gz")
        or content[:2] == b"\x1f\x8b"
    ):
        try:
            content = gzip.decompress(content)
        except Exception:
            pass

    return content


def extract_xml_urls(content: bytes) -> list[str]:
    text = content.decode(
        "utf-8",
        errors="ignore",
    )

    return re.findall(
        r"<loc>\s*(.*?)\s*</loc>",
        text,
        flags=re.IGNORECASE,
    )


def looks_pokemon_tcg(url: str) -> bool:
    lowered = url.lower()

    pokemon_hit = any(
        term in lowered
        for term in POKEMON_TERMS
    )

    tcg_hit = any(
        term in lowered
        for term in TCG_TERMS
    )

    return pokemon_hit and tcg_hit


def read_sitemap_recursive(
    url: str,
    max_children: int = 25,
) -> set[str]:

    found = set()

    try:
        content = fetch_bytes(url)
        urls = extract_xml_urls(content)
    except Exception as exc:
        print(f"Sitemap failed: {url}: {exc}")
        return found

    child_sitemaps = [
        item
        for item in urls
        if ".xml" in item.lower()
    ]

    page_urls = [
        item
        for item in urls
        if item not in child_sitemaps
    ]

    found.update(
        item
        for item in page_urls
        if looks_pokemon_tcg(item)
    )

    for child in child_sitemaps[:max_children]:
        try:
            child_content = fetch_bytes(child)
            child_urls = extract_xml_urls(
                child_content
            )

            found.update(
                item
                for item in child_urls
                if looks_pokemon_tcg(item)
            )

        except Exception as exc:
            print(
                f"Child sitemap failed: "
                f"{child}: {exc}"
            )

    return found


def target_scan() -> set[str]:
    return read_sitemap_recursive(
        TARGET_SITEMAP_INDEX,
        max_children=30,
    )


def walmart_scan() -> set[str]:
    results = set()

    for sitemap in WALMART_SITEMAPS:
        results.update(
            read_sitemap_recursive(
                sitemap,
                max_children=10,
            )
        )

    return results


def pokemon_center_scan() -> set[str]:
    results = set()

    for sitemap in POKEMON_CENTER_SITEMAPS:
        results.update(
            read_sitemap_recursive(
                sitemap,
                max_children=20,
            )
        )

    return results


def alert_target(new_urls: set[str]) -> None:
    if not new_urls:
        return

    urls = sorted(new_urls)[:8]

    lines = [
        "🚨 **TARGET POKÉMON LISTING ALERT**",
        "",
        "New Pokémon TCG product page(s) detected:",
        "",
    ]

    for url in urls:
        lines.append(f"🎯 {url}")

    lines.extend(
        [
            "",
            "⚠️ New listing ≠ guaranteed in stock.",
            "**Check Target now.**",
        ]
    )

    send_discord("\n".join(lines))


def alert_activity(
    retailer: str,
    new_urls: set[str],
) -> None:

    if not new_urls:
        return

    examples = sorted(new_urls)[:4]

    lines = [
        f"👀 **{retailer.upper()} POKÉMON ACTIVITY**",
        "",
        (
            "New Pokémon TCG-related page/index "
            "activity was detected."
        ),
        "",
    ]

    for url in examples:
        lines.append(f"• {url}")

    lines.extend(
        [
            "",
            "⚠️ This does NOT guarantee inventory.",
            f"**Check {retailer} now.**",
        ]
    )

    send_discord("\n".join(lines))


def main() -> None:
    previous = load_state()

    scanners = {
        "Target": target_scan,
        "Walmart": walmart_scan,
        "Pokemon Center": pokemon_center_scan,
    }

    current = {}

    for retailer, scanner in scanners.items():
        try:
            urls = scanner()

            old_urls = set(
                previous
                .get(retailer, {})
                .get("urls", [])
            )

            new_urls = urls - old_urls

            current[retailer] = {
                "status": "working",
                "count": len(urls),
                "urls": sorted(urls),
            }

            # First successful run = baseline.
            if retailer not in previous:
                print(
                    f"{retailer}: baseline "
                    f"created with {len(urls)} URLs."
                )
                continue

            if retailer == "Target":
                alert_target(new_urls)

            elif retailer == "Walmart":
                alert_activity(
                    "Walmart",
                    new_urls,
                )

            elif retailer == "Pokemon Center":
                alert_activity(
                    "Pokémon Center",
                    new_urls,
                )

            print(
                f"{retailer}: "
                f"{len(urls)} tracked, "
                f"{len(new_urls)} new."
            )

        except Exception as exc:
            print(
                f"{retailer}: ERROR: {exc}"
            )

            # Preserve previous state instead of
            # treating an error as zero inventory.
            if retailer in previous:
                current[retailer] = (
                    previous[retailer]
                )
                current[retailer][
                    "last_scan_error"
                ] = str(exc)
            else:
                current[retailer] = {
                    "status": "error",
                    "error": str(exc),
                    "urls": [],
                    "count": 0,
                }

    save_state(current)


if __name__ == "__main__":
    main()
