import os
import re
import sys
import datetime

import requests
from bs4 import BeautifulSoup

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

BASE_URL = "https://paypams.com/TN_Menus.aspx"

SCHOOL_NAME = "Geiger"

MEAL_TYPE_NAME = "Lunch"

def extract_form_fields(soup):
"""
Collect the current ASP.NET WebForms form state.
"""

```
fields = {}

form = soup.find("form")

if not form:
    raise RuntimeError("Could not find PayPAMS form.")

for tag in form.find_all(["input", "select", "textarea"]):

    name = tag.get("name")

    if not name:
        continue

    if tag.name == "select":

        selected = tag.find(
            "option",
            selected=True,
        )

        if selected is None:
            selected = tag.find("option")

        if selected is not None:
            fields[name] = selected.get(
                "value",
                selected.get_text(
                    strip=True
                ),
            )

        else:
            fields[name] = ""

    elif tag.name == "textarea":

        fields[name] = tag.text

    else:

        input_type = (
            tag.get("type") or "text"
        ).lower()

        if input_type in (
            "checkbox",
            "radio",
        ):

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

def parse_do_postback(href):
"""
Extract an ASP.NET postback target and argument.
"""

```
if not href:
    return None, None

match = re.search(
    r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
    href,
)

if match:
    return (
        match.group(1),
        match.group(2),
    )

match = re.search(
    r'WebForm_PostBackOptions\(\s*["\']([^"\']*)["\']\s*,\s*["\']([^"\']*)["\']',
    href,
)

if match:
    return (
        match.group(1),
        match.group(2),
    )

return None, None
```

def find_select_value(
soup,
select_id,
option_text_contains,
):
"""
Find a select option by visible text.
"""

```
select_el = soup.find(
    "select",
    id=select_id,
)

if not select_el:
    return None, []

all_options = []

match_value = None

search_text = option_text_contains.lower()

for opt in select_el.find_all("option"):

    text = opt.get_text(
        " ",
        strip=True,
    )

    value = opt.get(
        "value",
        "",
    )

    all_options.append(
        (
            text,
            value,
        )
    )

    if (
        match_value is None
        and search_text in text.lower()
    ):

        match_value = value

return (
    match_value,
    all_options,
)
```

def post_step(
session,
url,
soup,
overrides,
):
"""
Submit an ASP.NET WebForms postback.

```
Every postback gets the hidden state from the
immediately preceding page.
"""

payload = extract_form_fields(
    soup
)

payload.update(
    overrides
)

response = session.post(
    url,
    data=payload,
    timeout=30,
)

response.raise_for_status()

return (
    BeautifulSoup(
        response.text,
        "html.parser",
    ),
    response,
)
```

def parse_calendar_month(soup):
"""
Parse PayPAMS menucalendar into:

```
[
    {
        "date": "YYYY-MM-DD",
        "main": "...",
        "sides": "..."
    }
]
"""

month_year_el = soup.find(
    "span",
    id="h_LBL_MonthYear",
)

today = datetime.date.today()

target_year = today.year
target_month = today.month

if month_year_el:

    parts = month_year_el.get_text(
        " ",
        strip=True,
    ).split()

    if (
        len(parts) == 2
        and parts[0].lower() in MONTHS_MAP
    ):

        target_month = MONTHS_MAP[
            parts[0].lower()
        ]

        try:

            target_year = int(
                parts[1]
            )

        except ValueError:

            pass

items = []

table = soup.find(
    "table",
    class_="menucalendar",
)

if not table:

    print(
        "WARNING: menucalendar table was not found."
    )

    return items

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

        day_num = int(
            day_text
        )

        names = []

        for item_el in cell.find_all(
            "span",
            class_="uncheckedNC",
        ):

            name = item_el.get_text(
                " ",
                strip=True,
            )

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

            computed_date = datetime.date(
                target_year,
                target_month,
                day_num,
            )

        except ValueError:

            continue

        items.append(
            {
                "date": computed_date.strftime(
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

def find_next_month_postback(soup):
"""
Locate the PayPAMS next-month link and extract
its ASP.NET postback information.
"""

```
next_link = soup.find(
    "a",
    id="h_NextMonth",
)

if not next_link:
    return None, None

href = next_link.get(
    "href",
    "",
)

return parse_do_postback(
    href
)
```

def print_menu_items(items):
print()
print("UPCOMING LUNCHES")
print()

```
if not items:

    print(
        "No upcoming menu items were found."
    )

    return

for item in items:

    print(
        "{} | {} | {}".format(
            item["date"],
            item["main"],
            item["sides"],
        )
    )
```

def fetch_and_sync():

```
trmnl_url = os.environ.get(
    "TRMNL_WEBHOOK_URL"
)

if not trmnl_url:

    print(
        "CRITICAL ERROR: "
        "TRMNL_WEBHOOK_URL environment variable is missing!"
    )

    sys.exit(1)

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": (
            "en-US,en;q=0.9"
        ),
        "Origin": "https://paypams.com",
        "Referer": BASE_URL,
    }
)

try:

    print(
        "Loading {} ...".format(
            BASE_URL
        )
    )

    response = session.get(
        BASE_URL,
        timeout=30,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    print(
        "Response status: {}".format(
            response.status_code
        )
    )

    print(
        "Final URL: {}".format(
            response.url
        )
    )

    title_el = soup.find(
        "title"
    )

    if title_el:

        print(
            "Page title: {}".format(
                title_el.get_text(
                    strip=True
                )
            )
        )

    all_selects = soup.find_all(
        "select"
    )

    print(
        "Found {} select elements.".format(
            len(all_selects)
        )
    )

    for select in all_selects:

        print(
            "  id={!r} name={!r} options={}".format(
                select.get("id"),
                select.get("name"),
                len(
                    select.find_all(
                        "option"
                    )
                ),
            )
        )

    school_value, school_options = find_select_value(
        soup,
        "h_DD_Schools",
        SCHOOL_NAME,
    )

    print()
    print(
        "Schools found:"
    )

    for text, value in school_options:

        print(
            "  {!r} -> {!r}".format(
                text,
                value,
            )
        )

    if not school_value:

        print()
        print(
            "CRITICAL ERROR:"
        )

        print(
            "No school containing {!r} "
            "was found.".format(
                SCHOOL_NAME
            )
        )

        print(
            "PayPAMS may have returned a "
            "different district."
        )

        sys.exit(1)

    print()
    print(
        "Selecting school:"
    )

    print(
        "  {} -> {}".format(
            SCHOOL_NAME,
            school_value,
        )
    )

    soup, response = post_step(
        session,
        BASE_URL,
        soup,
        {
            "__EVENTTARGET": "h_DD_Schools",
            "__EVENTARGUMENT": "",
            "h_DD_Schools": school_value,
        },
    )

    print(
        "School postback status: {}".format(
            response.status_code
        )
    )

    meal_value, meal_options = find_select_value(
        soup,
        "h_DD_MealTypes",
        MEAL_TYPE_NAME,
    )

    if not meal_value:

        print()
        print(
            "Meal types found:"
        )

        for text, value in meal_options:

            print(
                "  {!r} -> {!r}".format(
                    text,
                    value,
                )
            )

        print()
        print(
            "CRITICAL ERROR:"
        )

        print(
            "No meal containing {!r} was found.".format(
                MEAL_TYPE_NAME
            )
        )

        sys.exit(1)

    print()
    print(
        "Selecting meal:"
    )

    print(
        "  {} -> {}".format(
            MEAL_TYPE_NAME,
            meal_value,
        )
    )

    current_month_soup, response = post_step(
        session,
        BASE_URL,
        soup,
        {
            "__EVENTTARGET": "h_DD_MealTypes",
            "__EVENTARGUMENT": "",
            "h_DD_Schools": school_value,
            "h_DD_MealTypes": meal_value,
        },
    )

    print(
        "Lunch postback status: {}".format(
            response.status_code
        )
    )

    all_menu_items = parse_calendar_month(
        current_month_soup
    )

    print(
        "Parsed {} items from current month.".format(
            len(all_menu_items)
        )
    )

    event_target, event_argument = (
        find_next_month_postback(
            current_month_soup
        )
    )

    if event_target:

        print(
            "Fetching next month..."
        )

        next_month_soup, response = post_step(
            session,
            BASE_URL,
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

        next_items = parse_calendar_month(
            next_month_soup
        )

        print(
            "Parsed {} items from next month.".format(
                len(next_items)
            )
        )

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
            "WARNING: Could not find next-month postback."
        )

    today_str = datetime.date.today().strftime(
        "%Y-%m-%d"
    )

    upcoming_items = [
        item
        for item in all_menu_items
        if item["date"] >= today_str
    ]

    upcoming_items.sort(
        key=lambda item: item["date"]
    )

    print_menu_items(
        upcoming_items
    )

    trmnl_payload = {
        "merge_variables": {
            "menu_items": upcoming_items,
        }
    }

    print()
    print(
        "Pushing {} upcoming menu items to TRMNL...".format(
            len(upcoming_items)
        )
    )

    push_response = requests.post(
        trmnl_url,
        json=trmnl_payload,
        headers={
            "Content-Type": "application/json"
        },
        timeout=30,
    )

    print(
        "TRMNL status: {}".format(
            push_response.status_code
        )
    )

    if push_response.text:

        print(
            "TRMNL response:"
        )

        print(
            push_response.text[:1000]
        )

    if push_response.status_code not in (
        200,
        201,
        202,
    ):

        print(
            "ERROR: TRMNL rejected the webhook."
        )

        sys.exit(1)

    print()
    print(
        "SUCCESS: menu synchronized."
    )

    print(
        "Menu items sent: {}".format(
            len(upcoming_items)
        )
    )

except requests.RequestException as err:

    print()
    print(
        "HTTP ERROR:"
    )

    print(
        str(err)
    )

    sys.exit(1)

except Exception as err:

    print()
    print(
        "CRITICAL PARSER ERROR:"
    )

    print(
        "{}: {}".format(
            type(err).__name__,
            err,
        )
    )

    sys.exit(1)
```

if **name** == "**main**":
fetch_and_sync()
