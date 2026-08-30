#!/usr/bin/env python3

"""
PayPAMS Maine -> Lewiston -> Menu scraper

Flow:

    GET TN_Menus.aspx
        |
        v
    POST state = ME
        |
        v
    Receive Maine district list
        |
        v
    POST __EVENTTARGET = _ctl7
        |
        v
    Receive Lewiston Public Schools menu page
        |
        v
    Extract menu HTML / embedded JSON / useful data

Requirements:

    pip install requests beautifulsoup4

Run:

    python fetch_menu.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIGURATION
# ============================================================================

URL = "https://paypams.com/TN_Menus.aspx"

STATE = "ME"
DISTRICT_NAME = "Lewiston Public Schools"

# We discovered this from the actual Lewiston link returned by PayPAMS.
LEWISTON_EVENTTARGET = "_ctl7"

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
        "q=0.9,image/avif,image/webp,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ============================================================================
# HELPERS
# ============================================================================

def save_text(filename: str, text: str) -> Path:
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")
    return path


def get_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Extract every hidden input from the first form.

    ASP.NET WebForms relies heavily on these values being submitted back.
    """

    result: Dict[str, str] = {}

    form = soup.find("form")

    if form is None:
        print("WARNING: No <form> element found.")
        return result

    for element in form.find_all("input", type="hidden"):

        name = element.get("name")

        if not name:
            continue

        result[name] = element.get("value", "")

    return result


def print_response(
    label: str,
    response: requests.Response,
) -> None:

    print()
    print("=" * 80)
    print(label)
    print("=" * 80)

    print("Status       :", response.status_code)
    print("URL          :", response.url)
    print("Content-Type :", response.headers.get("content-type"))
    print("Bytes        :", len(response.content))
    print()


def print_page_title(
    soup: BeautifulSoup,
) -> None:

    title = soup.title

    print(
        "HTML title:",
        title.get_text(" ", strip=True)
        if title
        else "(none)",
    )


def print_page_text(
    soup: BeautifulSoup,
    limit: int = 150,
) -> None:

    print()
    print("=" * 80)
    print("VISIBLE PAGE TEXT")
    print("=" * 80)

    text = soup.get_text(
        "\n",
        strip=True,
    )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines[:limit]:
        print(line)


def print_forms(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("FORMS")
    print("=" * 80)

    forms = soup.find_all("form")

    print("Form count:", len(forms))

    for i, form in enumerate(forms, 1):

        print()
        print(f"FORM #{i}")

        print("  id    :", form.get("id"))
        print("  name  :", form.get("name"))
        print("  action:", form.get("action"))
        print("  method:", form.get("method"))

        for element in form.find_all(
            ["input", "button", "select"]
        ):

            print(
                "   ",
                element.name,
                "id=",
                element.get("id"),
                "name=",
                element.get("name"),
                "value=",
                element.get("value"),
            )


def print_all_links(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("LINKS")
    print("=" * 80)

    links = soup.find_all("a")

    print("Link count:", len(links))

    for i, link in enumerate(links, 1):

        text = link.get_text(
            " ",
            strip=True,
        )

        href = link.get("href")

        if not text and not href:
            continue

        print()
        print(f"LINK #{i}")
        print("  text   :", repr(text))
        print("  href   :", repr(href))
        print("  onclick:", repr(link.get("onclick")))
        print("  id     :", repr(link.get("id")))
        print("  name   :", repr(link.get("name")))

        # Print complete HTML for interesting links.
        if (
            "lewiston" in text.lower()
            or "__doPostBack" in str(href)
            or "PostBackOptions" in str(href)
        ):
            print("  HTML   :", str(link)[:3000])


def extract_menu_json(
    soup: BeautifulSoup,
) -> Optional[list]:

    print()
    print("=" * 80)
    print("EMBEDDED MENU JSON")
    print("=" * 80)

    candidates = [
        "h_SCRIPT_menudata",
        "menudata",
        "menuData",
        "menu-data",
    ]

    for script_id in candidates:

        script = soup.find(
            "script",
            id=script_id,
        )

        if script is None:
            continue

        raw = script.string or script.get_text()

        raw = raw.strip()

        print(
            f"Found script id={script_id!r}"
        )

        print(
            "Raw length:",
            len(raw),
        )

        save_text(
            "menu_data_raw.txt",
            raw,
        )

        try:

            data = json.loads(raw)

        except json.JSONDecodeError as exc:

            print(
                "JSON parse error:",
                exc,
            )

            return None

        if isinstance(data, list):

            print(
                "Menu item count:",
                len(data),
            )

            path = OUT_DIR / "menu_data.json"

            path.write_text(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            print(
                "Saved:",
                path,
            )

            return data

        print(
            "JSON was not a list:",
            type(data).__name__,
        )

        return None

    print(
        "No known menu JSON script found."
    )

    return None


def search_html_for_menu_signatures(
    html: str,
) -> None:

    print()
    print("=" * 80)
    print("MENU SIGNATURE SEARCH")
    print("=" * 80)

    signatures = [
        "h_SCRIPT_menudata",
        "DistrictID",
        "ItemCode",
        "ServingTypeID",
        "DataCalDay",
        "CaloriesStr",
        "ItemName",
        "MenuName",
        "Lewiston",
        "School Menu",
        "Breakfast",
        "Lunch",
    ]

    for signature in signatures:

        count = html.lower().count(
            signature.lower()
        )

        print(
            f"{signature:20s} : {count}"
        )


def extract_possible_json_blocks(
    html: str,
) -> None:
    """
    Look for script blocks containing JSON-ish content.

    This is intentionally broad because we don't yet know how PayPAMS
    embeds the Lewiston menu records in this response.
    """

    print()
    print("=" * 80)
    print("POSSIBLE JSON / MENU SCRIPT BLOCKS")
    print("=" * 80)

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found = 0

    for index, script in enumerate(
        soup.find_all("script")
    ):

        text = script.get_text(
            "\n",
            strip=False,
        )

        if not text:
            continue

        lower = text.lower()

        if any(
            term in lower
            for term in [
                "districtid",
                "itemcode",
                "servingtypeid",
                "datacalday",
                "itemname",
                "menuname",
            ]
        ):

            found += 1

            filename = (
                f"menu_related_script_{found}.txt"
            )

            save_text(
                filename,
                text,
            )

            print()
            print(
                f"Script #{index} appears menu-related."
            )

            print(
                "Saved as:",
                filename,
            )

    print()
    print(
        "Potential menu scripts found:",
        found,
    )


def summarize_menu_items(
    items: list,
) -> None:

    if not items:
        return

    print()
    print("=" * 80)
    print("MENU ITEM SAMPLE")
    print("=" * 80)

    keys = [
        "DistrictID",
        "ItemCode",
        "ItemName",
        "ItemNumber",
        "ServingTypeID",
        "ServingTypeName",
        "ServingSize",
        "MenuName",
        "DataCalDay",
        "CaloriesStr",
        "FatGStr",
        "SatFatGStr",
        "TransFatStr",
        "CholMgStr",
        "SodMgStr",
        "CHOGStr",
        "FiberStr",
        "SugarGStr",
        "AddedSugarGStr",
        "ProteinGStr",
        "Allergens",
        "AllergensStr",
        "AttributesStr",
        "HealthClaimsStr",
    ]

    for i, item in enumerate(
        items[:20],
        1,
    ):

        if not isinstance(item, dict):
            continue

        print()
        print(
            f"ITEM #{i}"
        )

        for key in keys:

            if key in item:

                print(
                    f"  {key}: {item[key]}"
                )

    if len(items) > 20:

        print()
        print(
            f"... plus {len(items) - 20} "
            "more items."
        )


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print()
    print("=" * 80)
    print("PAYPAMS MAINE -> LEWISTON")
    print("=" * 80)

    print()
    print("State   :", STATE)
    print("District:", DISTRICT_NAME)
    print("Target  :", LEWISTON_EVENTTARGET)
    print("URL     :", URL)

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ========================================================================
    # STEP 1 - INITIAL GET
    # ========================================================================

    print()
    print("=" * 80)
    print("STEP 1 - INITIAL GET")
    print("=" * 80)

    try:

        response1 = session.get(
            URL,
            timeout=30,
            allow_redirects=True,
        )

    except requests.RequestException as exc:

        print(
            "Initial GET failed:"
        )
        print(exc)

        return 1

    response1.raise_for_status()

    print_response(
        "INITIAL RESPONSE",
        response1,
    )

    save_text(
        "01_initial.html",
        response1.text,
    )

    soup1 = BeautifulSoup(
        response1.text,
        "html.parser",
    )

    print_page_title(
        soup1
    )

    # ========================================================================
    # STEP 2 - SELECT MAINE
    # ========================================================================

    print()
    print("=" * 80)
    print("STEP 2 - POST MAINE")
    print("=" * 80)

    hidden1 = get_hidden_fields(
        soup1
    )

    print(
        "Hidden field count:",
        len(hidden1),
    )

    post_me = hidden1.copy()

    post_me[
        "h_UC_State:h_DD_State"
    ] = "ME"

    post_me[
        "h_BTN_Submit"
    ] = "Submit"

    post_me[
        "__EVENTTARGET"
    ] = ""

    post_me[
        "__EVENTARGUMENT"
    ] = ""

    print()
    print(
        "POSTing:"
    )

    print(
        "  h_UC_State:h_DD_State = ME"
    )

    print(
        "  h_BTN_Submit = Submit"
    )

    try:

        response2 = session.post(
            URL,
            data=post_me,
            timeout=30,
            allow_redirects=True,
        )

    except requests.RequestException as exc:

        print(
            "Maine POST failed:"
        )
        print(exc)

        return 1

    response2.raise_for_status()

    print_response(
        "MAINE RESPONSE",
        response2,
    )

    save_text(
        "02_after_ME_post.html",
        response2.text,
    )

    soup2 = BeautifulSoup(
        response2.text,
        "html.parser",
    )

    print_page_title(
        soup2
    )

    print_page_text(
        soup2
    )

    print_all_links(
        soup2
    )

    # ========================================================================
    # STEP 3 - VERIFY LEWISTON LINK
    # ========================================================================

    print()
    print("=" * 80)
    print("STEP 3 - VERIFY LEWISTON POSTBACK")
    print("=" * 80)

    lewiston_link = None

    for link in soup2.find_all("a"):

        text = link.get_text(
            " ",
            strip=True,
        )

        if (
            "lewiston public schools"
            in text.lower()
        ):

            lewiston_link = link
            break

    if lewiston_link is None:

        print(
            "ERROR: Lewiston Public Schools "
            "link was not found."
        )

        print(
            "Check 02_after_ME_post.html"
        )

        return 1

    href = lewiston_link.get(
        "href",
        "",
    )

    print(
        "Lewiston link found."
    )

    print(
        "Link HTML:"
    )

    print(
        lewiston_link
    )

    print()
    print(
        "href:"
    )

    print(
        href
    )

    # ========================================================================
    # STEP 4 - POST LEWISTON LINKBUTTON
    # ========================================================================

    print()
    print("=" * 80)
    print("STEP 4 - CLICK LEWISTON PUBLIC SCHOOLS")
    print("=" * 80)

    # IMPORTANT:
    #
    # The browser's JavaScript does this:
    #
    #   __EVENTTARGET = "_ctl7"
    #   __EVENTARGUMENT = ""
    #
    # and then submits the form.
    #
    hidden2 = get_hidden_fields(
        soup2
    )

    print(
        "Hidden field count:",
        len(hidden2),
    )

    post_lewiston = hidden2.copy()

    # This is the equivalent of clicking the Lewiston link.
    post_lewiston[
        "__EVENTTARGET"
    ] = LEWISTON_EVENTTARGET

    post_lewiston[
        "__EVENTARGUMENT"
    ] = ""

    # The clicked LinkButton does NOT submit its own
    # name/value pair like h_BTN_Submit did.
    #
    # Leave other fields from the page intact.

    print()
    print(
        "__EVENTTARGET =",
        post_lewiston["__EVENTTARGET"],
    )

    print(
        "__EVENTARGUMENT =",
        repr(post_lewiston["__EVENTARGUMENT"]),
    )

    try:

        response3 = session.post(
            URL,
            data=post_lewiston,
            timeout=30,
            allow_redirects=True,
        )

    except requests.RequestException as exc:

        print(
            "Lewiston POST failed:"
        )
        print(exc)

        return 1

    response3.raise_for_status()

    print_response(
        "LEWISTON RESPONSE",
        response3,
    )

    save_text(
        "03_after_Lewiston_post.html",
        response3.text,
    )

    soup3 = BeautifulSoup(
        response3.text,
        "html.parser",
    )

    # ========================================================================
    # STEP 5 - INSPECT LEWISTON PAGE
    # ========================================================================

    print_page_title(
        soup3
    )

    print_page_text(
        soup3,
        limit=250,
    )

    print_forms(
        soup3
    )

    print_all_links(
        soup3
    )

    # ========================================================================
    # STEP 6 - SEARCH FOR MENU DATA
    # ========================================================================

    menu_items = extract_menu_json(
        soup3
    )

    if menu_items is not None:

        summarize_menu_items(
            menu_items
        )

    search_html_for_menu_signatures(
        response3.text
    )

    extract_possible_json_blocks(
        response3.text
    )

    # ========================================================================
    # STEP 7 - SAVE A REPORT
    # ========================================================================

    report = {
        "state": STATE,
        "district": DISTRICT_NAME,
        "eventtarget": LEWISTON_EVENTTARGET,
        "initial_status": response1.status_code,
        "maine_status": response2.status_code,
        "lewistion_status": response3.status_code,
        "final_url": response3.url,
        "response_length": len(response3.text),
        "menu_item_count": (
            len(menu_items)
            if menu_items is not None
            else None
        ),
    }

    report_path = OUT_DIR / "report.json"

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # ========================================================================
    # DONE
    # ========================================================================

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)

    print()
    print(
        "The critical file is:"
    )

    print(
        OUT_DIR
        / "03_after_Lewiston_post.html"
    )

    print()
    print(
        "That is the page returned by PayPAMS "
        "after simulating the click on "
        "Lewiston Public Schools."
    )

    print()
    print(
        "Debug directory:"
    )

    print(
        OUT_DIR.resolve()
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
