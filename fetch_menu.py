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

# PayPams displays states using USPS abbreviations.
STATE_NAME = "ME"


def extract_form_fields(soup):
    fields = {}

    for tag in soup.find_all(["input", "select", "textarea"]):
        name = tag.get("name")

        if not name:
            continue

        if tag.name == "select":
            selected = tag.find("option", selected=True)

            if selected is None:
                selected = tag.find("option")

            fields[name] = (
                selected.get("value", selected.get_text(strip=True))
                if selected
                else ""
            )

        elif tag.name == "textarea":
            fields[name] = tag.text

        else:
            input_type = (tag.get("type") or "text").lower()

            if input_type in ("checkbox", "radio"):
                if tag.has_attr("checked"):
                    fields[name] = tag.get("value", "on")

            elif input_type in (
                "submit",
                "button",
                "image",
                "reset",
            ):
                continue

            else:
                fields[name] = tag.get("value", "")

    return fields


def parse_do_postback(href):
    if not href:
        return None, None

    patterns = [
        r"__doPostBack\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)",
        r'__doPostBack\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)',
    ]

    for pattern in patterns:
        match = re.search(pattern, href)

        if match:
            return match.group(1), match.group(2)

    match = re.search(
        r'WebForm_PostBackOptions\(\s*"([^"]*)"\s*,\s*"([^"]*)"',
        href,
    )

    if match:
        return match.group(1), match.group(2)

    return None, None


def find_select(soup, select_id):
    return soup.find("select", id=select_id)


def find_select_value(soup, select_id, option_text_contains):
    select_el = find_select(soup, select_id)

    if not select_el:
        return None, []

    all_options = []
    match_value = None

    search_text = option_text_contains.lower()

    for opt in select_el.find_all("option"):
        text = opt.get_text(strip=True)
        value = opt.get("value", "")

        all_options.append((text, value))

        if (
            match_value is None
            and (
                search_text in text.lower()
                or search_text == value.lower()
            )
        ):
            match_value = value

    return match_value, all_options


def get_select_postback_target(select_el):
    if select_el is None:
        return None

    onchange = select_el.get("onchange", "")

    target, _ = parse_do_postback(onchange)

    if target:
        return target

    name = select_el.get("name")

    if name:
        return name

    return select_el.get("id")


def post_step(
    session,
    url,
    soup,
    overrides,
    description="postback",
):
    payload = extract_form_fields(soup)
    payload.update(overrides)

    print(f"POST {description}...")
    print(
        f"  event target: "
        f"{payload.get('__EVENTTARGET', '')!r}"
    )

    res = session.post(
        url,
        data=payload,
        timeout=30,
    )

    res.raise_for_status()

    print(f"  response status: {res.status_code}")
    print(f"  final URL: {res.url}")

    new_soup = BeautifulSoup(
        res.text,
        "html.parser",
    )

    return new_soup, res


def print_selects(
    soup,
    heading="Select elements",
):
    print(heading + ":")

    selects = soup.find_all("select")

    if not selects:
        print("  (none)")
        return

    for sel in selects:
        options = sel.find_all("option")

        print(
            f"  id={sel.get('id')!r} "
            f"name={sel.get('name')!r} "
            f"option_count={len(options)}"
        )


def print_options(options):
    if not options:
        print("  (none)")
        return

    for text, value in options:
        print(
            f"  {text!r} -> value={value!r}"
        )


def parse_calendar_month(soup):
    items = []

    target_year = datetime.date.today().year
    target_month = datetime.date.today().month

    month_year_el = soup.find(
        "span",
        id="h_LBL_MonthYear",
    )

    if month_year_el:
        parts = month_year_el.get_text(
            strip=True
        ).split()

        if len(parts) == 2:
            month_name = parts[0].lower()

            if month_name in MONTHS_MAP:
                target_month = MONTHS_MAP[
                    month_name
                ]

                try:
                    target_year = int(parts[1])
                except ValueError:
                    pass

    table = soup.find(
        "table",
        class_="menucalendar",
    )

    if not table:
        print(
            "WARNING: Could not find "
            "menucalendar table."
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
                strip=True
            )

            if not day_text.isdigit():
                continue

            day_num = int(day_text)

            names = []

            for item_el in cell.find_all(
                "span",
                class_="uncheckedNC",
            ):
                name = (
                    item_el.get_text(
                        strip=True
                    )
                    .lstrip("\u2713")
                    .strip()
                )

                if name:
                    names.append(name)

            if not names:
                continue

            try:
                menu_date = datetime.date(
                    target_year,
                    target_month,
                    day_num,
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


def select_state(
    session,
    soup,
    state_name,
):
    state_select = find_select(
        soup,
        "h_UC_State_h_DD_State",
    )

    if not state_select:
        raise RuntimeError(
            "Could not find state dropdown "
            "'h_UC_State_h_DD_State'."
        )

    state_value, state_options = (
        find_select_value(
            soup,
            "h_UC_State_h_DD_State",
            state_name,
        )
    )

    print(
        "States seen in "
        "h_UC_State_h_DD_State dropdown:"
    )

    print_options(state_options)

    if not state_value:
        raise RuntimeError(
            f"Could not find state "
            f"{state_name!r} in the state dropdown."
        )

    print(
        f"Selecting state "
        f"{state_name!r} "
        f"(value={state_value!r})..."
    )

    event_target = (
        get_select_postback_target(
            state_select
        )
    )

    if not event_target:
        event_target = (
            state_select.get("name")
            or state_select.get("id")
        )

    state_field_name = (
        state_select.get("name")
    )

    if not state_field_name:
        raise RuntimeError(
            "State dropdown has no name attribute."
        )

    soup, response = post_step(
        session,
        BASE_URL,
        soup,
        {
            "__EVENTTARGET": event_target,
            "__EVENTARGUMENT": "",
            state_field_name: state_value,
        },
        description=(
            f"select state {state_name}"
        ),
    )

    print_selects(
        soup,
        "Select elements after state postback",
    )

    return soup, response


def select_school(
    session,
    soup,
    school_name,
):
    school_select = find_select(
        soup,
        "h_DD_Schools",
    )

    if not school_select:
        raise RuntimeError(
            "PayPams did not return the school "
            "dropdown 'h_DD_Schools' after "
            "selecting the state."
        )

    school_value, school_options = (
        find_select_value(
            soup,
            "h_DD_Schools",
            school_name,
        )
    )

    print(
        "Schools seen in "
        "h_DD_Schools dropdown:"
    )

    print_options(school_options)

    if not school_value:
        raise RuntimeError(
            f"Could not find school "
            f"{school_name!r} after selecting "
            f"{STATE_NAME!r}."
        )

    print(
        f"Selecting school "
        f"{school_name!r} "
        f"(value={school_value!r})..."
    )

    event_target = (
        get_select_postback_target(
            school_select
        )
    )

    if not event_target:
        event_target = (
            school_select.get("name")
            or school_select.get("id")
        )

    school_field_name = (
        school_select.get("name")
    )

    if not school_field_name:
        raise RuntimeError(
            "School dropdown has no name attribute."
        )

    soup, response = post_step(
        session,
        BASE_URL,
        soup,
        {
            "__EVENTTARGET": event_target,
            "__EVENTARGUMENT": "",
            school_field_name: school_value,
        },
        description=(
            f"select school {school_name}"
        ),
    )

    print_selects(
        soup,
        "Select elements after school postback",
    )

    return (
        soup,
        response,
        school_value,
    )


def select_meal_type(
    session,
    soup,
    school_value,
    meal_type_name,
):
    meal_select = find_select(
        soup,
        "h_DD_MealTypes",
    )

    if not meal_select:
        raise RuntimeError(
            "PayPams did not return the meal type "
            "dropdown 'h_DD_MealTypes' after "
            "selecting the school."
        )

    meal_value, meal_options = (
        find_select_value(
            soup,
            "h_DD_MealTypes",
            meal_type_name,
        )
    )

    print(
        "Meal types seen in "
        "h_DD_MealTypes dropdown:"
    )

    print_options(meal_options)

    if not meal_value:
        raise RuntimeError(
            f"Could not find meal type "
            f"{meal_type_name!r}."
        )

    print(
        f"Selecting meal type "
        f"{meal_type_name!r} "
        f"(value={meal_value!r})..."
    )

    event_target = (
        get_select_postback_target(
            meal_select
        )
    )

    if not event_target:
        event_target = (
            meal_select.get("name")
            or meal_select.get("id")
        )

    meal_field_name = (
        meal_select.get("name")
    )

    if not meal_field_name:
        raise RuntimeError(
            "Meal type dropdown has no name attribute."
        )

    overrides = {
        "__EVENTTARGET": event_target,
        "__EVENTARGUMENT": "",
        meal_field_name: meal_value,
    }

    school_select = find_select(
        soup,
        "h_DD_Schools",
    )

    if school_select is not None:
        school_field_name = (
            school_select.get("name")
        )

        if school_field_name:
            overrides[
                school_field_name
            ] = school_value

    soup, response = post_step(
        session,
        BASE_URL,
        soup,
        overrides,
        description=(
            f"select meal type "
            f"{meal_type_name}"
        ),
    )

    return (
        soup,
        response,
        meal_value,
    )


def find_next_month_postback(soup):
    """
    Find a likely next-month calendar control.

    PayPams may render the control differently,
    so check several common identifiers.
    """
    candidate_ids = [
        "h_NextMonth",
        "h_IB_NextMonth",
        "h_IMG_NextMonth",
        "NextMonth",
    ]

    for candidate_id in candidate_ids:
        link = soup.find(
            id=candidate_id
        )

        if link and link.get("href"):
            target, argument = (
                parse_do_postback(
                    link["href"]
                )
            )

            if target:
                return target, argument

    # Fall back to searching links for "next".
    for link in soup.find_all("a"):
        text = link.get_text(
            " ",
            strip=True,
        ).lower()

        href = link.get("href", "")

        if (
            "next" in text
            or "nextmonth" in href.lower()
        ):
            target, argument = (
                parse_do_postback(href)
            )

            if target:
                return target, argument

    return None, None


def fetch_and_sync():
    trmnl_url = os.environ.get(
        "TRMNL_WEBHOOK_URL"
    )

    if not trmnl_url:
        print(
            "CRITICAL ERROR: "
            "TRMNL_WEBHOOK_URL environment "
            "variable is missing!"
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
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            ),
            "Origin": (
                "https://paypams.com"
            ),
            "Referer": BASE_URL,
        }
    )

    try:
        # ---------------------------------------------------------
        # 1. Initial GET
        # ---------------------------------------------------------
        print(
            f"Loading {BASE_URL} ..."
        )

        res = session.get(
            BASE_URL,
            timeout=30,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        print(
            f"Response status: "
            f"{res.status_code}"
        )

        print(
            f"Final URL after redirects: "
            f"{res.url}"
        )

        title_el = soup.find("title")

        print(
            "Page title: "
            + (
                title_el.get_text(
                    strip=True
                )
                if title_el
                else "(none)"
            )
        )

        print_selects(
            soup,
            "Select elements on initial page",
        )

        # ---------------------------------------------------------
        # 2. Select Maine / ME
        # ---------------------------------------------------------
        soup, res = select_state(
            session,
            soup,
            STATE_NAME,
        )

        # ---------------------------------------------------------
        # 3. Select Geiger
        # ---------------------------------------------------------
        soup, res, school_value = (
            select_school(
                session,
                soup,
                SCHOOL_NAME,
            )
        )

        # ---------------------------------------------------------
        # 4. Select Lunch
        # ---------------------------------------------------------
        menu_soup, res, meal_value = (
            select_meal_type(
                session,
                soup,
                school_value,
                MEAL_TYPE_NAME,
            )
        )

        # ---------------------------------------------------------
        # 5. Parse current month
        # ---------------------------------------------------------
        all_menu_items = (
            parse_calendar_month(
                menu_soup
            )
        )

        print(
            f"Parsed "
            f"{len(all_menu_items)} items "
            "from current month."
        )

        # ---------------------------------------------------------
        # 6. Try to advance to next month
        # ---------------------------------------------------------
        next_target, next_argument = (
            find_next_month_postback(
                menu_soup
            )
        )

        if next_target:
            print(
                "Next month postback found:"
            )

            print(
                f"  target={next_target!r}"
            )

            print(
                f"  argument="
                f"{next_argument!r}"
            )

            overrides = {
                "__EVENTTARGET": next_target,
                "__EVENTARGUMENT": (
                    next_argument or ""
                ),
            }

            school_select = find_select(
                menu_soup,
                "h_DD_Schools",
            )

            if school_select is not None:
                field_name = (
                    school_select.get(
                        "name"
                    )
                )

                if field_name:
                    overrides[
                        field_name
                    ] = school_value

            meal_select = find_select(
                menu_soup,
                "h_DD_MealTypes",
            )

            if meal_select is not None:
                field_name = (
                    meal_select.get(
                        "name"
                    )
                )

                if field_name:
                    overrides[
                        field_name
                    ] = meal_value

            next_soup, res = post_step(
                session,
                BASE_URL,
                menu_soup,
                overrides,
                description=(
                    "advance to next month"
                ),
            )

            next_items = (
                parse_calendar_month(
                    next_soup
                )
            )

            print(
                f"Parsed "
                f"{len(next_items)} items "
                "from next month."
            )

            all_menu_items.extend(
                next_items
            )

        else:
            print(
                "WARNING: Could not find "
                "a next-month postback."
            )

        # ---------------------------------------------------------
        # 7. Remove duplicate dates
        # ---------------------------------------------------------
        unique_items = {}

        for item in all_menu_items:
            unique_items[
                item["date"]
            ] = item

        all_menu_items = list(
            unique_items.values()
        )

        all_menu_items.sort(
            key=lambda item: item["date"]
        )

        # ---------------------------------------------------------
        # 8. Only keep today's and future menus
        # ---------------------------------------------------------
        today = datetime.date.today()

        upcoming_items = []

        for item in all_menu_items:
            try:
                item_date = (
                    datetime.datetime.strptime(
                        item["date"],
                        "%Y-%m-%d",
                    ).date()
                )
            except ValueError:
                continue

            if item_date >= today:
                upcoming_items.append(
                    item
                )

        print(
            f"Found "
            f"{len(upcoming_items)} "
            "upcoming menu items."
        )

        for item in upcoming_items:
            output = (
                f"  {item['date']}: "
                f"{item['main']}"
            )

            if item["sides"]:
                output += (
                    f" | {item['sides']}"
                )

            print(output)

        # ---------------------------------------------------------
        # 9. Push to TRMNL
        # ---------------------------------------------------------
        payload = {
            "merge_variables": {
                "menu_items": (
                    upcoming_items
                )
            }
        }

        print(
            f"Pushing "
            f"{len(upcoming_items)} "
            "upcoming menu items "
            "to TRMNL..."
        )

        push_response = requests.post(
            trmnl_url,
            json=payload,
            headers={
                "Content-Type":
                    "application/json"
            },
            timeout=30,
        )

        print(
            "TRMNL response status: "
            f"{push_response.status_code}"
        )

        if push_response.status_code in (
            200,
            201,
            202,
            204,
        ):
            print(
                "SUCCESS: "
                "menu synchronized."
            )
        else:
            print(
                "WARNING: TRMNL rejected "
                "the push."
            )

            print(
                push_response.text[:1000]
            )

            sys.exit(1)

    except requests.RequestException as err:
        print(
            f"CRITICAL NETWORK ERROR: {err}"
        )
        sys.exit(1)

    except Exception as err:
        print(
            f"CRITICAL PARSER ERROR: {err}"
        )
        sys.exit(1)


if __name__ == "__main__":
    fetch_and_sync()
