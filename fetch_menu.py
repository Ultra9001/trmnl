```python
#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://paypams.com/TN_Menus.aspx"

STATE = "ME"

DISTRICT_NAME = "Lewiston Public Schools"

SCHOOL_NAME = "Geiger Elementary School"
SCHOOL_VALUE = "112"

MEAL_NAME = "Lunch"
MEAL_VALUE = "47"

# PayPAMS currently uses this postback for the district link discovered
# after selecting Maine.
DISTRICT_EVENTTARGET = "_ctl7"

# How many days we want available to TRMNL.
DAYS_TO_FETCH = 14

# Debug files are intentionally kept so that if PayPAMS changes again,
# we can inspect exactly what came back.
OUT_DIR = Path("paypams_me_debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# HTTP
# ============================================================================

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
    "Upgrade-Insecure-Requests": "1",
}


# ============================================================================
# MONTHS
# ============================================================================

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


# ============================================================================
# GENERAL HELPERS
# ============================================================================

def save_text(filename: str, text: str) -> Path:
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    print(f"Saved: {path}")
    return path


def save_json(filename: str, data) -> Path:
    path = OUT_DIR / filename
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved: {path}")
    return path


def soup_for(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def response_summary(label: str, response: requests.Response) -> None:
    print()
    print("=" * 80)
    print(label)
    print("=" * 80)
    print("Status :", response.status_code)
    print("URL    :", response.url)
    print("Bytes  :", len(response.content))


def die(message: str) -> None:
    print()
    print("=" * 80)
    print("FATAL")
    print("=" * 80)
    print(message)
    sys.exit(1)


# ============================================================================
# ASP.NET FORM HANDLING
# ============================================================================

def get_form(soup: BeautifulSoup):
    form = soup.find("form")

    if form is None:
        raise RuntimeError("PayPAMS form was not found.")

    return form


def get_hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Return all hidden fields from the current ASP.NET WebForms form.
    """

    form = get_form(soup)

    data: Dict[str, str] = {}

    for element in form.find_all("input"):
        name = element.get("name")

        if not name:
            continue

        input_type = (element.get("type") or "text").lower()

        if input_type in {
            "submit",
            "button",
            "image",
            "reset",
        }:
            continue

        if input_type in {"checkbox", "radio"}:
            if not element.has_attr("checked"):
                continue

        data[name] = element.get("value", "")

    return data


def get_form_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Harvest the current state of all useful ASP.NET form controls.

    This is intentionally more complete than simply harvesting hidden
    inputs because PayPAMS expects the current select values to survive
    WebForms postbacks.
    """

    form = get_form(soup)

    data: Dict[str, str] = {}

    for element in form.find_all(
        ["input", "select", "textarea"]
    ):

        name = element.get("name")

        if not name:
            continue

        # SELECT
        if element.name == "select":

            selected = element.find(
                "option",
                selected=True,
            )

            if selected is None:
                # WebForms often treats the first option as the current
                # value when no explicit selected attribute exists.
                selected = element.find("option")

            if selected is not None:
                data[name] = selected.get(
                    "value",
                    selected.get_text(strip=True),
                )
            else:
                data[name] = ""

            continue

        # TEXTAREA
        if element.name == "textarea":
            data[name] = element.text or ""
            continue

        # INPUT
        input_type = (
            element.get("type") or "text"
        ).lower()

        if input_type in {
            "submit",
            "button",
            "image",
            "reset",
        }:
            continue

        if input_type in {
            "checkbox",
            "radio",
        }:
            if element.has_attr("checked"):
                data[name] = element.get(
                    "value",
                    "on",
                )

            continue

        data[name] = element.get(
            "value",
            "",
        )

    return data


def postback_from_href(
    href: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:

    if not href:
        return None, None

    href = href.replace(
        "\\'",
        "'",
    ).replace(
        '\\"',
        '"',
    )

    # __doPostBack('target','argument')
    match = re.search(
        r"__doPostBack\s*\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
        href,
        flags=re.I,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    # WebForm_DoPostBackWithOptions(
    #   new WebForm_PostBackOptions("target","argument",...)
    # )
    match = re.search(
        r"WebForm_PostBackOptions\s*\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]",
        href,
        flags=re.I,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    # Sometimes the JavaScript is escaped.
    match = re.search(
        r"WebForm_PostBackOptions\s*\(\s*\\\\?['\"]([^'\"]*)['\"]\s*,\s*\\\\?['\"]([^'\"]*)['\"]",
        href,
        flags=re.I,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    return None, None


def post_form(
    session: requests.Session,
    soup: BeautifulSoup,
    overrides: Dict[str, str],
    label: str,
) -> Tuple[BeautifulSoup, requests.Response]:

    payload = get_form_fields(soup)

    payload.update(overrides)

    print()
    print("-" * 80)
    print(label)
    print("-" * 80)

    for key in (
        "__EVENTTARGET",
        "__EVENTARGUMENT",
        "h_UC_State:h_DD_State",
        "h_DD_Schools",
        "h_DD_MealTypes",
    ):
        if key in payload:
            print(
                f"{key} = {payload[key]!r}"
            )

    response = session.post(
        BASE_URL,
        data=payload,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    response_summary(
        f"{label} RESPONSE",
        response,
    )

    soup = soup_for(
        response.text
    )

    return soup, response


# ============================================================================
# SELECT HELPERS
# ============================================================================

def find_select(
    soup: BeautifulSoup,
    select_id: str,
):
    return soup.find(
        "select",
        id=select_id,
    )


def list_select_options(
    soup: BeautifulSoup,
    select_id: str,
) -> List[Tuple[str, str]]:

    select = find_select(
        soup,
        select_id,
    )

    if select is None:
        return []

    results = []

    for option in select.find_all("option"):

        text = clean_text(
            option.get_text(
                " ",
                strip=True,
            )
        )

        value = option.get(
            "value",
            "",
        )

        results.append(
            (text, value)
        )

    return results


def find_option_value(
    soup: BeautifulSoup,
    select_id: str,
    desired_text: str,
) -> Optional[str]:

    options = list_select_options(
        soup,
        select_id,
    )

    desired = desired_text.lower()

    for text, value in options:

        if text.lower() == desired:
            return value

    # Fallback to contains.
    for text, value in options:

        if desired in text.lower():
            return value

    return None


def print_select_options(
    soup: BeautifulSoup,
    select_id: str,
) -> None:

    print()
    print(
        f"OPTIONS: {select_id}"
    )
    print("-" * 80)

    options = list_select_options(
        soup,
        select_id,
    )

    if not options:
        print("NOT FOUND / EMPTY")
        return

    for index, (
        text,
        value,
    ) in enumerate(
        options,
        1,
    ):

        print(
            f"{index:02d}. "
            f"{text!r} -> {value!r}"
        )


# ============================================================================
# STEP 1: INITIAL GET
# ============================================================================

def initial_get(
    session: requests.Session,
) -> BeautifulSoup:

    print()
    print("=" * 80)
    print("STEP 1 - INITIAL PAYPAMS GET")
    print("=" * 80)

    response = session.get(
        BASE_URL,
        timeout=30,
    )

    response.raise_for_status()

    response_summary(
        "INITIAL RESPONSE",
        response,
    )

    save_text(
        "01_initial.html",
        response.text,
    )

    soup = soup_for(
        response.text
    )

    print()
    print(
        "Initial selects:"
    )

    for select in soup.find_all(
        "select"
    ):

        print(
            " ",
            select.get("id"),
            "name=",
            select.get("name"),
            "options=",
            len(
                select.find_all(
                    "option"
                )
            ),
        )

    return soup


# ============================================================================
# STEP 2: SELECT MAINE
# ============================================================================

def select_state(
    session: requests.Session,
    soup: BeautifulSoup,
) -> BeautifulSoup:

    print()
    print("=" * 80)
    print("STEP 2 - SELECT MAINE")
    print("=" * 80)

    state_select = find_select(
        soup,
        "h_UC_State:h_DD_State",
    )

    if state_select is None:
        die(
            "Could not find the Maine state selector "
            "h_UC_State:h_DD_State."
        )

    state_options = list_select_options(
        soup,
        "h_UC_State:h_DD_State",
    )

    print(
        "State options:"
    )

    for text, value in state_options:
        print(
            f"  {text!r} -> {value!r}"
        )

    state_value = None

    for text, value in state_options:

        if value.upper() == STATE:
            state_value = value
            break

        if text.upper() == "MAINE":
            state_value = value
            break

    if state_value is None:
        die(
            f"Could not find Maine in the state selector. "
            f"Expected {STATE!r}."
        )

    print()
    print(
        f"Selecting Maine: {state_value!r}"
    )

    soup, response = post_form(
        session,
        soup,
        {
            "h_UC_State:h_DD_State": state_value,
            "h_BTN_Submit": "Submit",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        },
        "STEP 2 - MAINE POST",
    )

    save_text(
        "02_after_ME_post.html",
        response.text,
    )

    print()
    print(
        "District selection links found:"
    )

    district_found = False

    for link in soup.find_all("a"):

        text = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if DISTRICT_NAME.lower() in text.lower():

            district_found = True

            target, argument = postback_from_href(
                link.get("href")
            )

            print(
                f"  {text!r}"
            )

            print(
                f"  href={link.get('href')!r}"
            )

            print(
                f"  target={target!r}"
            )

            print(
                f"  argument={argument!r}"
            )

    if not district_found:
        die(
            "Maine was selected, but "
            f"{DISTRICT_NAME!r} was not found."
        )

    return soup


# ============================================================================
# STEP 3: SELECT LEWISTON
# ============================================================================

def select_district(
    session: requests.Session,
    soup: BeautifulSoup,
) -> BeautifulSoup:

    print()
    print("=" * 80)
    print(
        "STEP 3 - SELECT LEWISTON PUBLIC SCHOOLS"
    )
    print("=" * 80)

    district_link = None

    for link in soup.find_all("a"):

        text = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if DISTRICT_NAME.lower() in text.lower():

            district_link = link
            break

    if district_link is None:
        die(
            f"Could not find {DISTRICT_NAME!r} "
            "after selecting Maine."
        )

    href = district_link.get(
        "href",
        "",
    )

    target, argument = postback_from_href(
        href
    )

    # We know PayPAMS currently uses _ctl7 here,
    # but prefer the actual link if it can be parsed.
    if not target:
        target = DISTRICT_EVENTTARGET

    if argument is None:
        argument = ""

    print(
        "District link:",
        clean_text(
            district_link.get_text(
                " ",
                strip=True,
            )
        ),
    )

    print(
        "Postback target:",
        target,
    )

    print(
        "Postback argument:",
        argument,
    )

    soup, response = post_form(
        session,
        soup,
        {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": argument,
        },
        "STEP 3 - LEWISTON POST",
    )

    save_text(
        "03_after_Lewiston_post.html",
        response.text,
    )

    print_select_options(
        soup,
        "h_DD_Schools",
    )

    school_value = find_option_value(
        soup,
        "h_DD_Schools",
        SCHOOL_NAME,
    )

    if school_value is None:
        die(
            f"{SCHOOL_NAME!r} was not found in "
            "h_DD_Schools after selecting Lewiston."
        )

    print()
    print(
        f"FOUND GEIGER: value={school_value!r}"
    )

    if school_value != SCHOOL_VALUE:
        print(
            "WARNING: configured school value differs "
            "from live PayPAMS value."
        )

        print(
            f"Configured: {SCHOOL_VALUE!r}"
        )

        print(
            f"Live     : {school_value!r}"
        )

    return soup


# ============================================================================
# STEP 4: SELECT GEIGER + LUNCH
# ============================================================================

def select_school_and_meal(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Tuple[BeautifulSoup, str, str]:

    print()
    print("=" * 80)
    print(
        "STEP 4 - SELECT GEIGER ELEMENTARY + LUNCH"
    )
    print("=" * 80)

    school_value = find_option_value(
        soup,
        "h_DD_Schools",
        SCHOOL_NAME,
    )

    if school_value is None:
        die(
            "Geiger Elementary School is not present "
            "in h_DD_Schools."
        )

    meal_value = find_option_value(
        soup,
        "h_DD_MealTypes",
        MEAL_NAME,
    )

    if meal_value is None:
        print_select_options(
            soup,
            "h_DD_MealTypes",
        )

        die(
            "Lunch is not present in h_DD_MealTypes."
        )

    print()
    print(
        f"School: {SCHOOL_NAME}"
    )

    print(
        f"School value: {school_value}"
    )

    print()
    print(
        f"Meal: {MEAL_NAME}"
    )

    print(
        f"Meal value: {meal_value}"
    )

    # IMPORTANT:
    #
    # The school dropdown does not necessarily trigger its own postback.
    # We therefore submit both school and meal in the Lunch postback.
    #
    # This is the critical part of the Maine workflow.

    soup, response = post_form(
        session,
        soup,
        {
            "h_DD_Schools": school_value,
            "h_DD_MealTypes": meal_value,
            "__EVENTTARGET": "h_DD_MealTypes",
            "__EVENTARGUMENT": "",
        },
        "STEP 4 - GEIGER + LUNCH POST",
    )

    save_text(
        "04_after_Geiger_Lunch_post.html",
        response.text,
    )

    return (
        soup,
        school_value,
        meal_value,
    )


# ============================================================================
# DATE PARSING
# ============================================================================

def get_calendar_month_year(
    soup: BeautifulSoup,
) -> Tuple[int, int]:

    today = dt.date.today()

    year = today.year
    month = today.month

    # Primary PayPAMS month/year label.
    candidates = [
        soup.find(
            "span",
            id="h_LBL_MonthYear",
        ),
        soup.find(
            id="h_LBL_MonthYear",
        ),
    ]

    for element in candidates:

        if element is None:
            continue

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        match = re.search(
            r"\b(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\b\s+(\d{4})",
            text,
            flags=re.I,
        )

        if match:

            month = MONTHS[
                match.group(1).lower()
            ]

            year = int(
                match.group(2)
            )

            return (
                year,
                month,
            )

    # Fallback: inspect page text.
    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\b\s+(\d{4})",
        page_text,
        flags=re.I,
    )

    if match:

        month = MONTHS[
            match.group(1).lower()
        ]

        year = int(
            match.group(2)
        )

    return (
        year,
        month,
    )


# ============================================================================
# MENU ITEM EXTRACTION
# ============================================================================

def looks_like_day_number(
    text: str,
) -> bool:

    text = clean_text(text)

    return bool(
        re.fullmatch(
            r"\d{1,2}",
            text,
        )
    )


def extract_menu_names_from_cell(
    cell,
) -> List[str]:

    names: List[str] = []

    # ------------------------------------------------------------------------
    # FIRST: PayPAMS's known menu item classes.
    # ------------------------------------------------------------------------

    selectors = [
        "span.uncheckedNC",
        "span.checkedNC",
        ".uncheckedNC",
        ".checkedNC",
    ]

    for selector in selectors:

        for element in cell.select(
            selector
        ):

            text = clean_text(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            text = text.lstrip(
                "✓✔"
            ).strip()

            if text and text not in names:
                names.append(text)

    if names:
        return names

    # ------------------------------------------------------------------------
    # SECOND: inspect links inside the calendar cell.
    #
    # PayPAMS often turns menu items into clickable anchors.
    # ------------------------------------------------------------------------

    for link in cell.find_all("a"):

        text = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            continue

        if text.isdigit():
            continue

        lower = text.lower()

        # Ignore navigation / date / UI links.
        if lower in {
            "next",
            "previous",
            "next month",
            "previous month",
            "view",
            "details",
        }:
            continue

        # Ignore obvious nutrition controls.
        if "nutrition" in lower:
            continue

        if text not in names:
            names.append(text)

    if names:
        return names

    # ------------------------------------------------------------------------
    # THIRD: inspect spans/divs with item-like classes.
    # ------------------------------------------------------------------------

    for element in cell.find_all(
        ["span", "div", "p"]
    ):

        classes = " ".join(
            element.get(
                "class",
                [],
            )
        ).lower()

        element_id = str(
            element.get(
                "id",
                "",
            )
        ).lower()

        identifier = (
            classes
            + " "
            + element_id
        )

        if not any(
            token in identifier
            for token in (
                "menuitem",
                "menu_item",
                "itemname",
                "item_name",
                "menu-name",
                "menu_name",
            )
        ):
            continue

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        text = text.lstrip(
            "✓✔"
        ).strip()

        if (
            text
            and not text.isdigit()
            and text not in names
        ):
            names.append(text)

    return names


def find_calendar_table(
    soup: BeautifulSoup,
):

    # Preferred known PayPAMS calendar.
    table = soup.find(
        "table",
        class_="menucalendar",
    )

    if table is not None:
        return table

    # Handle multiple classes.
    for candidate in soup.find_all(
        "table"
    ):

        classes = " ".join(
            candidate.get(
                "class",
                [],
            )
        ).lower()

        if "menucalendar" in classes:
            return candidate

    # Last resort: identify a table containing label_menuday.
    for candidate in soup.find_all(
        "table"
    ):

        if candidate.find(
            class_="label_menuday"
        ):
            return candidate

    return None


def parse_calendar_month(
    soup: BeautifulSoup,
) -> List[Dict[str, str]]:

    year, month = get_calendar_month_year(
        soup
    )

    print()
    print(
        f"CALENDAR MONTH: {year}-{month:02d}"
    )

    table = find_calendar_table(
        soup
    )

    if table is None:

        print(
            "WARNING: no menucalendar table found."
        )

        # Save a useful diagnostic snippet.
        calendar_candidates = []

        for candidate in soup.find_all(
            "table"
        ):

            text = clean_text(
                candidate.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:
                calendar_candidates.append(
                    text[:500]
                )

        save_json(
            "calendar_table_candidates.json",
            calendar_candidates,
        )

        return []

    print(
        "Calendar table FOUND."
    )

    items: List[Dict[str, str]] = []

    cells_seen = 0
    days_seen = 0
    cells_with_items = 0

    for row in table.find_all("tr"):

        for cell in row.find_all("td"):

            cells_seen += 1

            # ---------------------------------------------------------------
            # Find the numeric day.
            # ---------------------------------------------------------------

            day_element = cell.find(
                class_="label_menuday"
            )

            if day_element is None:

                # Fallback: look for a small span containing only a day.
                for span in cell.find_all(
                    "span"
                ):

                    candidate = clean_text(
                        span.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if looks_like_day_number(
                        candidate
                    ):

                        day_element = span
                        break

            if day_element is None:
                continue

            day_text = clean_text(
                day_element.get_text(
                    " ",
                    strip=True,
                )
            )

            if not looks_like_day_number(
                day_text
            ):
                continue

            day_number = int(
                day_text
            )

            if not (
                1
                <= day_number
                <= 31
            ):
                continue

            days_seen += 1

            try:

                calendar_date = dt.date(
                    year,
                    month,
                    day_number,
                )

            except ValueError:
                continue

            # ---------------------------------------------------------------
            # Extract menu names.
            # ---------------------------------------------------------------

            names = extract_menu_names_from_cell(
                cell
            )

            # Remove accidental duplicate whitespace.
            cleaned_names = []

            for name in names:

                name = clean_text(
                    name
                )

                if (
                    name
                    and name not in cleaned_names
                ):
                    cleaned_names.append(
                        name
                    )

            if not cleaned_names:

                continue

            cells_with_items += 1

            item = {
                "date": calendar_date.strftime(
                    "%Y-%m-%d"
                ),
                "main": cleaned_names[0],
                "sides": ", ".join(
                    cleaned_names[1:]
                ),
            }

            items.append(
                item
            )

    print(
        f"Calendar cells seen       : {cells_seen}"
    )

    print(
        f"Calendar days recognized  : {days_seen}"
    )

    print(
        f"Days containing menu data : {cells_with_items}"
    )

    print(
        f"Menu records extracted    : {len(items)}"
    )

    return items


# ============================================================================
# JAVASCRIPT / JSON FALLBACK
# ============================================================================

def parse_embedded_menu_json(
    soup: BeautifulSoup,
) -> List[Dict[str, str]]:

    """
    Fallback for PayPAMS pages that expose menu data through JavaScript.

    This is not required for the normal calendar parser, but it makes the
    scraper resilient to a PayPAMS frontend change.
    """

    results = []

    for script in soup.find_all(
        "script"
    ):

        text = script.get_text(
            "\n",
            strip=False,
        )

        if not text:
            continue

        if not any(
            token in text
            for token in (
                "ItemName",
                "DataCalDay",
                "DistrictID",
                "ServingTypeID",
            )
        ):
            continue

        # Look for JSON objects containing ItemName.
        object_matches = re.findall(
            r"\{[^{}]*?(?:ItemName|DataCalDay)[^{}]*?\}",
            text,
            flags=re.S,
        )

        for raw_object in object_matches:

            # Convert JavaScript-ish single quotes where possible.
            candidate = raw_object.strip()

            try:

                obj = json.loads(
                    candidate
                )

            except Exception:
                continue

            item_name = clean_text(
                str(
                    obj.get(
                        "ItemName",
                        "",
                    )
                )
            )

            raw_date = clean_text(
                str(
                    obj.get(
                        "DataCalDay",
                        "",
                    )
                )
            )

            if not item_name or not raw_date:
                continue

            date_match = re.search(
                r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})",
                raw_date,
            )

            if not date_match:
                continue

            month = int(
                date_match.group(1)
            )

            day = int(
                date_match.group(2)
            )

            year = int(
                date_match.group(3)
            )

            if year < 100:
                year += 2000

            try:

                date_value = dt.date(
                    year,
                    month,
                    day,
                )

            except ValueError:
                continue

            results.append(
                {
                    "date": date_value.strftime(
                        "%Y-%m-%d"
                    ),
                    "main": item_name,
                    "sides": "",
                }
            )

    return results


# ============================================================================
# NEXT MONTH
# ============================================================================

def advance_to_next_month(
    session: requests.Session,
    soup: BeautifulSoup,
) -> Optional[BeautifulSoup]:

    print()
    print("=" * 80)
    print("NEXT MONTH")
    print("=" * 80)

    next_link = soup.find(
        "a",
        id="h_NextMonth",
    )

    if next_link is None:

        # Fallback: look for links whose id/text suggests next month.
        for link in soup.find_all("a"):

            link_id = str(
                link.get(
                    "id",
                    "",
                )
            ).lower()

            text = clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            ).lower()

            if (
                "nextmonth" in link_id
                or "next month" in text
            ):

                next_link = link
                break

    if next_link is None:

        print(
            "No Next Month link found."
        )

        return None

    href = next_link.get(
        "href",
        "",
    )

    target, argument = postback_from_href(
        href
    )

    if not target:

        print(
            "Next Month link found, but its "
            "postback could not be parsed."
        )

        print(
            "href:",
            href,
        )

        return None

    print(
        "Next Month target:",
        target,
    )

    print(
        "Next Month argument:",
        argument,
    )

    next_soup, response = post_form(
        session,
        soup,
        {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": argument or "",
        },
        "NEXT MONTH POSTBACK",
    )

    save_text(
        "05_next_month.html",
        response.text,
    )

    return next_soup


# ============================================================================
# MENU NORMALIZATION
# ============================================================================

def dedupe_items(
    items: List[Dict[str, str]],
) -> List[Dict[str, str]]:

    seen = set()
    output = []

    for item in items:

        key = (
            item.get("date", ""),
            item.get("main", ""),
            item.get("sides", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(
            item
        )

    output.sort(
        key=lambda x: x["date"]
    )

    return output


def filter_upcoming(
    items: List[Dict[str, str]],
) -> List[Dict[str, str]]:

    today = dt.date.today()

    end_date = (
        today
        + dt.timedelta(
            days=DAYS_TO_FETCH
        )
    )

    output = []

    for item in items:

        try:

            date_value = dt.date.fromisoformat(
                item["date"]
            )

        except Exception:
            continue

        if (
            today
            <= date_value
            <= end_date
        ):
            output.append(
                item
            )

    output.sort(
        key=lambda x: x["date"]
    )

    return output


# ============================================================================
# TRMNL
# ============================================================================

def push_to_trmnl(
    menu_items: List[Dict[str, str]],
) -> None:

    webhook_url = os.environ.get(
        "TRMNL_WEBHOOK_URL"
    )

    if not webhook_url:

        die(
            "TRMNL_WEBHOOK_URL environment variable "
            "is missing."
        )

    payload = {
        "merge_variables": {
            "menu_items": menu_items,
        }
    }

    save_json(
        "trmnl_payload.json",
        payload,
    )

    print()
    print("=" * 80)
    print("TRMNL PAYLOAD")
    print("=" * 80)

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print(
        f"Pushing {len(menu_items)} menu items..."
    )

    response = requests.post(
        webhook_url,
        json=payload,
        headers={
            "Content-Type":
                "application/json",
        },
        timeout=30,
    )

    print(
        "TRMNL status:",
        response.status_code,
    )

    if response.text:
        print(
            "TRMNL response:",
            response.text[:1000],
        )

    if response.status_code not in (
        200,
        201,
        202,
    ):

        die(
            "TRMNL rejected the webhook."
        )

    print()
    print(
        "TRMNL synchronization successful."
    )


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print()
    print("=" * 80)
    print("PAYPAMS -> MAINE -> LEWISTON -> GEIGER -> LUNCH -> TRMNL")
    print("=" * 80)

    print()
    print(
        "Today:",
        dt.date.today().isoformat(),
    )

    print(
        "State:",
        STATE,
    )

    print(
        "District:",
        DISTRICT_NAME,
    )

    print(
        "School:",
        SCHOOL_NAME,
    )

    print(
        "Meal:",
        MEAL_NAME,
    )

    print(
        "Fetch window:",
        DAYS_TO_FETCH,
        "days",
    )

    # ------------------------------------------------------------------------
    # SESSION
    # ------------------------------------------------------------------------

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:

        # --------------------------------------------------------------------
        # 1. INITIAL
        # --------------------------------------------------------------------

        soup = initial_get(
            session
        )

        # --------------------------------------------------------------------
        # 2. MAINE
        # --------------------------------------------------------------------

        soup = select_state(
            session,
            soup,
        )

        # --------------------------------------------------------------------
        # 3. LEWISTON
        # --------------------------------------------------------------------

        soup = select_district(
            session,
            soup,
        )

        # --------------------------------------------------------------------
        # 4. GEIGER + LUNCH
        # --------------------------------------------------------------------

        (
            current_soup,
            school_value,
            meal_value,
        ) = select_school_and_meal(
            session,
            soup,
        )

        # --------------------------------------------------------------------
        # 5. PARSE CURRENT MONTH
        # --------------------------------------------------------------------

        print()
        print("=" * 80)
        print("STEP 5 - PARSE CURRENT MONTH")
        print("=" * 80)

        current_items = parse_calendar_month(
            current_soup
        )

        print()
        print(
            "Current month records:",
            len(current_items),
        )

        # --------------------------------------------------------------------
        # 6. FALLBACK EMBEDDED DATA
        # --------------------------------------------------------------------

        if not current_items:

            print()
            print(
                "Calendar parser returned zero items."
            )

            print(
                "Trying embedded menu-data fallback..."
            )

            embedded_items = parse_embedded_menu_json(
                current_soup
            )

            print(
                "Embedded records:",
                len(embedded_items),
            )

            if embedded_items:
                current_items.extend(
                    embedded_items
                )

        # --------------------------------------------------------------------
        # 7. NEXT MONTH
        # --------------------------------------------------------------------

        all_items = list(
            current_items
        )

        next_soup = advance_to_next_month(
            session,
            current_soup,
        )

        if next_soup is not None:

            next_items = parse_calendar_month(
                next_soup
            )

            print()
            print(
                "Next month records:",
                len(next_items),
            )

            all_items.extend(
                next_items
            )

        # --------------------------------------------------------------------
        # 8. DEDUPE
        # --------------------------------------------------------------------

        all_items = dedupe_items(
            all_items
        )

        print()
        print(
            "Total unique records:",
            len(all_items),
        )

        save_json(
            "all_parsed_items.json",
            all_items,
        )

        # --------------------------------------------------------------------
        # 9. FILTER
        # --------------------------------------------------------------------

        upcoming_items = filter_upcoming(
            all_items
        )

        save_json(
            "upcoming_items.json",
            upcoming_items,
        )

        # --------------------------------------------------------------------
        # 10. PRINT WHAT WE ACTUALLY GOT
        # --------------------------------------------------------------------

        print()
        print("=" * 80)
        print("UPCOMING LUNCHES")
        print("=" * 80)

        if upcoming_items:

            for item in upcoming_items:

                sides = item.get(
                    "sides",
                    "",
                )

                if sides:
                    print(
                        f"{item['date']} | "
                        f"{item['main']} | "
                        f"{sides}"
                    )
                else:
                    print(
                        f"{item['date']} | "
                        f"{item['main']}"
                    )

        else:

            print(
                "ZERO upcoming menu items."
            )

        # --------------------------------------------------------------------
        # 11. HARD FAILURE ON EMPTY DATA
        #
        # DO NOT push an empty array to TRMNL and call it success.
        # --------------------------------------------------------------------

        if not upcoming_items:

            print()
            print("=" * 80)
            print("NO MENU DATA WAS EXTRACTED")
            print("=" * 80)

            print()
            print(
                "The scraper will NOT overwrite the existing "
                "TRMNL data with an empty menu."
            )

            print()
            print(
                "Debug files are in:"
            )

            print(
                OUT_DIR.resolve()
            )

            print()
            print(
                "Most useful file:"
            )

            print(
                OUT_DIR
                / "04_after_Geiger_Lunch_post.html"
            )

            return 2

        # --------------------------------------------------------------------
        # 12. TRMNL
        # --------------------------------------------------------------------

        push_to_trmnl(
            upcoming_items
        )

        # --------------------------------------------------------------------
        # 13. FINAL REPORT
        # --------------------------------------------------------------------

        report = {
            "run_date": dt.date.today().isoformat(),
            "state": STATE,
            "district": DISTRICT_NAME,
            "school": SCHOOL_NAME,
            "school_value": school_value,
            "meal": MEAL_NAME,
            "meal_value": meal_value,
            "days_requested": DAYS_TO_FETCH,
            "all_items": len(all_items),
            "upcoming_items": len(upcoming_items),
            "items": upcoming_items,
        }

        save_json(
            "final_report.json",
            report,
        )

        print()
        print("=" * 80)
        print("SUCCESS")
        print("=" * 80)

        print()
        print(
            f"{len(upcoming_items)} upcoming "
            "lunches sent to TRMNL."
        )

        return 0

    except requests.RequestException as exc:

        print()
        print("=" * 80)
        print("HTTP ERROR")
        print("=" * 80)

        print(
            type(exc).__name__,
            str(exc),
        )

        return 1

    except KeyboardInterrupt:

        print()
        print(
            "Interrupted."
        )

        return 130

    except Exception as exc:

        print()
        print("=" * 80)
        print("UNEXPECTED ERROR")
        print("=" * 80)

        print(
            type(exc).__name__,
            str(exc),
        )

        import traceback

        traceback.print_exc()

        return 1


if __name__ == "__main__":
    sys.exit(
        main()
    )
```
