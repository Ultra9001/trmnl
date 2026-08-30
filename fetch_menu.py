#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict

import requests
from bs4 import BeautifulSoup


URL = "https://paypams.com/TN_Menus.aspx"
OUT_DIR = Path("paypams_me_debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    data = {}

    form = soup.find("form")
    if not form:
        return data

    for element in form.find_all("input", type="hidden"):
        name = element.get("name")
        if name:
            data[name] = element.get("value", "")

    return data


def save_text(name: str, text: str) -> None:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")


def print_all_links(soup: BeautifulSoup) -> None:
    print()
    print("=" * 80)
    print("ALL LINKS AFTER MAINE POST")
    print("=" * 80)

    links = soup.find_all("a")

    print("Number of links:", len(links))

    for i, link in enumerate(links, 1):
        text = link.get_text(" ", strip=True)
        href = link.get("href")
        onclick = link.get("onclick")
        link_id = link.get("id")
        name = link.get("name")

        print()
        print(f"LINK #{i}")
        print("  text   :", repr(text))
        print("  href   :", repr(href))
        print("  onclick:", repr(onclick))
        print("  id     :", repr(link_id))
        print("  name   :", repr(name))
        print("  HTML   :", str(link)[:2000])


def locate_lewiston(soup: BeautifulSoup):
    print()
    print("=" * 80)
    print("LEWISTON LINK")
    print("=" * 80)

    matches = []

    for link in soup.find_all("a"):

        text = link.get_text(" ", strip=True)

        if "lewiston" in text.lower():

            matches.append(link)

    if not matches:
        print("No Lewiston link found.")
        return None

    for i, link in enumerate(matches, 1):

        print()
        print(f"MATCH #{i}")
        print("  text   :", link.get_text(" ", strip=True))
        print("  href   :", link.get("href"))
        print("  onclick:", link.get("onclick"))
        print("  id     :", link.get("id"))
        print()
        print("FULL HTML:")
        print(link)

    return matches[0]


def inspect_scripts(soup: BeautifulSoup) -> None:
    print()
    print("=" * 80)
    print("SCRIPTS REFERENCING LEWISTON / DISTRICT / SCHOOL")
    print("=" * 80)

    count = 0

    for i, script in enumerate(soup.find_all("script")):

        text = script.get_text("\n", strip=False)

        if not text:
            continue

        if any(
            x.lower() in text.lower()
            for x in [
                "lewiston",
                "district",
                "school",
                "__doPostBack",
                "PostBackOptions",
            ]
        ):

            count += 1

            print()
            print(f"SCRIPT #{i}")
            print("-" * 80)
            print(text[:15000])

    print()
    print("Matching scripts:", count)


def main() -> int:

    print("=" * 80)
    print("PAYPAMS MAINE -> LEWISTON DIAGNOSTIC")
    print("=" * 80)

    session = requests.Session()
    session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    print()
    print("1. GET initial PayPAMS page...")

    try:
        r1 = session.get(
            URL,
            timeout=30,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print("GET failed:", exc)
        return 1

    r1.raise_for_status()

    print("Status:", r1.status_code)
    print("URL:", r1.url)

    save_text(
        "01_initial.html",
        r1.text,
    )

    soup1 = BeautifulSoup(
        r1.text,
        "html.parser",
    )

    # ------------------------------------------------------------------
    # POST MAINE
    # ------------------------------------------------------------------

    print()
    print("2. Selecting Maine (ME)...")

    data = get_hidden_fields(soup1)

    data["h_UC_State:h_DD_State"] = "ME"
    data["h_BTN_Submit"] = "Submit"
    data["__EVENTTARGET"] = ""
    data["__EVENTARGUMENT"] = ""

    try:
        r2 = session.post(
            URL,
            data=data,
            timeout=30,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print("POST failed:", exc)
        return 1

    r2.raise_for_status()

    print("Status:", r2.status_code)
    print("URL:", r2.url)
    print("Length:", len(r2.text))

    save_text(
        "02_after_ME_post.html",
        r2.text,
    )

    soup2 = BeautifulSoup(
        r2.text,
        "html.parser",
    )

    # ------------------------------------------------------------------
    # INSPECT LINKS
    # ------------------------------------------------------------------

    print_all_links(soup2)

    lewiston = locate_lewiston(soup2)

    inspect_scripts(soup2)

    # ------------------------------------------------------------------
    # SAVE LEWISTON HTML
    # ------------------------------------------------------------------

    if lewiston is not None:

        info = {
            "text": lewiston.get_text(" ", strip=True),
            "href": lewiston.get("href"),
            "onclick": lewiston.get("onclick"),
            "id": lewiston.get("id"),
            "name": lewiston.get("name"),
            "html": str(lewiston),
        }

        save_text(
            "lewiston_link.json",
            json.dumps(
                info,
                indent=2,
                ensure_ascii=False,
            ),
        )

        print()
        print("=" * 80)
        print("FOUND LEWISTON")
        print("=" * 80)

        print(
            json.dumps(
                info,
                indent=2,
                ensure_ascii=False,
            )
        )

    else:

        print()
        print(
            "ERROR: Could not locate Lewiston."
        )

    # ------------------------------------------------------------------
    # DONE
    # ------------------------------------------------------------------

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)

    print(
        "Look at:",
        OUT_DIR.resolve(),
    )

    print()
    print(
        "The critical output is "
        "'lewiston_link.json'."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
