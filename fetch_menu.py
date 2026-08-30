#!/usr/bin/env python3

from **future** import annotations

import datetime
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ============================================================================

# CONFIGURATION

# ============================================================================

BASE_URL = "https://paypams.com/TN_Menus.aspx"

SCHOOL_NAME = "Geiger"
MEAL_TYPE_NAME = "Lunch"

TRMNL_WEBHOOK_URL = os.environ.get("TRMNL_WEBHOOK_URL")

REQUEST_TIMEOUT = 30

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
"Origin": "https://paypams.com",
"Referer": BASE_URL,
"Connection": "keep-alive",
}

MONTHS_MAP = {
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

# BASIC HELPERS

# ============================================================================

def get_soup(html: str) -> BeautifulSoup:
return BeautifulSoup(html, "html.parser")

def extract_form_fields(soup: BeautifulSoup) -> Dict[str, str]:
"""
Collect the CURRENT state of the ASP.NET WebForms form.

```
PayPAMS is an ASP.NET WebForms application, so postbacks need the
hidden __VIEWSTATE/__EVENTVALIDATION/etc. values from the CURRENT page.
"""

fields: Dict[str, str] = {}

for tag in soup.find_all(["input", "select", "textarea"]):

    name = tag.get("name")

    if not name:
        continue

    if tag.name == "select":

        selected = (
            tag.find("option", selected=True)
            or tag.find("option")
        )

        if selected:
            fields[name] = selected.get(
                "value",
                selected.get_text(strip=True),
            )
        else:
            fields[name] = ""

    elif tag.name == "textarea":

        fields[name] = tag.text

    else:

        input_type = (
            tag.get("type") or "text"
        ).lower()

        if input_type in ("checkbox", "radio"):

            if tag.has_attr("checked"):
                fields[name] = tag.get(
                    "value",
                    "on",
                )

        elif input_type in (
            "submit",
            "button",
            "image",
            "reset",
        ):

            continue

        else:

            fields[name] = tag.get(
                "value",
                "",
            )

return fields
```

def find_select_value(
soup: BeautifulSoup,
select_id: str,
text_to_match: str,
) -> Tuple[Optional[str], List[Tuple[str, str]]]:

```
select = soup.find(
    "select",
    id=select_id,
)

if not select:
    return None, []

options: List[Tuple[str, str]] = []

match_value: Optional[str] = None

for option in select.find_all("option"):

    text = option.get_text(
        " ",
        strip=True,
    )

    value = option.get(
        "value",
        "",
    )

    options.append(
        (text, value)
    )

    if (
        match_value is None
        and text_to_match.lower()
        in text.lower()
    ):
        match_value = value

return match_value, options
```

# ============================================================================

# POSTBACK HELPERS

# ============================================================================

def parse_do_postback(
href: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:

```
if not href:
    return None, None

# javascript:__doPostBack('target','argument')
match = re.search(
    r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
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
    r'WebForm_PostBackOptions\(\s*["\']([^"\']*)["\']\s*,\s*["\']([^"\']*)["\']',
    href,
    flags=re.I,
)

if match:
    return (
        match.group(1),
        match.group(2),
    )

return None, None
```

def post_step(
session: requests.Session,
soup: BeautifulSoup,
overrides: Dict[str, str],
) -> Tuple[BeautifulSoup, requests.Response]:

```
payload = extract_form_fields(
    soup
)

payload.update(
    overrides
)

response = session.post(
    BASE_URL,
    data=payload,
    timeout=REQUEST_TIMEOUT,
)

response.raise_for_status()

return (
    get_soup(response.text),
    response,
)
```

# ============================================================================

# MENU PARSER

# ============================================================================

def parse_calendar_month(
soup: BeautifulSoup,
) -> List[Dict[str, str]]:

```
"""
Parse PayPAMS's menu calendar.

Expected structure:

    table.menucalendar

      span.label_menuday
      span.uncheckedNC

Produces:

    {
        "date": "YYYY-MM-DD",
        "main": "...",
        "sides": "..."
    }
"""

month_year = soup.find(
    "span",
    id="h_LBL_MonthYear",
)

today = datetime.date.today()

target_year = today.year
target_month = today.month

if month_year:

    text = month_year.get_text(
        " ",
        strip=True,
    )

    parts = text.split()

    if len(parts) == 2:

        month_name = parts[0].lower()

        if month_name in MONTHS_MAP:

            target_month = MONTHS_MAP[
                month_name
            ]

            try:
                target_year = int(
                    parts[1]
                )
            except ValueError:
                pass

table = soup.find(
    "table",
    class_="menucalendar",
)

if not table:
    print(
        "WARNING: no table.menucalendar found."
    )
    return []

items: List[Dict[str, str]] = []

for row in table.find_all("tr"):

    for cell in row.find_all("td"):

        day_span = cell.find(
            "span",
            class_="label_menuday",
        )

        if not day_span:
            continue

        day_text = day_span.get_text(
            " ",
            strip=True,
        )

        if not day_text.isdigit():
            continue

        day_number = int(
            day_text
        )

        names: List[str] = []

        for item_el in cell.find_all(
            "span",
            class_="uncheckedNC",
        ):

            name = item_el.get_text(
                " ",
                strip=True,
            )

            # Remove leading checkmark if PayPAMS includes one.
            name = name.lstrip(
                "\u2713"
            ).strip()

            if name:
                names.append(
                    name
                )

        if not names:
            continue

        try:

            menu_date = datetime.date(
                target_year,
                target_month,
                day_number,
            )

        except ValueError:

            continue

        items.append(
            {
                "date": menu_date.strftime(
                    "%Y-%m-%d"
                ),
                "main": names[0],
                "sides": ", ".join(
                    names[1:]
                ),
            }
        )

return items
```

# ============================================================================

# DEBUGGING / VALIDATION

# ============================================================================

def print_select(
soup: BeautifulSoup,
select_id: str,
) -> None:

```
select = soup.find(
    "select",
    id=select_id,
)

print()
print(
    f"--- {select_id} ---"
)

if not select:

    print(
        "NOT FOUND"
    )

    return

print(
    "name:",
    select.get("name"),
)

for option in select.find_all(
    "option"
):

    print(
        f"  {option.get_text(' ', strip=True)!r}"
        f" -> {option.get('value', '')!r}"
    )
```

def print_menu_items(
items: List[Dict[str, str]],
) -> None:

```
print()
print(
    "=" * 70
)
print(
    "PARSED MENU ITEMS"
)
print(
    "=" * 70
)

if not items:

    print(
        "NO MENU ITEMS FOUND"
    )

    return

for item in items:

    print(
        f"{item['date']} | "
        f"{item['main']} | "
        f"{item['sides']}"
    )
```

# ============================================================================

# MAIN FETCH

# ============================================================================

def fetch_and_sync() -> None:

```
if not TRMNL_WEBHOOK_URL:

    print(
        "CRITICAL ERROR: "
        "TRMNL_WEBHOOK_URL environment variable is missing!"
    )

    sys.exit(1)

print()
print(
    "=" * 70
)
print(
    "LEWISTON PUBLIC SCHOOLS MENU FETCH"
)
print(
    "=" * 70
)

print(
    "School:",
    SCHOOL_NAME,
)

print(
    "Meal:",
    MEAL_TYPE_NAME,
)

session = requests.Session()

session.headers.update(
    HEADERS
)

# ------------------------------------------------------------------------
# 1. INITIAL GET
# ------------------------------------------------------------------------

print()
print(
    "1. Loading PayPAMS..."
)

response = session.get(
    BASE_URL,
    timeout=REQUEST_TIMEOUT,
)

response.raise_for_status()

soup = get_soup(
    response.text
)

print(
    "   Status:",
    response.status_code,
)

print(
    "   URL:",
    response.url,
)

# ------------------------------------------------------------------------
# 2. FIND SCHOOL
# ------------------------------------------------------------------------

print()
print(
    "2. Finding Geiger..."
)

school_value, school_options = find_select_value(
    soup,
    "h_DD_Schools",
    SCHOOL_NAME,
)

print(
    "   Schools available:"
)

for text, value in school_options:

    print(
        f"      {text!r} -> {value!r}"
    )

if not school_value:

    print()
    print(
        "CRITICAL ERROR:"
    )

    print(
        f"Could not find school containing {SCHOOL_NAME!r}."
    )

    print(
        "PayPAMS may be geolocating this runner "
        "to a different district."
    )

    sys.exit(1)

print(
    "   Selected school value:",
    school_value,
)

# ------------------------------------------------------------------------
# 3. SCHOOL POSTBACK
# ------------------------------------------------------------------------

print()
print(
    "3. Posting school selection..."
)

soup, response = post_step(
    session,
    soup,
    {
        "__EVENTTARGET": "h_DD_Schools",
        "__EVENTARGUMENT": "",
        "h_DD_Schools": school_value,
    },
)

print(
    "   Status:",
    response.status_code,
)

# ------------------------------------------------------------------------
# 4. FIND LUNCH
# ------------------------------------------------------------------------

print()
print(
    "4. Finding Lunch..."
)

meal_value, meal_options = find_select_value(
    soup,
    "h_DD_MealTypes",
    MEAL_TYPE_NAME,
)

print(
    "   Meal types available:"
)

for text, value in meal_options:

    print(
        f"      {text!r} -> {value!r}"
    )

if not meal_value:

    print()
    print(
        "CRITICAL ERROR:"
    )

    print(
        f"Could not find meal type containing {MEAL_TYPE_NAME!r}."
    )

    sys.exit(1)

print(
    "   Selected meal value:",
    meal_value,
)

# ------------------------------------------------------------------------
# 5. LUNCH POSTBACK
# ------------------------------------------------------------------------

print()
print(
    "5. Posting Lunch selection..."
)

current_month_soup, response = post_step(
    session,
    soup,
    {
        "__EVENTTARGET": "h_DD_MealTypes",
        "__EVENTARGUMENT": "",
        "h_DD_Schools": school_value,
        "h_DD_MealTypes": meal_value,
    },
)

print(
    "   Status:",
    response.status_code,
)

# ------------------------------------------------------------------------
# 6. PARSE CURRENT MONTH
# ------------------------------------------------------------------------

print()
print(
    "6. Parsing current month..."
)

all_menu_items = parse_calendar_month(
    current_month_soup
)

print(
    f"   Found {len(all_menu_items)} items."
)

# ------------------------------------------------------------------------
# 7. NEXT MONTH
# ------------------------------------------------------------------------

print()
print(
    "7. Looking for next month..."
)

next_link = current_month_soup.find(
    "a",
    id="h_NextMonth",
)

if next_link:

    href = next_link.get(
        "href"
    )

    event_target, event_argument = parse_do_postback(
        href
    )

    print(
        "   Next-month target:",
        event_target,
    )

    print(
        "   Next-month argument:",
        event_argument,
    )

    if event_target:

        next_month_soup, response = post_step(
            session,
            current_month_soup,
            {
                "__EVENTTARGET": event_target,
                "__EVENTARGUMENT": (
                    event_argument or ""
                ),
                "h_DD_Schools": school_value,
                "h_DD_MealTypes": meal_value,
            },
        )

        print(
            "   Next-month status:",
            response.status_code,
        )

        next_items = parse_calendar_month(
            next_month_soup
        )

        print(
            f"   Found {len(next_items)} next-month items."
        )

        # Avoid duplicate month if PayPAMS failed to advance.
        if next_items:

            existing_dates = {
                item["date"]
                for item in all_menu_items
            }

            for item in next_items:

                if item["date"] not in existing_dates:

                    all_menu_items.append(
                        item
                    )

else:

    print(
        "   No next-month link found."
    )

# ------------------------------------------------------------------------
# 8. FILTER UPCOMING
# ------------------------------------------------------------------------

today = datetime.date.today()

upcoming_items = []

for item in all_menu_items:

    try:

        item_date = datetime.date.fromisoformat(
            item["date"]
        )

    except ValueError:

        continue

    if item_date >= today:

        upcoming_items.append(
            item
        )

upcoming_items.sort(
    key=lambda item: item["date"]
)

# Remove duplicate dates while preserving the first entry.
deduped_items = []

seen_dates = set()

for item in upcoming_items:

    date_value = item["date"]

    if date_value in seen_dates:
        continue

    seen_dates.add(
        date_value
    )

    deduped_items.append(
        item
    )

upcoming_items = deduped_items

# ------------------------------------------------------------------------
# 9. SHOW WHAT WE GOT
# ------------------------------------------------------------------------

print_menu_items(
    upcoming_items
)

print()
print(
    f"Upcoming menu items: {len(upcoming_items)}"
)

# ------------------------------------------------------------------------
# 10. BUILD EXACT TRMNL PAYLOAD
# ------------------------------------------------------------------------

trmnl_payload = {
    "merge_variables": {
        "menu_items": upcoming_items,
    }
}

print()
print(
    "=" * 70
)
print(
    "TRMNL PAYLOAD"
)
print(
    "=" * 70
)

print(
    f"Sending {len(upcoming_items)} menu items."
)

# ------------------------------------------------------------------------
# 11. SEND TO TRMNL
# ------------------------------------------------------------------------

push_response = requests.post(
    TRMNL_WEBHOOK_URL,
    json=trmnl_payload,
    headers={
        "Content-Type": "application/json",
    },
    timeout=REQUEST_TIMEOUT,
)

print()
print(
    "TRMNL response status:",
    push_response.status_code,
)

if push_response.status_code not in (
    200,
    201,
    202,
):

    print(
        "TRMNL response:"
    )

    print(
        push_response.text[:1000]
    )

    raise RuntimeError(
        "TRMNL rejected the menu payload."
    )

print()
print(
    "=" * 70
)
print(
    "SUCCESS"
)
print(
    "=" * 70
)

print(
    f"Sent {len(upcoming_items)} upcoming lunches to TRMNL."
)
```

# ============================================================================

# ENTRY POINT

# ============================================================================

if **name** == "**main**":

```
try:

    fetch_and_sync()

except requests.RequestException as exc:

    print()
    print(
        "HTTP ERROR:"
    )

    print(
        str(exc)
    )

    sys.exit(1)

except Exception as exc:

    print()
    print(
        "CRITICAL ERROR:"
    )

    print(
        f"{type(exc).__name__}: {exc}"
    )

    sys.exit(1)
```
