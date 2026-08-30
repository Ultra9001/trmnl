#!/usr/bin/env python3

"""
PayPAMS Maine school/menu diagnostic scraper.

This script:
1. Loads the PayPAMS school-menu page.
2. Collects the ASP.NET hidden form fields.
3. Selects Maine (ME).
4. Submits the state selection.
5. Saves the resulting HTML.
6. Prints all SELECT elements and their options.
7. Looks for school/district controls.
8. Looks for ASP.NET postback controls.
9. Looks for h_SCRIPT_menudata.
10. Saves useful diagnostic output.

Requirements:
    pip install requests beautifulsoup4

Run:
    python fetch_paypams_me.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

URL = "https://paypams.com/TN_Menus.aspx"

# Keep Maine debugging files separate.
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
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def save_text(filename: str, text: str) -> Path:
    """Save text to the debug directory."""
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")
    return path


def get_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Extract hidden fields from the first HTML form.

    PayPAMS is ASP.NET/WebForms-style, so preserving these fields is
    important when submitting the form.
    """
    data: Dict[str, str] = {}

    form = soup.find("form")

    if form is None:
        return data

    for inp in form.find_all("input", {"type": "hidden"}):
        name = inp.get("name")

        if name:
            data[name] = inp.get("value", "")

    return data


def print_response_info(
    label: str,
    response: requests.Response,
) -> None:
    print()
    print("=" * 80)
    print(label)
    print("=" * 80)

    print("Status       :", response.status_code)
    print("Final URL    :", response.url)
    print("Content-Type :", response.headers.get("content-type"))
    print("Length       :", len(response.text))
    print()


def dump_selects(
    soup: BeautifulSoup,
) -> List[Tuple[str, str, List[Tuple[str, str]]]]:
    """
    Return every SELECT and its options.

    Returns:
        [
            (
                select_id,
                select_name,
                [
                    (value, visible_text),
                    ...
                ]
            ),
            ...
        ]
    """
    results = []

    for select in soup.find_all("select"):

        select_id = select.get("id", "")
        select_name = select.get("name", "")

        options = []

        for option in select.find_all("option"):

            value = option.get("value", "")
            text = option.get_text(" ", strip=True)

            options.append((value, text))

        results.append(
            (
                select_id,
                select_name,
                options,
            )
        )

    return results


def print_selects(soup: BeautifulSoup) -> None:
    """Print every SELECT element and its options."""

    selects = dump_selects(soup)

    print()
    print("=" * 80)
    print("SELECT ELEMENTS")
    print("=" * 80)

    if not selects:
        print("No <select> elements found.")
        return

    for index, (select_id, select_name, options) in enumerate(
        selects,
        start=1,
    ):

        print()
        print(f"SELECT #{index}")
        print("  id           :", select_id)
        print("  name         :", select_name)
        print("  option count :", len(options))

        for value, text in options:
            print(
                f"    value={value!r} "
                f"text={text!r}"
            )


def find_school_controls(soup: BeautifulSoup) -> None:
    """
    Find controls whose IDs/names/text suggest school or district data.
    """

    print()
    print("=" * 80)
    print("POSSIBLE SCHOOL / DISTRICT CONTROLS")
    print("=" * 80)

    patterns = [
        re.compile(r"school", re.I),
        re.compile(r"district", re.I),
        re.compile(r"schools", re.I),
        re.compile(r"dd_", re.I),
    ]

    found = set()

    for tag in soup.find_all(
        ["select", "input", "button", "a"]
    ):

        tag_id = tag.get("id", "")
        tag_name = tag.get("name", "")
        tag_value = tag.get("value", "")
        text = tag.get_text(" ", strip=True)

        combined = " ".join(
            [
                str(tag_id),
                str(tag_name),
                str(tag_value),
                str(text),
            ]
        )

        if not any(
            pattern.search(combined)
            for pattern in patterns
        ):
            continue

        key = (
            tag.name,
            tag_id,
            tag_name,
            tag_value,
            text,
        )

        if key in found:
            continue

        found.add(key)

        print()
        print("TAG     :", tag.name)
        print("  id    :", tag_id)
        print("  name  :", tag_name)
        print("  value :", tag_value)
        print("  text  :", text[:300])

        onclick = tag.get("onclick")

        if onclick:
            print("  onclick:")
            print("   ", onclick)


def find_postback_controls(
    soup: BeautifulSoup,
) -> None:
    """
    Find controls that appear to use ASP.NET postbacks.
    """

    print()
    print("=" * 80)
    print("POSTBACK / FORM CONTROLS")
    print("=" * 80)

    for tag in soup.find_all(
        ["input", "button", "a", "select"]
    ):

        attrs_text = json.dumps(
            tag.attrs,
            ensure_ascii=False,
        )

        if not (
            "__doPostBack" in attrs_text
            or "PostBackOptions" in attrs_text
            or "submit" in attrs_text.lower()
        ):
            continue

        print()
        print("TAG")
        print("  type/name:", tag.name)
        print("  id       :", tag.get("id"))
        print("  name     :", tag.get("name"))
        print("  value    :", tag.get("value"))
        print(
            "  text     :",
            tag.get_text(" ", strip=True)[:200],
        )

        onclick = tag.get("onclick")

        if onclick:
            print("  onclick  :", onclick)


def save_relevant_scripts(
    soup: BeautifulSoup,
) -> None:
    """
    Save inline scripts containing terms useful for reverse-engineering
    the school/menu page.
    """

    scripts = []

    keywords = [
        "h_DD_Schools",
        "DD_Schools",
        "school",
        "district",
        "h_SCRIPT_menudata",
        "__doPostBack",
        "PostBackOptions",
    ]

    for index, script in enumerate(
        soup.find_all("script")
    ):

        text = script.get_text(
            "\n",
            strip=False,
        )

        if not text:
            continue

        if any(
            keyword.lower() in text.lower()
            for keyword in keywords
        ):

            scripts.append(
                "\n\n"
                + f"/* ================= SCRIPT {index} ================= */"
                + "\n\n"
                + text
            )

    if not scripts:
        print()
        print("No relevant inline scripts found.")
        return

    output = "".join(scripts)

    path = save_text(
        "relevant_scripts.txt",
        output,
    )

    print(
        f"Relevant inline scripts saved: {path}"
    )


def find_menu_data(
    soup: BeautifulSoup,
) -> Optional[List[dict]]:
    """
    Extract h_SCRIPT_menudata if it exists.
    """

    script = soup.find(
        "script",
        id="h_SCRIPT_menudata",
    )

    print()
    print("=" * 80)
    print("MENU DATA")
    print("=" * 80)

    if script is None:
        print(
            "h_SCRIPT_menudata was NOT found."
        )
        return None

    raw = script.string or script.get_text()

    raw = raw.strip()

    print(
        "Found h_SCRIPT_menudata."
    )

    print(
        "Raw JSON length:",
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
            "Could not parse menu JSON."
        )

        print(
            "JSON error:",
            exc,
        )

        return None

    if not isinstance(data, list):

        print(
            "Unexpected menu-data JSON type:",
            type(data).__name__,
        )

        return None

    print(
        "Menu items:",
        len(data),
    )

    pretty_path = OUT_DIR / "menu_data.json"

    pretty_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "Pretty JSON saved:",
        pretty_path,
    )

    return data


def summarize_menu_items(
    items: List[dict],
) -> None:
    """Print a useful summary of returned menu records."""

    if not items:
        return

    print()
    print("=" * 80)
    print("MENU ITEM SUMMARY")
    print("=" * 80)

    keys = [
        "DistrictID",
        "ItemCode",
        "ItemName",
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

    # Don't dump thousands of records.
    preview_count = min(
        len(items),
        20,
    )

    for index in range(preview_count):

        item = items[index]

        print()
        print(
            f"ITEM #{index + 1}"
        )

        for key in keys:

            if key in item:

                print(
                    f"  {key}: {item[key]}"
                )

    if len(items) > preview_count:

        print()
        print(
            f"... plus "
            f"{len(items) - preview_count} "
            f"additional items."
        )


def print_page_text(
    soup: BeautifulSoup,
    max_lines: int = 100,
) -> None:
    """Print the beginning of visible page text."""

    print()
    print("=" * 80)
    print("PAGE TEXT")
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

    for line in lines[:max_lines]:
        print(line)


def save_report(
    soup: BeautifulSoup,
    response: requests.Response,
    menu_items: Optional[List[dict]],
) -> None:
    """Write a compact machine-readable diagnostic report."""

    report = {
        "state": "ME",
        "state_name": "Maine",
        "url": URL,
        "status": response.status_code,
        "final_url": response.url,
        "menu_item_count": (
            len(menu_items)
            if menu_items is not None
            else None
        ),
        "selects": [],
    }

    for (
        select_id,
        select_name,
        options,
    ) in dump_selects(soup):

        report["selects"].append(
            {
                "id": select_id,
                "name": select_name,
                "option_count": len(options),
                "options": [
                    {
                        "value": value,
                        "text": text,
                    }
                    for value, text in options
                ],
            }
        )

    path = OUT_DIR / "report.json"

    path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "Diagnostic report saved:",
        path,
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> int:

    print()
    print("=" * 80)
    print("PAYPAMS MAINE MENU SCRAPER")
    print("=" * 80)
    print()
    print("State: Maine (ME)")
    print("URL  :", URL)
    print()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # =======================================================================
    # STEP 1 - INITIAL GET
    # =======================================================================

    print("=" * 80)
    print("STEP 1 - INITIAL GET")
    print("=" * 80)

    try:

        response = session.get(
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

    response.raise_for_status()

    print_response_info(
        "INITIAL RESPONSE",
        response,
    )

    save_text(
        "01_initial.html",
        response.text,
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    print_selects(soup)

    find_school_controls(soup)

    find_postback_controls(soup)

    save_relevant_scripts(soup)

    # =======================================================================
    # STEP 2 - COLLECT FORM FIELDS
    # =======================================================================

    print()
    print("=" * 80)
    print("STEP 2 - BUILD MAINE FORM POST")
    print("=" * 80)

    hidden = get_hidden_fields(
        soup
    )

    print()
    print("Hidden fields found:")

    for key, value in hidden.items():

        if len(value) > 300:

            display = (
                value[:100]
                + " ... "
                + f"[{len(value)} chars]"
            )

        else:

            display = value

        print(
            f"  {key} = {display!r}"
        )

    # This is the SELECT field from the PayPAMS page.
    state_field = (
        "h_UC_State:h_DD_State"
    )

    # Start with every hidden form value.
    post_data = hidden.copy()

    # -----------------------------------------------------------------------
    # MAINE
    # -----------------------------------------------------------------------

    post_data[state_field] = "ME"

    # Submit button.
    post_data["h_BTN_Submit"] = "Submit"

    # ASP.NET postback fields.
    post_data.setdefault(
        "__EVENTTARGET",
        "",
    )

    post_data.setdefault(
        "__EVENTARGUMENT",
        "",
    )

    print()
    print("State selection:")
    print(
        f"  {state_field} = "
        f"{post_data[state_field]!r}"
    )

    print()
    print("Submitting Maine...")

    # =======================================================================
    # STEP 3 - POST STATE=ME
    # =======================================================================

    try:

        response2 = session.post(
            URL,
            data=post_data,
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

    print_response_info(
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

    # =======================================================================
    # STEP 4 - INSPECT MAINE RESPONSE
    # =======================================================================

    print_page_text(
        soup2,
        max_lines=100,
    )

    print_selects(
        soup2
    )

    find_school_controls(
        soup2
    )

    find_postback_controls(
        soup2
    )

    save_relevant_scripts(
        soup2
    )

    # =======================================================================
    # STEP 5 - LOOK FOR MENU DATA
    # =======================================================================

    menu_items = find_menu_data(
        soup2
    )

    if menu_items is not None:

        summarize_menu_items(
            menu_items
        )

    # =======================================================================
    # STEP 6 - REPORT
    # =======================================================================

    save_report(
        soup=soup2,
        response=response2,
        menu_items=menu_items,
    )

    # =======================================================================
    # DONE
    # =======================================================================

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)

    print()
    print(
        "Debug directory:"
    )

    print(
        OUT_DIR.resolve()
    )

    print()
    print("Generated files:")

    for path in sorted(
        OUT_DIR.iterdir()
    ):

        if path.is_file():

            print(
                "  ",
                path.name,
            )

    print()
    print(
        "The most important file is:"
    )

    print(
        f"  {OUT_DIR / '02_after_ME_post.html'}"
    )

    print()
    print(
        "That is the actual PayPAMS response "
        "after selecting Maine."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
