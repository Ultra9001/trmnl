#!/usr/bin/env python3

"""
PayPAMS
Maine -> Lewiston Public Schools -> Geiger Elementary School -> Lunch

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
from typing import Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIGURATION
# ============================================================================

URL = "https://paypams.com/TN_Menus.aspx"

STATE_CODE = "ME"
DISTRICT_NAME = "Lewiston Public Schools"
SCHOOL_NAME = "Geiger Elementary School"
MEAL_NAME = "Lunch"

# This was discovered from the actual Lewiston district link.
DISTRICT_EVENTTARGET = "_ctl7"

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
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ============================================================================
# GENERAL HELPERS
# ============================================================================

def save_text(filename: str, text: str) -> Path:
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")
    return path


def get_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def get_form(soup: BeautifulSoup):
    form = soup.find("form")

    if form is None:
        raise RuntimeError("Could not find PayPAMS form.")

    return form


def get_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Collect all hidden inputs from the PayPAMS ASP.NET form.
    """

    form = get_form(soup)

    data: Dict[str, str] = {}

    for inp in form.find_all("input", type="hidden"):

        name = inp.get("name")

        if name:
            data[name] = inp.get("value", "")

    return data


def print_response(
    label: str,
    response: requests.Response,
) -> None:

    print()
    print("=" * 80)
    print(label)
    print("=" * 80)

    print("Status :", response.status_code)
    print("URL    :", response.url)
    print("Length :", len(response.content))
    print()


# ============================================================================
# SELECT HELPERS
# ============================================================================

def get_select(
    soup: BeautifulSoup,
    select_id: str,
):
    select = soup.find(
        "select",
        id=select_id,
    )

    if select is None:

        # Try by name as fallback.
        select = soup.find(
            "select",
            attrs={"name": select_id},
        )

    return select


def print_select(
    soup: BeautifulSoup,
    select_id: str,
) -> None:

    print()
    print("=" * 80)
    print(f"SELECT: {select_id}")
    print("=" * 80)

    select = get_select(
        soup,
        select_id,
    )

    if select is None:

        print(
            f"ERROR: <select id={select_id!r}> "
            "was not found."
        )

        return

    print(
        "id      :",
        select.get("id"),
    )

    print(
        "name    :",
        select.get("name"),
    )

    print(
        "onchange:",
        select.get("onchange"),
    )

    options = select.find_all("option")

    print(
        "options :",
        len(options),
    )

    for i, option in enumerate(
        options,
        1,
    ):

        value = option.get(
            "value",
            "",
        )

        text = option.get_text(
            " ",
            strip=True,
        )

        selected = (
            " SELECTED"
            if option.has_attr("selected")
            else ""
        )

        print(
            f"  [{i:02d}] "
            f"value={value!r} "
            f"text={text!r}"
            f"{selected}"
        )


def find_option_by_text(
    soup: BeautifulSoup,
    select_id: str,
    wanted_text: str,
) -> Optional[Tuple[str, str]]:

    select = get_select(
        soup,
        select_id,
    )

    if select is None:
        return None

    wanted_normalized = re.sub(
        r"\s+",
        " ",
        wanted_text.strip().lower(),
    )

    options = select.find_all("option")

    # Exact normalized match first.
    for option in options:

        value = option.get(
            "value",
            "",
        )

        text = re.sub(
            r"\s+",
            " ",
            option.get_text(
                " ",
                strip=True,
            ).lower(),
        )

        if text == wanted_normalized:
            return value, option.get_text(
                " ",
                strip=True,
            )

    # Then substring match.
    for option in options:

        value = option.get(
            "value",
            "",
        )

        text_original = option.get_text(
            " ",
            strip=True,
        )

        text = re.sub(
            r"\s+",
            " ",
            text_original.lower(),
        )

        if wanted_normalized in text:
            return value, text_original

    return None


# ============================================================================
# POSTBACK HELPERS
# ============================================================================

def extract_postback_target(
    onchange: Optional[str],
) -> Optional[str]:

    if not onchange:
        return None

    # Common ASP.NET pattern:
    #
    # __doPostBack('h_DD_Schools','')
    #
    # or:
    #
    # __doPostBack("h_DD_Schools","")
    #
    match = re.search(
        r"__doPostBack\s*\(\s*['\"]([^'\"]+)['\"]",
        onchange,
        flags=re.I,
    )

    if match:
        return match.group(1)

    # Sometimes WebForm_DoPostBackWithOptions is used.
    match = re.search(
        r'PostBackOptions\s*\(\s*["\']([^"\']+)["\']',
        onchange,
        flags=re.I,
    )

    if match:
        return match.group(1)

    return None


def print_control_details(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("SCHOOL / MEAL CONTROL DETAILS")
    print("=" * 80)

    for select_id in [
        "h_DD_Schools",
        "h_DD_MealTypes",
    ]:

        select = get_select(
            soup,
            select_id,
        )

        if select is None:
            continue

        print()
        print(select_id)

        print(
            "  name     :",
            select.get("name"),
        )

        print(
            "  onchange :",
            select.get("onchange"),
        )

        print(
            "  postback :",
            extract_postback_target(
                select.get("onchange")
            ),
        )


# ============================================================================
# STEP 1
# ============================================================================

def initial_get(
    session: requests.Session,
) -> Tuple[requests.Response, BeautifulSoup]:

    print()
    print("=" * 80)
    print("STEP 1 - INITIAL GET")
    print("=" * 80)

    response = session.get(
        URL,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    print_response(
        "INITIAL RESPONSE",
        response,
    )

    save_text(
        "01_initial.html",
        response.text,
    )

    return response, get_soup(
        response.text
    )


# ============================================================================
# STEP 2
# ============================================================================

def select_maine(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Tuple[requests.Response, BeautifulSoup]:

    print()
    print("=" * 80)
    print("STEP 2 - SELECT MAINE")
    print("=" * 80)

    data = get_hidden_fields(
        soup
    )

    data[
        "h_UC_State:h_DD_State"
    ] = STATE_CODE

    data[
        "h_BTN_Submit"
    ] = "Submit"

    data[
        "__EVENTTARGET"
    ] = ""

    data[
        "__EVENTARGUMENT"
    ] = ""

    print(
        "State:",
        STATE_CODE,
    )

    response = session.post(
        URL,
        data=data,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    print_response(
        "MAINE RESPONSE",
        response,
    )

    save_text(
        "02_after_ME_post.html",
        response.text,
    )

    return response, get_soup(
        response.text
    )


# ============================================================================
# STEP 3
# ============================================================================

def select_lewiston(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Tuple[requests.Response, BeautifulSoup]:

    print()
    print("=" * 80)
    print("STEP 3 - SELECT LEWISTON PUBLIC SCHOOLS")
    print("=" * 80)

    # Find the actual Lewiston link.
    link = None

    for candidate in soup.find_all("a"):

        text = candidate.get_text(
            " ",
            strip=True,
        )

        if (
            DISTRICT_NAME.lower()
            in text.lower()
        ):

            link = candidate
            break

    if link is None:

        raise RuntimeError(
            "Could not find Lewiston Public Schools link."
        )

    href = link.get(
        "href",
        "",
    )

    print(
        "Found district link:"
    )

    print(
        link
    )

    print(
        "href:",
        href,
    )

    # Reproduce:
    #
    # WebForm_DoPostBackWithOptions(
    #     new WebForm_PostBackOptions(
    #         "_ctl7", ...
    #     )
    #
    data = get_hidden_fields(
        soup
    )

    data[
        "__EVENTTARGET"
    ] = DISTRICT_EVENTTARGET

    data[
        "__EVENTARGUMENT"
    ] = ""

    print()
    print(
        "__EVENTTARGET =",
        DISTRICT_EVENTTARGET,
    )

    response = session.post(
        URL,
        data=data,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    print_response(
        "LEWISTON RESPONSE",
        response,
    )

    save_text(
        "03_after_Lewiston_post.html",
        response.text,
    )

    soup3 = get_soup(
        response.text
    )

    print_control_details(
        soup3
    )

    print_select(
        soup3,
        "h_DD_Schools",
    )

    print_select(
        soup3,
        "h_DD_MealTypes",
    )

    return response, soup3


# ============================================================================
# STEP 4
# ============================================================================

def select_geiger(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Tuple[requests.Response, BeautifulSoup]:

    print()
    print("=" * 80)
    print("STEP 4 - SELECT GEIGER ELEMENTARY SCHOOL")
    print("=" * 80)

    select = get_select(
        soup,
        "h_DD_Schools",
    )

    if select is None:

        raise RuntimeError(
            "h_DD_Schools was not found."
        )

    school_result = find_option_by_text(
        soup,
        "h_DD_Schools",
        SCHOOL_NAME,
    )

    if school_result is None:

        print_select(
            soup,
            "h_DD_Schools",
        )

        raise RuntimeError(
            f"Could not find school "
            f"{SCHOOL_NAME!r}."
        )

    school_value, school_text = school_result

    print(
        "School text :",
        school_text,
    )

    print(
        "School value:",
        school_value,
    )

    school_name = select.get(
        "name",
    )

    if not school_name:

        raise RuntimeError(
            "h_DD_Schools has no name attribute."
        )

    onchange = select.get(
        "onchange",
    )

    school_postback_target = (
        extract_postback_target(
            onchange
        )
    )

    print(
        "School field:",
        school_name,
    )

    print(
        "School onchange:",
        onchange,
    )

    print(
        "Detected school postback target:",
        school_postback_target,
    )

    # Start with all hidden fields from the Lewiston page.
    data = get_hidden_fields(
        soup
    )

    # ASP.NET select field.
    data[
        school_name
    ] = school_value

    data[
        "__EVENTARGUMENT"
    ] = ""

    # If the dropdown has an onchange __doPostBack,
    # use exactly that target.
    if school_postback_target:

        data[
            "__EVENTTARGET"
        ] = school_postback_target

        print()
        print(
            "Submitting school selection "
            "as ASP.NET postback:"
        )

        print(
            "  EVENTTARGET =",
            school_postback_target,
        )

    else:

        # Some ASP.NET pages process the selected value
        # without an explicit onchange target.
        data[
            "__EVENTTARGET"
        ] = ""

        print()
        print(
            "No school onchange postback was detected."
        )

    response = session.post(
        URL,
        data=data,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    print_response(
        "GEIGER RESPONSE",
        response,
    )

    save_text(
        "04_after_Geiger_post.html",
        response.text,
    )

    soup4 = get_soup(
        response.text
    )

    print_control_details(
        soup4
    )

    print_select(
        soup4,
        "h_DD_Schools",
    )

    print_select(
        soup4,
        "h_DD_MealTypes",
    )

    return response, soup4


# ============================================================================
# STEP 5
# ============================================================================

def select_lunch(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Tuple[requests.Response, BeautifulSoup]:

    print()
    print("=" * 80)
    print("STEP 5 - SELECT LUNCH")
    print("=" * 80)

    meal_select = get_select(
        soup,
        "h_DD_MealTypes",
    )

    if meal_select is None:

        raise RuntimeError(
            "h_DD_MealTypes was not found."
        )

    meal_result = find_option_by_text(
        soup,
        "h_DD_MealTypes",
        MEAL_NAME,
    )

    if meal_result is None:

        print_select(
            soup,
            "h_DD_MealTypes",
        )

        raise RuntimeError(
            f"Could not find meal "
            f"{MEAL_NAME!r}."
        )

    meal_value, meal_text = meal_result

    print(
        "Meal text :",
        meal_text,
    )

    print(
        "Meal value:",
        meal_value,
    )

    meal_name = meal_select.get(
        "name",
    )

    if not meal_name:

        raise RuntimeError(
            "h_DD_MealTypes has no name attribute."
        )

    onchange = meal_select.get(
        "onchange",
    )

    meal_postback_target = (
        extract_postback_target(
            onchange
        )
    )

    print(
        "Meal field:",
        meal_name,
    )

    print(
        "Meal onchange:",
        onchange,
    )

    print(
        "Detected meal postback target:",
        meal_postback_target,
    )

    data = get_hidden_fields(
        soup
    )

    # Preserve current school selection too.
    school_select = get_select(
        soup,
        "h_DD_Schools",
    )

    if school_select is not None:

        current_school = school_select.find(
            "option",
            selected=True,
        )

        # If there is no explicit selected attribute,
        # use the first non-placeholder option.
        if current_school is None:

            options = school_select.find_all(
                "option"
            )

            current_school = next(
                (
                    option
                    for option in options
                    if option.get("value")
                    and option.get_text(
                        " ",
                        strip=True,
                    ).lower()
                    != "select"
                ),
                None,
            )

        if current_school is not None:

            data[
                school_select.get(
                    "name"
                )
            ] = current_school.get(
                "value",
                "",
            )

            print(
                "Preserving school value:",
                current_school.get(
                    "value",
                    "",
                ),
            )

    # Add Lunch.
    data[
        meal_name
    ] = meal_value

    data[
        "__EVENTARGUMENT"
    ] = ""

    if meal_postback_target:

        data[
            "__EVENTTARGET"
        ] = meal_postback_target

        print()
        print(
            "Submitting meal selection "
            "as ASP.NET postback."
        )

        print(
            "  EVENTTARGET =",
            meal_postback_target,
        )

    else:

        data[
            "__EVENTTARGET"
        ] = ""

        print()
        print(
            "No meal onchange postback detected."
        )

    response = session.post(
        URL,
        data=data,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    print_response(
        "LUNCH RESPONSE",
        response,
    )

    save_text(
        "05_after_Lunch_post.html",
        response.text,
    )

    soup5 = get_soup(
        response.text
    )

    return response, soup5


# ============================================================================
# MENU DATA EXTRACTION
# ============================================================================

def search_for_menu_data(
    soup: BeautifulSoup,
    html: str,
) -> None:

    print()
    print("=" * 80)
    print("MENU DATA SEARCH")
    print("=" * 80)

    signatures = [
        "h_SCRIPT_menudata",
        "DistrictID",
        "ItemCode",
        "ServingTypeID",
        "DataCalDay",
        "CaloriesStr",
        "ItemName",
        "ServingSize",
        "MenuName",
        "Breakfast",
        "Lunch",
        "Geiger",
    ]

    for signature in signatures:

        count = html.lower().count(
            signature.lower()
        )

        print(
            f"{signature:20s}: {count}"
        )

    # ----------------------------------------------------------------------
    # Look for script tags with menu-related content.
    # ----------------------------------------------------------------------

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
                f"Menu-related script #{index}"
            )

            print(
                "Saved:",
                filename,
            )

    print()
    print(
        "Menu-related scripts:",
        found,
    )


def extract_menu_json(
    soup: BeautifulSoup,
) -> Optional[list]:

    print()
    print("=" * 80)
    print("DIRECT MENU JSON EXTRACTION")
    print("=" * 80)

    # First try the exact script ID seen in the site's JS.
    script = soup.find(
        "script",
        id="h_SCRIPT_menudata",
    )

    if script is None:

        print(
            "No h_SCRIPT_menudata script element."
        )

        return None

    raw = (
        script.string
        or script.get_text()
    ).strip()

    print(
        "Script found."
    )

    print(
        "Raw length:",
        len(raw),
    )

    save_text(
        "menu_data_raw.txt",
        raw,
    )

    # Sometimes the script contains JSON wrapped
    # in JavaScript rather than pure JSON.
    try:

        data = json.loads(raw)

    except json.JSONDecodeError:

        # Try extracting the first JSON array.
        match = re.search(
            r"(\[\s*\{.*\}\s*\])",
            raw,
            flags=re.S,
        )

        if not match:

            print(
                "No directly parseable JSON array found."
            )

            return None

        try:

            data = json.loads(
                match.group(1)
            )

        except json.JSONDecodeError as exc:

            print(
                "JSON extraction failed:",
                exc,
            )

            return None

    if not isinstance(
        data,
        list,
    ):

        print(
            "Menu data is not a list."
        )

        return None

    print(
        "Menu item count:",
        len(data),
    )

    output = OUT_DIR / "menu_data.json"

    output.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "Saved:",
        output,
    )

    return data


def print_visible_menu(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("VISIBLE MENU TEXT")
    print("=" * 80)

    text = soup.get_text(
        "\n",
        strip=True,
    )

    lines = [
        re.sub(
            r"\s+",
            " ",
            line.strip(),
        )
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines:

        lower = line.lower()

        if any(
            keyword in lower
            for keyword in [
                "geiger",
                "lunch",
                "menu",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
            ]
        ):

            print(line)


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print()
    print("=" * 80)
    print("PAYPAMS MENU SCRAPER")
    print("=" * 80)

    print()
    print("State   :", STATE_CODE)
    print("District:", DISTRICT_NAME)
    print("School  :", SCHOOL_NAME)
    print("Meal    :", MEAL_NAME)

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    # ----------------------------------------------------------------------
    # 1. INITIAL PAGE
    # ----------------------------------------------------------------------

    _, soup1 = initial_get(
        session
    )

    # ----------------------------------------------------------------------
    # 2. MAINE
    # ----------------------------------------------------------------------

    _, soup2 = select_maine(
        session,
        soup1,
    )

    # ----------------------------------------------------------------------
    # 3. LEWISTON
    # ----------------------------------------------------------------------

    _, soup3 = select_lewiston(
        session,
        soup2,
    )

    # ----------------------------------------------------------------------
    # 4. GEIGER
    # ----------------------------------------------------------------------

    _, soup4 = select_geiger(
        session,
        soup3,
    )

    # ----------------------------------------------------------------------
    # 5. LUNCH
    # ----------------------------------------------------------------------

    response5, soup5 = select_lunch(
        session,
        soup4,
    )

    # ----------------------------------------------------------------------
    # 6. EXTRACT / INSPECT MENU
    # ----------------------------------------------------------------------

    print_visible_menu(
        soup5
    )

    menu_items = extract_menu_json(
        soup5
    )

    search_for_menu_data(
        soup5,
        response5.text,
    )

    if menu_items is not None:

        print()
        print("=" * 80)
        print("MENU ITEM SAMPLE")
        print("=" * 80)

        for i, item in enumerate(
            menu_items[:20],
            1,
        ):

            print()
            print(
                f"ITEM #{i}"
            )

            if isinstance(
                item,
                dict,
            ):

                for key in [
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
                    "AttributesStr",
                    "HealthClaimsStr",
                ]:

                    if key in item:

                        print(
                            f"  {key}: {item[key]}"
                        )

    # ----------------------------------------------------------------------
    # REPORT
    # ----------------------------------------------------------------------

    report = {
        "state": STATE_CODE,
        "district": DISTRICT_NAME,
        "school": SCHOOL_NAME,
        "meal": MEAL_NAME,
        "district_eventtarget": DISTRICT_EVENTTARGET,
        "final_url": response5.url,
        "final_status": response5.status_code,
        "final_response_length": len(
            response5.content
        ),
        "menu_item_count": (
            len(menu_items)
            if menu_items is not None
            else None
        ),
    }

    report_path = OUT_DIR / "final_report.json"

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("COMPLETE")
    print("=" * 80)

    print()
    print(
        "Target:"
    )

    print(
        f"  {STATE_CODE} -> "
        f"{DISTRICT_NAME} -> "
        f"{SCHOOL_NAME} -> "
        f"{MEAL_NAME}"
    )

    print()
    print(
        "Final response:"
    )

    print(
        OUT_DIR
        / "05_after_Lunch_post.html"
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
