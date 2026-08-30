#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIG
# ============================================================================

URL = "https://paypams.com/TN_Menus.aspx"

STATE = "ME"

DISTRICT_NAME = "Lewiston Public Schools"
DISTRICT_EVENTTARGET = "_ctl7"

SCHOOL_NAME = "Geiger Elementary School"
SCHOOL_VALUE = "112"

MEAL_NAME = "Lunch"
MEAL_VALUE = "47"
MEAL_EVENTTARGET = "h_DD_MealTypes"

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
# HELPERS
# ============================================================================

def save_text(filename: str, text: str) -> Path:
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")
    return path


def soup_for(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def get_form(soup: BeautifulSoup):
    form = soup.find("form")

    if form is None:
        raise RuntimeError("Could not find PayPAMS form.")

    return form


def get_hidden_fields(
    soup: BeautifulSoup,
) -> Dict[str, str]:

    form = get_form(soup)

    data: Dict[str, str] = {}

    for inp in form.find_all("input", type="hidden"):

        name = inp.get("name")

        if name:
            data[name] = inp.get("value", "")

    return data


def print_response(
    name: str,
    response: requests.Response,
) -> None:

    print()
    print("=" * 80)
    print(name)
    print("=" * 80)

    print("Status :", response.status_code)
    print("URL    :", response.url)
    print("Length :", len(response.content))


def get_select(
    soup: BeautifulSoup,
    select_id: str,
):
    return soup.find(
        "select",
        id=select_id,
    )


def print_select(
    soup: BeautifulSoup,
    select_id: str,
) -> None:

    print()
    print("=" * 80)
    print(f"SELECT {select_id}")
    print("=" * 80)

    select = get_select(
        soup,
        select_id,
    )

    if select is None:

        print(
            "NOT FOUND"
        )

        return

    print(
        "name:",
        select.get("name"),
    )

    print(
        "onchange:",
        select.get("onchange"),
    )

    print()

    for index, option in enumerate(
        select.find_all("option"),
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
            " [SELECTED]"
            if option.has_attr("selected")
            else ""
        )

        print(
            f"{index:02d}. "
            f"value={value!r} "
            f"text={text!r}"
            f"{selected}"
        )


def print_menu_text(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("MENU PAGE TEXT")
    print("=" * 80)

    text = soup.get_text(
        "\n",
        strip=True,
    )

    for line in text.splitlines():

        line = re.sub(
            r"\s+",
            " ",
            line.strip(),
        )

        if not line:
            continue

        print(line)


# ============================================================================
# POSTBACK PARSING
# ============================================================================

def extract_postback_target(
    javascript: Optional[str],
) -> Optional[str]:

    if not javascript:
        return None

    # Handles:
    #
    # __doPostBack('h_DD_MealTypes','')
    #
    # and:
    #
    # __doPostBack(\'h_DD_MealTypes\',\'\')
    #

    patterns = [
        r"__doPostBack\s*\(\s*['\\\"]+([^'\\\"]+)",
        r"__doPostBack\s*\(\s*\\\\?['\\\"]([^'\\\"]+)",
        r"PostBackOptions\s*\(\s*['\\\"]+([^'\\\"]+)",
        r"PostBackOptions\s*\(\s*\\\\?['\\\"]([^'\\\"]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            javascript,
            flags=re.I,
        )

        if match:
            return match.group(1)

    return None


# ============================================================================
# MENU JSON / DATA DISCOVERY
# ============================================================================

def try_parse_json(
    raw: str,
) -> Optional[object]:

    raw = raw.strip()

    if not raw:
        return None

    # Straight JSON.
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Try extracting an array.
    array_match = re.search(
        r"(\[\s*\{.*?\}\s*\])",
        raw,
        flags=re.S,
    )

    if array_match:

        try:
            return json.loads(
                array_match.group(1)
            )
        except Exception:
            pass

    return None


def inspect_menu_scripts(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("MENU-RELATED SCRIPTS")
    print("=" * 80)

    found = 0

    terms = [
        "h_SCRIPT_menudata",
        "DistrictID",
        "ItemCode",
        "ServingTypeID",
        "DataCalDay",
        "ItemName",
        "CaloriesStr",
        "Geiger",
        "Lunch",
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

        lower = text.lower()

        matching_terms = [
            term
            for term in terms
            if term.lower() in lower
        ]

        if not matching_terms:
            continue

        found += 1

        filename = (
            f"menu_script_{found}.txt"
        )

        save_text(
            filename,
            text,
        )

        print()
        print(
            f"SCRIPT #{index}"
        )

        print(
            "Matching terms:",
            ", ".join(matching_terms),
        )

        print(
            "Saved:",
            filename,
        )

        # Try parsing script contents as JSON.
        parsed = try_parse_json(
            text
        )

        if parsed is not None:

            json_name = (
                f"menu_script_{found}.json"
            )

            path = (
                OUT_DIR / json_name
            )

            path.write_text(
                json.dumps(
                    parsed,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            print(
                "Parsed JSON saved:",
                path,
            )


def inspect_embedded_menu_elements(
    soup: BeautifulSoup,
) -> None:

    print()
    print("=" * 80)
    print("MENU-RELATED HTML ELEMENTS")
    print("=" * 80)

    # Search elements whose IDs/classes contain menu-related strings.
    for tag in soup.find_all(
        True
    ):

        tag_id = str(
            tag.get("id", "")
        )

        tag_class = " ".join(
            tag.get(
                "class",
                [],
            )
        )

        identifier = (
            tag_id
            + " "
            + tag_class
        ).lower()

        if not any(
            x in identifier
            for x in [
                "menu",
                "calendar",
                "item",
                "nutrition",
            ]
        ):
            continue

        text = tag.get_text(
            " ",
            strip=True,
        )

        if text:

            print()
            print(
                tag.name,
                "id=",
                tag.get("id"),
                "class=",
                tag.get("class"),
            )

            print(
                "TEXT:",
                text[:500],
            )


# ============================================================================
# STEP 1
# ============================================================================

def step_initial_get(
    session: requests.Session,
):

    print()
    print("=" * 80)
    print("STEP 1 - INITIAL GET")
    print("=" * 80)

    response = session.get(
        URL,
        timeout=30,
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

    return soup_for(
        response.text
    )


# ============================================================================
# STEP 2
# ============================================================================

def step_select_state(
    session: requests.Session,
    soup: BeautifulSoup,
):

    print()
    print("=" * 80)
    print("STEP 2 - SELECT MAINE")
    print("=" * 80)

    data = get_hidden_fields(
        soup
    )

    data[
        "h_UC_State:h_DD_State"
    ] = STATE

    data[
        "h_BTN_Submit"
    ] = "Submit"

    data[
        "__EVENTTARGET"
    ] = ""

    data[
        "__EVENTARGUMENT"
    ] = ""

    response = session.post(
        URL,
        data=data,
        timeout=30,
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

    return soup_for(
        response.text
    )


# ============================================================================
# STEP 3
# ============================================================================

def step_select_district(
    session: requests.Session,
    soup: BeautifulSoup,
):

    print()
    print("=" * 80)
    print(
        "STEP 3 - SELECT LEWISTON PUBLIC SCHOOLS"
    )
    print("=" * 80)

    district_link = None

    for link in soup.find_all("a"):

        text = link.get_text(
            " ",
            strip=True,
        )

        if (
            DISTRICT_NAME.lower()
            in text.lower()
        ):

            district_link = link
            break

    if district_link is None:

        raise RuntimeError(
            "Lewiston Public Schools link "
            "was not found."
        )

    print(
        "District link:"
    )

    print(
        district_link
    )

    data = get_hidden_fields(
        soup
    )

    data[
        "__EVENTTARGET"
    ] = DISTRICT_EVENTTARGET

    data[
        "__EVENTARGUMENT"
    ] = ""

    response = session.post(
        URL,
        data=data,
        timeout=30,
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

    return soup_for(
        response.text
    )


# ============================================================================
# STEP 4
# ============================================================================

def step_select_geiger(
    session: requests.Session,
    soup: BeautifulSoup,
):

    print()
    print("=" * 80)
    print(
        "STEP 4 - SELECT GEIGER ELEMENTARY SCHOOL"
    )
    print("=" * 80)

    print_select(
        soup,
        "h_DD_Schools",
    )

    school_select = get_select(
        soup,
        "h_DD_Schools",
    )

    if school_select is None:

        raise RuntimeError(
            "h_DD_Schools not found."
        )

    # Verify the school exists.
    found = False

    for option in school_select.find_all(
        "option"
    ):

        value = option.get(
            "value",
            "",
        )

        text = option.get_text(
            " ",
            strip=True,
        )

        if (
            value == SCHOOL_VALUE
            and text.lower()
            == SCHOOL_NAME.lower()
        ):

            found = True
            break

    if not found:

        raise RuntimeError(
            "Geiger was not found with "
            f"value={SCHOOL_VALUE!r}."
        )

    print()
    print(
        "Using school:"
    )

    print(
        f"  {SCHOOL_NAME}"
    )

    print(
        f"  value = {SCHOOL_VALUE}"
    )

    # IMPORTANT:
    #
    # There is NO onchange on h_DD_Schools.
    # Therefore clicking/selecting it does NOT create
    # a separate server round-trip.
    #
    # We need to carry this selected value into the
    # subsequent meal postback.

    print()
    print(
        "No school postback exists."
    )

    print(
        "School will be submitted with the "
        "Lunch postback."
    )

    return soup


# ============================================================================
# STEP 5
# ============================================================================

def step_select_lunch(
    session: requests.Session,
    soup: BeautifulSoup,
):

    print()
    print("=" * 80)
    print(
        "STEP 5 - SELECT LUNCH FOR GEIGER"
    )
    print("=" * 80)

    print_select(
        soup,
        "h_DD_MealTypes",
    )

    meal_select = get_select(
        soup,
        "h_DD_MealTypes",
    )

    if meal_select is None:

        raise RuntimeError(
            "h_DD_MealTypes not found."
        )

    # Verify Lunch exists.
    lunch_found = False

    for option in meal_select.find_all(
        "option"
    ):

        value = option.get(
            "value",
            "",
        )

        text = option.get_text(
            " ",
            strip=True,
        )

        if (
            value == MEAL_VALUE
            and text.lower()
            == MEAL_NAME.lower()
        ):

            lunch_found = True
            break

    if not lunch_found:

        raise RuntimeError(
            "Lunch was not found with "
            f"value={MEAL_VALUE!r}."
        )

    print()
    print(
        "Using meal:"
    )

    print(
        f"  {MEAL_NAME}"
    )

    print(
        f"  value = {MEAL_VALUE}"
    )

    # ------------------------------------------------------------------------
    # This is the key correction.
    #
    # DO NOT inspect the selected <option> here because PayPAMS returns
    # "Select School" as selected by default in the HTML.
    #
    # We know the user wants Geiger and have already validated its value:
    #
    #     Geiger Elementary School = 112
    #
    # So explicitly send 112.
    # ------------------------------------------------------------------------

    data = get_hidden_fields(
        soup
    )

    data[
        "h_DD_Schools"
    ] = SCHOOL_VALUE

    data[
        "h_DD_MealTypes"
    ] = MEAL_VALUE

    data[
        "__EVENTTARGET"
    ] = MEAL_EVENTTARGET

    data[
        "__EVENTARGUMENT"
    ] = ""

    print()
    print(
        "Submitting:"
    )

    print(
        f"  h_DD_Schools   = {SCHOOL_VALUE}"
    )

    print(
        f"  h_DD_MealTypes = {MEAL_VALUE}"
    )

    print(
        f"  __EVENTTARGET  = {MEAL_EVENTTARGET}"
    )

    response = session.post(
        URL,
        data=data,
        timeout=30,
    )

    response.raise_for_status()

    print_response(
        "GEIGER + LUNCH RESPONSE",
        response,
    )

    save_text(
        "05_after_Geiger_Lunch_post.html",
        response.text,
    )

    return response, soup_for(
        response.text
    )


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print()
    print("=" * 80)
    print("PAYPAMS")
    print("MAINE -> LEWISTON -> GEIGER -> LUNCH")
    print("=" * 80)

    print()
    print("State   :", STATE)
    print("District:", DISTRICT_NAME)
    print("School  :", SCHOOL_NAME)
    print("School #:", SCHOOL_VALUE)
    print("Meal    :", MEAL_NAME)
    print("Meal #  :", MEAL_VALUE)

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:

        # 1. Initial page.
        soup1 = step_initial_get(
            session
        )

        # 2. Maine.
        soup2 = step_select_state(
            session,
            soup1,
        )

        # 3. Lewiston.
        soup3 = step_select_district(
            session,
            soup2,
        )

        # 4. Geiger.
        step_select_geiger(
            session,
            soup3,
        )

        # 5. Lunch.
        response5, soup5 = step_select_lunch(
            session,
            soup3,
        )

        # ------------------------------------------------------------------
        # Inspect final result.
        # ------------------------------------------------------------------

        print()
        print("=" * 80)
        print("FINAL PAGE")
        print("=" * 80)

        print_menu_text(
            soup5
        )

        inspect_menu_scripts(
            soup5
        )

        inspect_embedded_menu_elements(
            soup5
        )

        # ------------------------------------------------------------------
        # Summary report.
        # ------------------------------------------------------------------

        report = {
            "state": STATE,
            "district": DISTRICT_NAME,
            "district_eventtarget": DISTRICT_EVENTTARGET,
            "school": SCHOOL_NAME,
            "school_value": SCHOOL_VALUE,
            "meal": MEAL_NAME,
            "meal_value": MEAL_VALUE,
            "meal_eventtarget": MEAL_EVENTTARGET,
            "final_status": response5.status_code,
            "final_url": response5.url,
            "final_response_bytes": len(
                response5.content
            ),
        }

        report_path = (
            OUT_DIR / "final_report.json"
        )

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
        print("SUCCESS")
        print("=" * 80)

        print()
        print(
            "Requested path:"
        )

        print(
            "  Maine"
        )

        print(
            "  -> Lewiston Public Schools"
        )

        print(
            "  -> Geiger Elementary School"
        )

        print(
            "  -> Lunch"
        )

        print()
        print(
            "Final HTML:"
        )

        print(
            OUT_DIR
            / "05_after_Geiger_Lunch_post.html"
        )

        print()
        print(
            "Debug directory:"
        )

        print(
            OUT_DIR.resolve()
        )

        return 0

    except requests.RequestException as exc:

        print()
        print(
            "HTTP ERROR:"
        )

        print(exc)

        return 1

    except Exception as exc:

        print()
        print(
            "ERROR:"
        )

        print(
            type(exc).__name__,
            str(exc),
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
