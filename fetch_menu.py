#!/usr/bin/env python3
import datetime
import json
import os
import re
import sys
import requests
from bs4 import BeautifulSoup

============================================================================
CONFIG
============================================================================
PAYPAMS_URL = "https://paypams.com/TN_Menus.aspx"
SCHOOL_NAME = "Geiger Elementary School"
SCHOOL_SEARCH = "Geiger"
MEAL_NAME = "Lunch"
TRMNL_WEBHOOK_URL = os.environ.get("TRMNL_WEBHOOK_URL")
TIMEOUT = 30
HEADERS = {
"User-Agent": (
"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
"AppleWebKit/537.36 (KHTML, like Gecko) "
"Chrome/151.0.0.0 Safari/537.36"
),
"Accept": (
"text/html,application/xhtml+xml,application/xml;"
"q=0.9,image/avif,image/webp,image/apng,/;q=0.8"
),
"Accept-Language": "en-US,en;q=0.9",
"Referer": PAYPAMS_URL,
}

============================================================================
WEBFORMS HELPERS
============================================================================
def soup(html):
return BeautifulSoup(html, "html.parser")

def form_fields(page):
"""
Return the current ASP.NET WebForms fields.
    This is important because PayPAMS changes __VIEWSTATE,
    __EVENTVALIDATION, etc. after every postback.
    """

    form = page.find("form")

    if form is None:
        raise RuntimeError("PayPAMS form was not found.")

    data = {}

    for element in form.find_all(["input", "select", "textarea"]):

        name = element.get("name")

        if not name:
            continue

        if element.name == "input":

            input_type = (
                element.get("type") or "text"
            ).lower()

            if input_type in (
                "submit",
                "button",
                "image",
                "reset",
            ):
                continue

            if input_type in (
                "checkbox",
                "radio",
            ):

                if element.has_attr("checked"):
                    data[name] = element.get(
                        "value",
                        "on",
                    )

            else:

                data[name] = element.get(
                    "value",
                    "",
                )

        elif element.name == "select":

            selected = element.find(
                "option",
                selected=True,
            )

            if selected is not None:

                data[name] = selected.get(
                    "value",
                    "",
                )

            else:

                data[name] = ""

        elif element.name == "textarea":

            data[name] = element.text

    return data



def postback(
session,
page,
event_target,
event_argument="",
extra=None,
):
"""
Perform an ASP.NET WebForms postback using the CURRENT page state.
"""
    data = form_fields(page)

    data["__EVENTTARGET"] = event_target
    data["__EVENTARGUMENT"] = event_argument

    if extra:
        data.update(extra)

    response = session.post(
        PAYPAMS_URL,
        data=data,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response, soup(
        response.text
    )



============================================================================
SELECT HELPERS
============================================================================
def get_select(page, select_id):
return page.find(
"select",
id=select_id,
)

def dump_select(page, select_id):
select = get_select(
page,
select_id,
)
    print()
    print("SELECT:", select_id)

    if select is None:
        print("  NOT FOUND")
        return

    print(
        "  name:",
        select.get("name"),
    )

    for option in select.find_all("option"):

        print(
            "  ",
            repr(
                option.get_text(
                    " ",
                    strip=True,
                )
            ),
            "=>",
            repr(
                option.get(
                    "value",
                    "",
                )
            ),
        )



def find_option(
page,
select_id,
search_text,
):
select = get_select(
page,
select_id,
)
    if select is None:
        return None

    search_text = search_text.lower()

    for option in select.find_all("option"):

        text = option.get_text(
            " ",
            strip=True,
        )

        if search_text in text.lower():

            return {
                "text": text,
                "value": option.get(
                    "value",
                    "",
                ),
            }

    return None



============================================================================
DATE HELPERS
============================================================================
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

def get_calendar_month(page):
    month_label = page.find(
        "span",
        id="h_LBL_MonthYear",
    )

    if month_label:

        text = month_label.get_text(
            " ",
            strip=True,
        )

        match = re.search(
            r"([A-Za-z]+)\s+(\d{4})",
            text,
        )

        if match:

            month_name = (
                match.group(1).lower()
            )

            year = int(
                match.group(2)
            )

            if month_name in MONTHS:

                return (
                    year,
                    MONTHS[month_name],
                )

    today = datetime.date.today()

    return (
        today.year,
        today.month,
    )



============================================================================
MENU PARSER
============================================================================
def parse_menu(page):
    table = page.find(
        "table",
        class_="menucalendar",
    )

    if table is None:

        print()
        print(
            "WARNING: table.menucalendar was not found."
        )

        return []

    year, month = get_calendar_month(
        page
    )

    print()
    print(
        "Calendar month:",
        year,
        month,
    )

    results = []

    for cell in table.find_all("td"):

        day_element = cell.find(
            "span",
            class_="label_menuday",
        )

        if day_element is None:
            continue

        day_text = day_element.get_text(
            " ",
            strip=True,
        )

        if not day_text.isdigit():
            continue

        day = int(
            day_text
        )

        try:

            menu_date = datetime.date(
                year,
                month,
                day,
            )

        except ValueError:

            continue

        foods = []

        for item in cell.find_all(
            "span",
            class_="uncheckedNC",
        ):

            text = item.get_text(
                " ",
                strip=True,
            )

            text = re.sub(
                r"^\s*[✓✔]\s*",
                "",
                text,
            ).strip()

            if text:
                foods.append(
                    text
                )

        if not foods:
            continue

        results.append(
            {
                "date": menu_date.isoformat(),
                "main": foods[0],
                "sides": ", ".join(
                    foods[1:]
                ),
            }
        )

    return results



============================================================================
NEXT MONTH
============================================================================
def find_next_month_postback(page):
    candidates = []

    for element in page.find_all("a"):

        text = element.get_text(
            " ",
            strip=True,
        )

        element_id = element.get(
            "id",
            "",
        )

        href = element.get(
            "href",
            "",
        )

        combined = (
            text
            + " "
            + element_id
            + " "
            + href
        ).lower()

        if (
            "next" in combined
            and (
                "month" in combined
                or ">" in text
            )
        ):

            candidates.append(
                element
            )

    for element in candidates:

        href = element.get(
            "href",
            "",
        )

        match = re.search(
            r"__doPostBack\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
            href,
            flags=re.I,
        )

        if match:

            return (
                match.group(1),
                match.group(2),
            )

    return None



============================================================================
TRMNL
============================================================================
def send_to_trmnl(items):
    if not TRMNL_WEBHOOK_URL:

        raise RuntimeError(
            "TRMNL_WEBHOOK_URL environment variable "
            "is not configured."
        )

    payload = {
        "merge_variables": {
            "menu_items": items,
        }
    }

    print()
    print(
        "Sending payload to TRMNL..."
    )

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )

    response = requests.post(
        TRMNL_WEBHOOK_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
        },
        timeout=TIMEOUT,
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

    response.raise_for_status()



============================================================================
MAIN
============================================================================
def main():
    print()
    print(
        "=" * 72
    )
    print(
        "LEWISTON PUBLIC SCHOOLS"
    )
    print(
        "GEIGER ELEMENTARY SCHOOL"
    )
    print(
        "LUNCH MENU FETCH"
    )
    print(
        "=" * 72
    )

    if not TRMNL_WEBHOOK_URL:

        print()
        print(
            "ERROR: TRMNL_WEBHOOK_URL is not set."
        )

        print(
            "The GitHub Action needs a repository secret "
            "named TRMNL_WEBHOOK_URL."
        )

        return 1

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ------------------------------------------------------------------------
    # STEP 1
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 1: Initial PayPAMS GET"
    )

    response = session.get(
        PAYPAMS_URL,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    page = soup(
        response.text
    )

    print(
        "Status:",
        response.status_code,
    )

    # ------------------------------------------------------------------------
    # STEP 2
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 2: Inspecting school selector"
    )

    dump_select(
        page,
        "h_DD_Schools",
    )

    school = find_option(
        page,
        "h_DD_Schools",
        SCHOOL_SEARCH,
    )

    if school is None:

        print()
        print(
            "ERROR: Geiger was not found."
        )

        print(
            "The PayPAMS page returned no matching "
            "school option."
        )

        return 1

    print(
        "School:",
        school["text"],
    )

    print(
        "School value:",
        school["value"],
    )

    # ------------------------------------------------------------------------
    # STEP 3
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 3: School postback"
    )

    response, page = postback(
        session,
        page,
        "h_DD_Schools",
        "",
        {
            "h_DD_Schools": school["value"],
        },
    )

    print(
        "Status:",
        response.status_code,
    )

    # ------------------------------------------------------------------------
    # STEP 4
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 4: Inspecting meal selector"
    )

    dump_select(
        page,
        "h_DD_MealTypes",
    )

    meal = find_option(
        page,
        "h_DD_MealTypes",
        MEAL_NAME,
    )

    if meal is None:

        print()
        print(
            "ERROR: Lunch was not found."
        )

        return 1

    print(
        "Meal:",
        meal["text"],
    )

    print(
        "Meal value:",
        meal["value"],
    )

    # ------------------------------------------------------------------------
    # STEP 5
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 5: Lunch postback"
    )

    response, page = postback(
        session,
        page,
        "h_DD_MealTypes",
        "",
        {
            "h_DD_Schools": school["value"],
            "h_DD_MealTypes": meal["value"],
        },
    )

    print(
        "Status:",
        response.status_code,
    )

    # ------------------------------------------------------------------------
    # STEP 6
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 6: Parsing menu calendar"
    )

    items = parse_menu(
        page
    )

    print(
        "Current month items:",
        len(items),
    )

    # ------------------------------------------------------------------------
    # STEP 7
    # ------------------------------------------------------------------------

    next_postback = find_next_month_postback(
        page
    )

    if next_postback:

        print()
        print(
            "STEP 7: Fetching next month"
        )

        response, next_page = postback(
            session,
            page,
            next_postback[0],
            next_postback[1],
            {
                "h_DD_Schools": school["value"],
                "h_DD_MealTypes": meal["value"],
            },
        )

        print(
            "Status:",
            response.status_code,
        )

        next_items = parse_menu(
            next_page
        )

        print(
            "Next month items:",
            len(next_items),
        )

        known_dates = {
            item["date"]
            for item in items
        }

        for item in next_items:

            if item["date"] not in known_dates:

                items.append(
                    item
                )

    else:

        print()
        print(
            "No next-month postback found."
        )

    # ------------------------------------------------------------------------
    # STEP 8
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 8: Filtering upcoming lunches"
    )

    today = datetime.date.today()

    upcoming = []

    for item in items:

        try:

            item_date = datetime.date.fromisoformat(
                item["date"]
            )

        except Exception:

            continue

        if item_date >= today:

            upcoming.append(
                item
            )

    upcoming.sort(
        key=lambda item: item["date"]
    )

    # Keep one record per date.
    deduped = []

    seen = set()

    for item in upcoming:

        if item["date"] in seen:
            continue

        seen.add(
            item["date"]
        )

        deduped.append(
            item
        )

    upcoming = deduped

    # ------------------------------------------------------------------------
    # STEP 9
    # ------------------------------------------------------------------------

    print()
    print(
        "=" * 72
    )
    print(
        "UPCOMING LUNCHES"
    )
    print(
        "=" * 72
    )

    if not upcoming:

        print(
            "NO UPCOMING MENU ITEMS FOUND."
        )

    else:

        for item in upcoming:

            print(
                item["date"],
                "|",
                item["main"],
                "|",
                item["sides"],
            )

    # ------------------------------------------------------------------------
    # STEP 10
    # ------------------------------------------------------------------------

    print()
    print(
        "STEP 10: Sending menu to TRMNL"
    )

    send_to_trmnl(
        upcoming
    )

    print()
    print(
        "=" * 72
    )
    print(
        "SUCCESS"
    )
    print(
        "=" * 72
    )

    print(
        "Menu items sent:",
        len(upcoming),
    )

    return 0



if name == "main":
sys.exit(
main()
)
