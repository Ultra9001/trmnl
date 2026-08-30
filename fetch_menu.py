import os
import re
import sys
import datetime
import requests
from bs4 import BeautifulSoup

MONTHS_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

BASE_URL = "https://paypams.com/TN_Menus.aspx"
SCHOOL_NAME = "Geiger"      # matched against dropdown option text, case-insensitive
MEAL_TYPE_NAME = "Lunch"    # matched against dropdown option text, case-insensitive


def extract_form_fields(soup):
    """
    Harvest the CURRENT value of every form field on the page (inputs, selects,
    textareas). ASP.NET WebForms postbacks generally expect the entire form
    state echoed back on every request.
    """
    fields = {}
    for tag in soup.find_all(["input", "select", "textarea"]):
        name = tag.get("name")
        if not name:
            continue

        if tag.name == "select":
            selected = tag.find("option", selected=True) or tag.find("option")
            fields[name] = selected.get("value", selected.get_text(strip=True)) if selected else ""
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
    Extract (event_target, event_argument) from either postback style:
      javascript:__doPostBack('target','argument')
      javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions("target","argument",...))
    Returns (None, None) if neither pattern matches.
    """
    if not href:
        return None, None
    m = re.search(r"__doPostBack\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)", href)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r'WebForm_PostBackOptions\(\s*"([^"]*)"\s*,\s*"([^"]*)"', href)
    if m:
        return m.group(1), m.group(2)
    return None, None


def find_select_value(soup, select_id, option_text_contains):
    """Find a <select>'s option whose visible text contains a substring, case-insensitive."""
    select_el = soup.find("select", id=select_id)
    if not select_el:
        return None, []
    all_options = []
    match_value = None
    for opt in select_el.find_all("option"):
        text = opt.get_text(strip=True)
        value = opt.get("value", "")
        all_options.append((text, value))
        if match_value is None and option_text_contains.lower() in text.lower():
            match_value = value
    return match_value, all_options


def post_step(session, url, soup, overrides):
    payload = extract_form_fields(soup)
    payload.update(overrides)
    res = session.post(url, data=payload)
    return BeautifulSoup(res.text, "html.parser"), res


def parse_calendar_month(soup):
    """Parse the menucalendar table into [{date, main, sides}, ...]."""
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
                name = item_el.get_text(strip=True).lstrip("\u2713").strip()
                if name:
                    names.append(name)

            if not names:
                continue  # date shown but nothing posted (e.g. no school that day)

            try:
                computed_date = datetime.date(target_year, target_month, day_num)
            except ValueError:
                continue

            items.append({
                "date": computed_date.strftime("%Y-%m-%d"),
                "main": names[0],
                "sides": ", ".join(names[1:]),
            })
    return items


def fetch_and_sync():
    trmnl_url = os.environ.get("TRMNL_WEBHOOK_URL")
    if not trmnl_url:
        print("CRITICAL ERROR: TRMNL_WEBHOOK_URL environment variable is missing!")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://paypams.com",
        "Referer": "https://paypams.com",
    })

    try:
        print(f"Loading {BASE_URL} ...")
        res = session.get(BASE_URL)
        soup = BeautifulSoup(res.text, "html.parser")

        print(f"Response status: {res.status_code}")
        print(f"Final URL after redirects: {res.url}")
        title_el = soup.find("title")
        print(f"Page title: {title_el.get_text(strip=True) if title_el else '(none)'}")

        all_selects = soup.find_all("select")
        print(f"Found {len(all_selects)} <select> elements on the page:")
        for sel in all_selects:
            print(f"  id={sel.get('id')!r} name={sel.get('name')!r} option_count={len(sel.find_all('option'))}")

        if not all_selects:
            print("----- First 3000 chars of response body -----")
            print(res.text[:3000])
            print("----- End snippet -----")

        school_value, school_options = find_select_value(soup, "h_DD_Schools", SCHOOL_NAME)
        print("Schools seen in h_DD_Schools dropdown:")
        for text, value in school_options:
            print(f"  {text!r} -> value={value!r}")

        if not school_value:
            print(f"CRITICAL ERROR: no option containing {SCHOOL_NAME!r} found in the school "
                  f"dropdown. This runner's IP is very likely being geolocated to a different "
                  f"default district than Lewiston. See the school list printed above.")
            sys.exit(1)

        print(f"Selecting school (value={school_value})...")
        soup, res = post_step(session, BASE_URL, soup, {
            "__EVENTTARGET": "h_DD_Schools",
            "__EVENTARGUMENT": "",
            "h_DD_Schools": school_value,
        })

        meal_value, meal_options = find_select_value(soup, "h_DD_MealTypes", MEAL_TYPE_NAME)
        if not meal_value:
            print("Meal types seen in h_DD_MealTypes dropdown:")
            for text, value in meal_options:
                print(f"  {text!r} -> value={value!r}")
            print(f"CRITICAL ERROR: no option containing {MEAL_TYPE_NAME!r} found in the meal type dropdown.")
            sys.exit(1)

        print(f"Selecting meal type (value={meal_value})...")
        current_month_soup, res = post_step(session, BASE_URL, soup, {
            "__EVENTTARGET": "h_DD_MealTypes",
            "__EVENTARGUMENT": "",
            "h_DD_Schools": school_value,
            "h_DD_MealTypes": meal_value,
        })

        all_menu_items = parse_calendar_month(current_month_soup)
        print(f"Parsed {len(all_menu_items)} items from the current month view.")

        print("Advancing to next month...")
        next_link = current_month_soup.find("a", id="h_NextMonth")
        event_target, event_argument = (None, None)
        if next_link and next_link.get("href"):
            event_target, event_argument = parse_do_postback(next_link["href"])

        if event_target:
            next_month_soup, res = post_step(session, BASE_URL, current_month_soup, {
                "__EVENTTARGET": event_target,
                "__EVENTARGUMENT": event_argument or "",
                "h_DD_Schools": school_value,
                "h_DD_MealTypes": meal_value,
            })
            next_items = parse_calendar_month(next_month_soup)
            print(f"Parsed {len(next_items)} items from the next month view.")

            if all_menu_items and next_items and all_menu_items[0]["date"][:7] == next_items[0]["date"][:7]:
                print("WARNING: next-month page appears identical to current month - "
                      "the postback likely did not advance.")

            all_menu_items.extend(next_items)
        else:
            print("WARNING: could not find/parse the 'Next Month' link (id='h_NextMonth'); "
                  "only the current month's items will be pushed.")

        today_str = datetime.date.today().strftime("%Y-%m-%d")
        upcoming_items = [item for item in all_menu_items if item["date"] >= today_str]
        upcoming_items.sort(key=lambda x: x["date"])

        trmnl_payload = {"merge_variables": {"menu_items": upcoming_items}}

        print(f"Pushing {len(upcoming_items)} upcoming menu items to TRMNL...")
        push_response = requests.post(trmnl_url, json=trmnl_payload, headers={"Content-Type": "application/json"})

        if push_response.status_code in (200, 202):
            print("SUCCESS: menu synchronized.")
        else:
            print(f"WARNING: TRMNL rejected the push - status {push_response.status_code}")
            print(push_response.text[:500])

    except Exception as err:
        print(f"CRITICAL PARSER ERROR: {err}")
        sys.exit(1)


if __name__ == "__main__":
    fetch_and_sync()
