#!/usr/bin/env python3

import datetime
import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://paypams.com/TN_Menus.aspx"

STATE = "ME"
DISTRICT_NAME = "Lewiston Public Schools"
DISTRICT_EVENTTARGET = "_ctl7"

SCHOOL_SEARCH = "Geiger"
MEAL_SEARCH = "Lunch"

OUT_DIR = Path("paypams_me_debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)


STATE_SELECT_IDS = [
    "h_UC_State_h_DD_State",
    "h_UC_State:h_DD_State",
    "h_DD_State",
]

STATE_FIELD_NAMES = [
    "h_UC_State:h_DD_State",
    "h_UC_State$h_DD_State",
    "h_DD_State",
]


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
}


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


def save_text(name, text):
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    print("Saved:", path)


def save_json(name, data):
    path = OUT_DIR / name
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print("Saved:", path)


def soup_for(html):
    return BeautifulSoup(
        html,
        "html.parser",
    )


def normalize_space(text):
    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def get_form(soup):
    form = soup.find("form")

    if not form:
        raise RuntimeError(
            "PayPAMS form was not found"
        )

    return form


def form_fields(soup):
    form = get_form(soup)

    data = {}

    for tag in form.find_all(
        ["input", "select", "textarea"]
    ):

        name = tag.get("name")

        if not name:
            continue

        if tag.name == "select":

            selected = tag.find(
                "option",
                selected=True,
            )

            if selected is None:
                selected = tag.find(
                    "option"
                )

            if selected is not None:
                data[name] = selected.get(
                    "value",
                    "",
                )
            else:
                data[name] = ""

            continue

        if tag.name == "textarea":

            data[name] = tag.text or ""

            continue

        input_type = (
            tag.get("type") or "text"
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

            if not tag.has_attr("checked"):
                continue

        data[name] = tag.get(
            "value",
            "",
        )

    return data


def find_select(
    soup,
    ids,
):
    for select_id in ids:

        select = soup.find(
            "select",
            id=select_id,
        )

        if select is not None:
            return select

    return None


def option_value(
    soup,
    ids,
    wanted,
):
    select = find_select(
        soup,
        ids,
    )

    if select is None:
        return None, []

    options = []

    wanted_lower = wanted.lower()

    exact = None
    contains = None

    for option in select.find_all(
        "option"
    ):

        text = normalize_space(
            option.get_text(
                " ",
                strip=True,
            )
        )

        value = option.get(
            "value",
            "",
        )

        options.append(
            (
                text,
                value,
            )
        )

        if (
            text.lower() == wanted_lower
            and exact is None
        ):
            exact = value

        elif (
            wanted_lower in text.lower()
            and contains is None
        ):
            contains = value

    if exact is not None:
        return exact, options

    return contains, options


def print_options(
    label,
    options,
):
    print(label)

    if not options:
        print("  NONE")
        return

    for text, value in options:

        print(
            "  {} -> {}".format(
                repr(text),
                repr(value),
            )
        )


def find_state_field_name(soup):
    select = find_select(
        soup,
        STATE_SELECT_IDS,
    )

    if select is None:
        return None

    name = select.get("name")

    if name:
        return name

    fields = form_fields(
        soup
    )

    for candidate in STATE_FIELD_NAMES:

        if candidate in fields:
            return candidate

    return None


def find_submit_field(soup):
    form = get_form(
        soup
    )

    for tag in form.find_all(
        ["input", "button"]
    ):

        text = normalize_space(
            tag.get_text(
                " ",
                strip=True,
            )
        )

        value = normalize_space(
            tag.get(
                "value",
                "",
            )
        )

        combined = (
            text
            + " "
            + value
        ).lower()

        name = tag.get("name")

        if not name:
            continue

        if (
            "submit" in combined
            or value.lower() == "submit"
        ):

            return (
                name,
                tag.get(
                    "value",
                    "Submit",
                ),
            )

    return None, None


def post_form(
    session,
    soup,
    overrides,
):
    payload = form_fields(
        soup
    )

    payload.update(
        overrides
    )

    response = session.post(
        BASE_URL,
        data=payload,
        timeout=30,
    )

    response.raise_for_status()

    return (
        response,
        soup_for(
            response.text
        ),
    )


def parse_postback(
    href,
):
    if not href:
        return None, None

    href = href.replace(
        "\\'",
        "'",
    )

    href = href.replace(
        '\\"',
        '"',
    )

    patterns = [
        r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
        r"WebForm_PostBackOptions\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            href,
            flags=re.I,
        )

        if match:

            return (
                match.group(1),
                match.group(2),
            )

    return None, None


def select_state(
    session,
    soup,
):
    print()
    print(
        "Step 1: select Maine"
    )

    select = find_select(
        soup,
        STATE_SELECT_IDS,
    )

    if select is None:

        save_text(
            "state_selector_failure.html",
            str(soup),
        )

        raise RuntimeError(
            "Maine state selector was not found. "
            "Expected one of: "
            + ", ".join(
                STATE_SELECT_IDS
            )
        )

    print(
        "State selector id:",
        select.get("id"),
        "name:",
        select.get("name"),
    )

    value, options = option_value(
        soup,
        STATE_SELECT_IDS,
        STATE,
    )

    print_options(
        "State options:",
        options,
    )

    if value is None:

        for text, option_value_text in options:

            if text.lower() == "maine":

                value = option_value_text
                break

    if value is None:

        raise RuntimeError(
            "Maine was not found in the state selector"
        )

    state_field_name = (
        select.get("name")
        or find_state_field_name(
            soup
        )
    )

    if not state_field_name:

        raise RuntimeError(
            "Could not determine the POST field name "
            "for the state selector"
        )

    submit_name, submit_value = (
        find_submit_field(
            soup
        )
    )

    overrides = {
        state_field_name: value,
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
    }

    if submit_name:

        overrides[submit_name] = (
            submit_value
            or "Submit"
        )

        print(
            "Submit field:",
            submit_name,
            "=",
            repr(submit_value),
        )

    else:

        overrides["h_BTN_Submit"] = "Submit"

        print(
            "Submit field not discovered; "
            "using h_BTN_Submit fallback"
        )

    print(
        "Posting state:",
        state_field_name,
        "=",
        value,
    )

    response, new_soup = post_form(
        session,
        soup,
        overrides,
    )

    save_text(
        "02_after_ME_post.html",
        response.text,
    )

    return new_soup


def select_district(
    session,
    soup,
):
    print()
    print(
        "Step 2: select Lewiston"
    )

    district_link = None

    for link in soup.find_all(
        "a"
    ):

        text = normalize_space(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if (
            DISTRICT_NAME.lower()
            in text.lower()
        ):

            district_link = link
            break

    if district_link is None:

        save_text(
            "district_failure.html",
            str(soup),
        )

        raise RuntimeError(
            "Lewiston Public Schools link was "
            "not found after selecting Maine"
        )

    target, argument = parse_postback(
        district_link.get(
            "href",
            "",
        )
    )

    if not target:

        target = DISTRICT_EVENTTARGET
        argument = ""

    print(
        "District link:",
        normalize_space(
            district_link.get_text(
                " ",
                strip=True,
            )
        ),
    )

    print(
        "District postback target:",
        target,
    )

    print(
        "District postback argument:",
        argument or "",
    )

    response, new_soup = post_form(
        session,
        soup,
        {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": (
                argument or ""
            ),
        },
    )

    save_text(
        "03_after_Lewiston_post.html",
        response.text,
    )

    return new_soup


def select_school_and_lunch(
    session,
    soup,
):
    print()
    print(
        "Step 3: select Geiger and Lunch"
    )

    school_value, school_options = (
        option_value(
            soup,
            ["h_DD_Schools"],
            SCHOOL_SEARCH,
        )
    )

    print_options(
        "School options:",
        school_options,
    )

    if school_value is None:

        raise RuntimeError(
            "Geiger Elementary School was not found"
        )

    print(
        "Selected school:",
        SCHOOL_SEARCH,
        "value:",
        school_value,
    )

    meal_value, meal_options = (
        option_value(
            soup,
            ["h_DD_MealTypes"],
            MEAL_SEARCH,
        )
    )

    print_options(
        "Meal options:",
        meal_options,
    )

    if meal_value is None:

        raise RuntimeError(
            "Lunch was not found in the meal selector"
        )

    print(
        "Selected meal:",
        MEAL_SEARCH,
        "value:",
        meal_value,
    )

    response, new_soup = post_form(
        session,
        soup,
        {
            "h_DD_Schools": school_value,
            "h_DD_MealTypes": meal_value,
            "__EVENTTARGET": "h_DD_MealTypes",
            "__EVENTARGUMENT": "",
        },
    )

    save_text(
        "04_after_Geiger_Lunch_post.html",
        response.text,
    )

    return (
        new_soup,
        school_value,
        meal_value,
    )


def calendar_month(
    soup,
):
    today = datetime.date.today()

    year = today.year
    month = today.month

    label = soup.find(
        id="h_LBL_MonthYear"
    )

    if label:

        text = normalize_space(
            label.get_text(
                " ",
                strip=True,
            )
        )

        match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
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


def parse_calendar(
    soup,
):
    table = soup.find(
        "table",
        class_="menucalendar",
    )

    if table is None:

        print(
            "WARNING: table.menucalendar "
            "was not found"
        )

        return []

    header_year, header_month = calendar_month(
        soup
    )

    print(
        "Calendar month:",
        header_year,
        header_month,
    )

    items = []

    # PayPAMS pads the grid with days from the adjacent month so the
    # weeks line up (e.g. the September grid's first row shows Aug
    # 30/31 before Sept 1 starts). The header only tells us the month
    # for the *middle* of the grid, so we track which "phase" we're in
    # by watching for the day number decreasing between cells:
    #   -1 = trailing days of the PREVIOUS month (padding at the start)
    #    0 = the header month itself
    #   +1 = leading days of the NEXT month (padding at the end)
    phase = 0
    prev_day = None

    for cell in table.find_all(
        "td"
    ):

        day_span = cell.find(
            "span",
            class_="label_menuday",
        )

        if day_span is None:
            continue

        day_text = normalize_space(
            day_span.get_text(
                " ",
                strip=True,
            )
        )

        if not day_text.isdigit():
            continue

        day = int(
            day_text
        )

        if prev_day is None and day != 1:
            # Grid doesn't start on day 1 -> leading padding from the
            # previous month.
            phase = -1
        elif prev_day is not None and day < prev_day:
            # Day number dropped -> we've crossed a month boundary.
            phase += 1

        prev_day = day

        year, month = header_year, header_month
        month += phase

        if month < 1:
            month += 12
            year -= 1
        elif month > 12:
            month -= 12
            year += 1

        try:

            date_value = datetime.date(
                year,
                month,
                day,
            )

        except ValueError:

            continue

        names = []

        for element in cell.select(
            "span.uncheckedNC"
        ):

            text = normalize_space(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            text = re.sub(
                r"^[\u2713\u2714]\s*",
                "",
                text,
            ).strip()

            if text and text not in names:

                names.append(
                    text
                )

        if not names:

            for element in cell.find_all(
                "a"
            ):

                text = normalize_space(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not text:
                    continue

                if text.isdigit():
                    continue

                if text.lower() in (
                    "previous",
                    "next",
                    "next month",
                    "previous month",
                ):
                    continue

                if text not in names:

                    names.append(
                        text
                    )

        if not names:
            continue

        items.append(
            {
                "date": date_value.isoformat(),
                "main": names[0],
                "sides": ", ".join(
                    names[1:]
                ),
            }
        )

    return items


def find_next_month(
    soup,
):
    for link in soup.find_all(
        "a"
    ):

        link_id = str(
            link.get(
                "id",
                "",
            )
        ).lower()

        text = normalize_space(
            link.get_text(
                " ",
                strip=True,
            )
        ).lower()

        href = link.get(
            "href",
            "",
        )

        if (
            "nextmonth" not in link_id
            and not (
                "next" in text
                and "month" in text
            )
        ):
            continue

        target, argument = parse_postback(
            href
        )

        if target:

            return (
                target,
                argument or "",
            )

    return None, None


def main():

    webhook = os.environ.get(
        "TRMNL_WEBHOOK_URL"
    )

    if not webhook:

        print(
            "CRITICAL ERROR: "
            "TRMNL_WEBHOOK_URL is not set"
        )

        return 1

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:

        print(
            "Loading PayPAMS:",
            BASE_URL,
        )

        response = session.get(
            BASE_URL,
            timeout=30,
        )

        response.raise_for_status()

        print(
            "Initial response:",
            response.status_code,
        )

        save_text(
            "01_initial.html",
            response.text,
        )

        soup = soup_for(
            response.text
        )

        soup = select_state(
            session,
            soup,
        )

        soup = select_district(
            session,
            soup,
        )

        (
            soup,
            school_value,
            meal_value,
        ) = select_school_and_lunch(
            session,
            soup,
        )

        print()
        print(
            "Step 4: parse current month"
        )

        items = parse_calendar(
            soup
        )

        print(
            "Current month items:",
            len(items),
        )

        target, argument = find_next_month(
            soup
        )

        if target:

            print()
            print(
                "Step 5: fetch next month"
            )

            response, next_soup = post_form(
                session,
                soup,
                {
                    "__EVENTTARGET": target,
                    "__EVENTARGUMENT": argument,
                    "h_DD_Schools": school_value,
                    "h_DD_MealTypes": meal_value,
                },
            )

            save_text(
                "05_next_month.html",
                response.text,
            )

            next_items = parse_calendar(
                next_soup
            )

            print(
                "Next month items:",
                len(next_items),
            )

            known = {
                (
                    item["date"],
                    item["main"],
                    item["sides"],
                )
                for item in items
            }

            for item in next_items:

                key = (
                    item["date"],
                    item["main"],
                    item["sides"],
                )

                if key not in known:

                    items.append(
                        item
                    )

        else:

            print()
            print(
                "No next-month postback found."
            )

        today = datetime.date.today()

        end_date = (
            today
            + datetime.timedelta(
                days=14
            )
        )

        upcoming = []

        for item in items:

            try:

                item_date = datetime.date.fromisoformat(
                    item["date"]
                )

            except ValueError:

                continue

            if (
                today
                <= item_date
                <= end_date
            ):

                upcoming.append(
                    item
                )

        upcoming.sort(
            key=lambda item: item["date"]
        )

        print()
        print(
            "UPCOMING LUNCHES"
        )

        print(
            "-" * 72
        )

        if not upcoming:

            print(
                "NO UPCOMING MENU ITEMS FOUND"
            )

        else:

            for item in upcoming:

                print(
                    "{} | {} | {}".format(
                        item["date"],
                        item["main"],
                        item["sides"],
                    )
                )

        payload = {
            "merge_variables": {
                "menu_items": upcoming,
            }
        }

        save_json(
            "trmnl_payload.json",
            payload,
        )

        if not upcoming:

            print()
            print(
                "ERROR: zero lunches extracted."
            )

            print(
                "TRMNL will NOT be overwritten."
            )

            return 2

        print()
        print(
            "Sending {} lunches to TRMNL...".format(
                len(upcoming)
            )
        )

        push = requests.post(
            webhook,
            json=payload,
            headers={
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        print(
            "TRMNL status:",
            push.status_code,
        )

        if push.text:

            print(
                push.text[:1000]
            )

        push.raise_for_status()

        print()
        print(
            "SUCCESS"
        )

        print(
            "Sent {} lunches to TRMNL.".format(
                len(upcoming)
            )
        )

        return 0

    except requests.RequestException as exc:

        print()
        print(
            "HTTP ERROR:",
            exc,
        )

        return 1

    except Exception as exc:

        print()
        print(
            "CRITICAL PARSER ERROR:",
            exc,
        )

        return 1


if __name__ == "__main__":
    sys.exit(
        main()
    )
