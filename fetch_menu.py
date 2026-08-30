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
STATE_NAME = "Maine"


def extract_form_fields(soup):
    """
    Harvest the current value of every ASP.NET form field.

    ASP.NET WebForms postbacks generally expect the complete form state
    (__VIEWSTATE, __EVENTVALIDATION, selects, hidden fields, etc.) to be
    submitted with every request.
    """
    fields = {}

    for tag in soup.find_all(["input", "select", "textarea"]):
        name = tag.get("name")

        if not name:
            continue

        if tag.name == "select":
            selected = tag.find("option", selected=True)

            # If nothing is explicitly selected, use the first option.
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

            elif input_type in ("submit", "button", "image", "reset"):
                continue

            else:
                fields[name] = tag.get("value", "")

    return fields


def parse_do_postback(href):
    """
    Extract (event_target, event_argument) from common ASP.NET postback styles.

    Handles:
      javascript:__doPostBack('target','argument')
      javascript:WebForm_DoPostBackWithOptions(
          new WebForm_PostBackOptions("target","argument",...)
      )

    Returns:
        (None, None) if no postback target can be found.
    """
    if not href:
        return None, None

    # Normal __doPostBack(...)
    patterns = [
        r"__doPostBack\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)",
        r'__doPostBack\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)',
    ]

    for pattern in patterns:
        match = re.search(pattern, href)

        if match:
            return match.group(1), match.group(2)

    # WebForm_PostBackOptions(...)
    match = re.search(
        r'WebForm_PostBackOptions\(\s*"([^"]*)"\s*,\s*"([^"]*)"',
        href,
    )

    if match:
        return match.group(1), match.group(2)

    return None, None


def find_select(soup, select_id):
    """Return a select element by ID."""
    return soup.find("select", id=select_id)


def find_select_value(soup, select_id, option_text_contains):
    """
    Find a select option whose visible text contains the requested text,
    case-insensitively.

    Returns:
        (matching_value, all_options)
    """
    select_el = find_select(soup, select_id)

    if not select_el:
        return None, []

    all_options = []
    match_value = None

    for opt in select_el.find_all("option"):
        text = opt.get_text(strip=True)
        value = opt.get("value", "")

        all_options.append((text, value))

        if (
            match_value is None
            and option_text_contains.lower() in text.lower()
        ):
            match_value = value

    return match_value, all_options


def get_select_postback_target(select_el):
    """
    Try to determine the ASP.NET __EVENTTARGET for a select's onchange.

    The rendered HTML can use either:
      __doPostBack(...)
    or:
      WebForm_DoPostBackWithOptions(...)

    If no JavaScript target is present, fall back to the select's name,
    then its ID.
    """
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


def post_step(session, url, soup, overrides, description="postback"):
    """
    Perform an ASP.NET WebForms postback while preserving the current form
    state.
    """
    payload = extract_form_fields(soup)
    payload.update(overrides)

    print(f"POST {description}...")
    print(f"  event target: {payload.get('__EVENTTARGET', '')!r}")

    res = session.post(
        url,
        data=payload,
        timeout=30,
    )

    res.raise_for_status()

    print(f"  response status: {res.status_code}")
    print(f"  final URL: {res.url}")

    new_soup = BeautifulSoup(res.text, "html.parser")

    return new_soup, res


def print_selects(soup, heading="Select elements"):
    """Print select IDs/names/options for debugging."""
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
    """Print dropdown options."""
    if not options:
        print("  (none)")
        return

    for text, value in options:
        print(f"  {text!r} -> value={value!r}")


def parse_calendar_month(soup):
    """Parse the menu calendar into [{date, main, sides}, ...]."""
    month_year_el = soup.find("span", id="h_LBL_MonthYear")

    target_year = datetime.date.today().year
    target_month = datetime.date.today().month

    if month_year_el:
        parts = month_year_el.get_text(strip=True).split()

        if len(parts) == 2 and parts[0].lower() in MONTHS_MAP:
            target_month = MONTHS_MAP[parts[0].lower()]

            try:
                target_year = int(parts[1])
            except ValueError:
                pass

    items = []

    table = soup.find("table", class_="menucalendar")

    if not table:
        return items

    for row in table.find_all("tr"):
        for cell in row.find_all("td"):
            day_span = cell.find("span", class_="label_menuday")

            if not day_span:
                continue

            day_text = day_span.get_text(strip=True)

            if not day_text.isdigit():
                continue

            day_num = int(day_text)

            names = []

            for item_el in cell.find_all("span", class_="uncheckedNC"):
                name = (
                    item_el.get_text(strip=True)
                    .lstrip("\u2713")
                    .strip()
                )

                if name:
                    names.append(name)

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
                    "date": computed_date.strftime("%Y-%m-%d"),
                    "main": names[0],
                    "sides": ", ".join(names[1:]),
                }
            )

    return items


def select_state(session, soup, state_name):
    """
    Select the state.

    This is the important fix: PayPams initially renders the state dropdown
    but does not populate the school dropdown until the state selection
    causes an ASP.NET postback.
    """
    state_select = find_select(
        soup,
        "h_UC_State_h_DD_State",
    )

    if not state_select:
        raise RuntimeError(
            "Could not find the state dropdown "
            "'h_UC_State_h_DD_State'."
        )

    state_value, state_options = find_select_value(
        soup,
        "h_UC_State_h_DD_State",
        state_name,
    )

    print("States seen in h_UC_State_h_DD_State dropdown:")
    print_options(state_options)

    if not state_value:
        raise RuntimeError(
            f"Could not find state {state_name!r} in the state dropdown."
        )

    print(
        f"Selecting state {state_name!r} "
        f"(value={state_value!r})..."
    )

    # Prefer the actual ASP.NET postback target embedded in onchange.
    event_target = get_select_postback_target(state_select)

    if not event_target:
        event_target = (
            state_select.get("name")
            or state_select.get("id")
        )

    # ASP.NET normally uses the select's NAME as the posted form value.
    # The HTML observed from PayPams uses:
    #
    #   id   = h_UC_State_h_DD_State
    #   name = h_UC_State:h_DD_State
    #
    state_field_name = state_select.get("name")

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
        description=f"select state {state_name}",
    )

    print_selects(
        soup,
        "Select elements after state postback",
    )

    return soup, response


def select_school(session, soup, school_name):
    """Select the requested school after the state postback."""
    school_select = find_select(
        soup,
        "h_DD_Schools",
    )

    if not school_select:
        raise RuntimeError(
            "PayPams did not return the school dropdown "
            "'h_DD_Schools' after selecting the state."
        )

    school_value, school_options = find_select_value(
        soup,
        "h_DD_Schools",
        school_name,
    )

    print("Schools seen in h_DD_Schools dropdown:")
    print_options(school_options)

    if not school_value:
        raise RuntimeError(
            f"Could not find school {school_name!r} after selecting "
            f"{STATE_NAME!r}."
        )

    print(
        f"Selecting school {school_name!r} "
        f"(value={school_value!r})..."
    )

    event_target = get_select_postback_target(school_select)

    if not event_target:
        event_target = (
            school_select.get("name")
            or school_select.get("id")
        )

    school_field_name = school_select.get("name")

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
        description=f"select school {school_name}",
    )

    print_selects(
        soup,
        "Select elements after school postback",
    )

    return soup, response, school_value


def select_meal_type(session, soup, school_value, meal_type_name):
    """Select Lunch after the school dropdown has been processed."""
    meal_select = find_select(
        soup,
        "h_DD_MealTypes",
    )

    if not meal_select:
        raise RuntimeError(
            "PayPams did not return the meal type dropdown "
            "'h_DD_MealTypes' after selecting the school."
        )

    meal_value, meal_options = find_select_value(
        soup,
        "h_DD_MealTypes",
        meal_type_name,
    )

    print("Meal types seen in h_DD_MealTypes dropdown:")
    print_options(meal_options)

    if not meal_value:
        raise RuntimeError(
            f"Could not find meal type {meal_type_name!r}."
        )

    print(
        f"Selecting meal type {meal_type_name!r} "
        f"(value={meal_value!r})..."
    )

    event_target = get_select_postback_target(meal_select)

    if not event_target:
        event_target = (
            meal_select.get("name")
            or meal_select.get("id")
        )

    meal_field_name = meal_select.get("name")

    if not meal_field_name:
        raise RuntimeError(
            "Meal type dropdown has no name attribute."
        )

    overrides = {
        "__EVENTTARGET": event_target,
        "__EVENTARGUMENT": "",
        meal_field_name: meal_value,
    }

    # Keep the school selection explicitly in the postback.
    school_select = find_select(soup, "h_DD_Schools")

    if school_select is not None:
        school_field_name = school_select.get("name")

        if school_field_name:
            overrides[school_field_name] = school_value

    soup, response = post_step(
        session,
        BASE_URL,
        soup,
        overrides,
        description=f"select meal type {meal_type_name}",
    )

    return soup, response, meal_value


def fetch_and_sync():
    trmnl_url = os.environ.get("TRMNL_WEBHOOK_URL")

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
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://paypams.com",
            "Referer": BASE_URL,
        }
    )

    try:
        # ------------------------------------------------------------
        # 1. Initial GET
        # ------------------------------------------------------------
        print(f"Loading {BASE_URL} ...")

        res = session.get(
            BASE_URL,
            timeout=30,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        print(f"Response status: {res.status_code}")
        print(f"Final URL after redirects: {res.url}")

        title_el = soup.find("title")

        print(
            "Page title: "
            f"{title_el.get_text(strip=True) if title_el else '(none)'}"
        )

        print_selects(
            soup,
            "Select elements on initial page",
        )

        # ------------------------------------------------------------
        # 2. Select Maine FIRST
        #
        # This is the critical fix. The initial page does not contain
        # h_DD_Schools. Selecting the state causes PayPams to populate
        # the school dropdown.
        # ------------------------------------------------------------
        soup, res = select_state(
            session,
            soup,
            STATE_NAME,
        )

        # ------------------------------------------------------------
        # 3. Select Geiger
        # ------------------------------------------------------------
        soup, res, school_value = select_school(
            session,
            soup,
            SCHOOL_NAME,
        )

        # ------------------------------------------------------------
        # 4. Select Lunch
        # ------------------------------------------------------------
        current_month_soup, res, meal_value = select_meal_type(
            session,
            soup,
            school_value,
            MEAL_TYPE_NAME,
        )

        # ------------------------------------------------------------
        # 5. Parse current month
        # ------------------------------------------------------------
        all_menu_items = parse_calendar_month(
            current_month_soup
        )

        print(
            f"Parsed {len(all_menu_items)} items "
            "from the current month view."
        )

        # ------------------------------------------------------------
        # 6. Advance to next month
        # ------------------------------------------------------------
        print("Advancing to next month...")

        next_link = current_month_soup.find(
            "a",
            id="h_NextMonth",
        )

        event_target = None
        event_argument = None

        if next_link and next_link.get("href"):
            event_target, event_argument = parse_do_postback(
                next_link["href"]
            )

        if event_target:
            # Use the current form state from the current-month page.
            overrides = {
                "__EVENTTARGET": event_target,
                "__EVENTARGUMENT": event_argument or "",
            }

            # Explicitly preserve the school and meal selections.
            school_select = find_select(
                current_month_soup,
                "h_DD_Schools",
            )

            if school_select is not None:
                school_field_name = school_select.get("name")

                if school_field_name:
                    overrides[school_field_name] = school_value

            meal_select = find_select(
                current_month_soup,
                "h_DD_MealTypes",
            )

            if meal_select is not None:
                meal_field_name = meal_select.get("name")

                if meal_field_name:
                    overrides[meal_field_name] = meal_value

            next_month_soup, res = post_step(
                session,
                BASE_URL,
                current_month_soup,
                overrides,
                description="advance to next month",
            )

            next_items = parse_calendar_month(
                next_month_soup
            )

            print(
                f"Parsed {len(next_items)} items "
                "from the next month view."
            )

            if (
                all_menu_items
                and next_items
                and all_menu_items[0]["date"][:7]
                == next_items[0]["date"][:7]
            ):
                print(
                    "WARNING: next-month page appears identical "
                    "to current month - the postback likely did "
                    "not advance."
                )

            all_menu_items.extend(next_items)

        else:
            print(
                "WARNING: could not find/parse the "
                "'Next Month' link (id='h_NextMonth'); "
                "only the current month's items will be pushed."
            )

        # ------------------------------------------------------------
        # 7. Filter to today's and future menu items
        # ------------------------------------------------------------
        today_str = datetime.date.today().strftime(
            "%Y-%m-%d"
        )

        upcoming_items = [
            item
            for item in all_menu_items
            if item["date"] >= today_str
        ]

        upcoming_items.sort(
            key=lambda x: x["date"]
        )

        print(
            f"Found {len(upcoming_items)} upcoming menu items."
        )

        for item in upcoming_items:
            print(
                f"  {item['date']}: "
                f"{item['main']}"
                + (
                    f" | {item['sides']}"
                    if item["sides"]
                    else ""
                )
            )

        # ------------------------------------------------------------
        # 8. Push to TRMNL
        # ------------------------------------------------------------
        trmnl_payload = {
            "merge_variables": {
                "menu_items": upcoming_items
            }
        }

        print(
            f"Pushing {len(upcoming_items)} upcoming menu items "
            "to TRMNL..."
        )

        push_response = requests.post(
            trmnl_url,
            json=trmnl_payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=30,
        )

        if push_response.status_code in (200, 202):
            print("SUCCESS: menu synchronized.")
        else:
            print(
                "WARNING: TRMNL rejected the push - "
                f"status {push_response.status_code}"
            )
            print(push_response.text[:500])

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
