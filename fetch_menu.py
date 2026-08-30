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
SCHOOL_NAME = "Geiger Elementary School"
MEAL_NAME = "Lunch"
OUT_DIR = Path("paypams_me_debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved:", path)


def parse_html(text):
    return BeautifulSoup(text, "html.parser")


def form_fields(soup):
    form = soup.find("form")
    if not form:
        raise RuntimeError("PayPAMS form not found")

    data = {}
    for tag in form.find_all(["input", "select", "textarea"]):
        name = tag.get("name")
        if not name:
            continue

        if tag.name == "select":
            selected = tag.find("option", selected=True)
            if selected is None:
                selected = tag.find("option")
            data[name] = selected.get("value", "") if selected else ""
            continue

        if tag.name == "textarea":
            data[name] = tag.text or ""
            continue

        input_type = (tag.get("type") or "text").lower()
        if input_type in ("submit", "button", "image", "reset"):
            continue
        if input_type in ("checkbox", "radio") and not tag.has_attr("checked"):
            continue
        data[name] = tag.get("value", "")

    return data


def post_form(session, soup, overrides):
    data = form_fields(soup)
    data.update(overrides)
    response = session.post(BASE_URL, data=data, timeout=30)
    response.raise_for_status()
    return response, parse_html(response.text)


def option_value(soup, select_id, wanted):
    select = soup.find("select", id=select_id)
    if not select:
        return None, []

    wanted = wanted.lower()
    options = []
    exact = None
    contains = None

    for option in select.find_all("option"):
        text = re.sub(r"\s+", " ", option.get_text(" ", strip=True))
        value = option.get("value", "")
        options.append((text, value))
        if text.lower() == wanted and exact is None:
            exact = value
        if wanted in text.lower() and contains is None:
            contains = value

    return exact if exact is not None else contains, options


def print_options(title, options):
    print(title)
    for text, value in options:
        print("  {} -> {}".format(repr(text), repr(value)))


def postback_target(href):
    if not href:
        return None, None

    patterns = [
        r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",
        r'WebForm_PostBackOptions\(\s*["\']([^"\']*)["\']\s*,\s*["\']([^"\']*)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, href, flags=re.I)
        if match:
            return match.group(1), match.group(2)
    return None, None


def select_state(session, soup):
    value, options = option_value(soup, "h_UC_State:h_DD_State", STATE)
    if value is None:
        print_options("State options:", options)
        raise RuntimeError("Maine was not found in the state selector")

    print("Selecting Maine:", value)
    response, new_soup = post_form(
        session,
        soup,
        {
            "h_UC_State:h_DD_State": value,
            "h_BTN_Submit": "Submit",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        },
    )
    save_text("02_after_ME_post.html", response.text)
    return new_soup


def select_district(session, soup):
    target = None
    argument = ""

    for link in soup.find_all("a"):
        text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        if DISTRICT_NAME.lower() in text.lower():
            target, argument = postback_target(link.get("href", ""))
            print("District link:", text)
            print("District postback target:", target)
            print("District postback argument:", argument)
            break

    if not target:
        raise RuntimeError("Lewiston Public Schools postback link was not found")

    response, new_soup = post_form(
        session,
        soup,
        {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": argument or "",
        },
    )
    save_text("03_after_Lewiston_post.html", response.text)
    return new_soup


def select_school_and_lunch(session, soup):
    school_value, school_options = option_value(soup, "h_DD_Schools", SCHOOL_NAME)
    if school_value is None:
        print_options("School options:", school_options)
        raise RuntimeError("Geiger Elementary School was not found")

    print("Selected school:", SCHOOL_NAME)
    print("School value:", school_value)

    meal_value, meal_options = option_value(soup, "h_DD_MealTypes", MEAL_NAME)
    if meal_value is None:
        print_options("Meal options:", meal_options)
        raise RuntimeError("Lunch was not found")

    print("Selected meal:", MEAL_NAME)
    print("Meal value:", meal_value)

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
    save_text("04_after_Geiger_Lunch_post.html", response.text)
    return new_soup, school_value, meal_value


def calendar_month(soup):
    today = datetime.date.today()
    year = today.year
    month = today.month

    label = soup.find(id="h_LBL_MonthYear")
    if label:
        text = re.sub(r"\s+", " ", label.get_text(" ", strip=True))
        match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", text, flags=re.I)
        if match:
            month = MONTHS[match.group(1).lower()]
            year = int(match.group(2))

    return year, month


def parse_calendar(soup):
    table = soup.find("table", class_="menucalendar")
    if table is None:
        return []

    year, month = calendar_month(soup)
    items = []

    for cell in table.find_all("td"):
        day = cell.find("span", class_="label_menuday")
        if day is None:
            continue
        day_text = day.get_text(" ", strip=True)
        if not day_text.isdigit():
            continue

        try:
            date_value = datetime.date(year, month, int(day_text))
        except ValueError:
            continue

        names = []

        for element in cell.select("span.uncheckedNC"):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            text = re.sub(r"^[\u2713\u2714]\s*", "", text).strip()
            if text and text not in names:
                names.append(text)

        if not names:
            for element in cell.find_all("a"):
                text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
                if not text or text.isdigit():
                    continue
                if text.lower() in ("previous", "next", "next month", "previous month"):
                    continue
                if text not in names:
                    names.append(text)

        if not names:
            continue

        items.append({
            "date": date_value.isoformat(),
            "main": names[0],
            "sides": ", ".join(names[1:]),
        })

    return items


def next_month(session, soup, school_value, meal_value):
    candidates = []
    for link in soup.find_all("a"):
        link_id = str(link.get("id", ""))
        text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        href = link.get("href", "")
        combined = (link_id + " " + text + " " + href).lower()
        if "nextmonth" in combined or ("next" in combined and "month" in combined):
            candidates.append(link)

    for link in candidates:
        target, argument = postback_target(link.get("href", ""))
        if target:
            response, new_soup = post_form(
                session,
                soup,
                {
                    "__EVENTTARGET": target,
                    "__EVENTARGUMENT": argument or "",
                    "h_DD_Schools": school_value,
                    "h_DD_MealTypes": meal_value,
                },
            )
            save_text("05_next_month.html", response.text)
            return new_soup

    return None


def main():
    webhook = os.environ.get("TRMNL_WEBHOOK_URL")
    if not webhook:
        print("CRITICAL ERROR: TRMNL_WEBHOOK_URL is not set")
        return 1

    session = requests.Session()
    session.headers.update(HEADERS)

    print("Loading PayPAMS:", BASE_URL)
    response = session.get(BASE_URL, timeout=30)
    response.raise_for_status()
    save_text("01_initial.html", response.text)
    soup = parse_html(response.text)

    print("Step 1: select Maine")
    soup = select_state(session, soup)

    print("Step 2: select Lewiston")
    soup = select_district(session, soup)

    print("Step 3: select Geiger and Lunch")
    soup, school_value, meal_value = select_school_and_lunch(session, soup)

    print("Step 4: parse current month")
    items = parse_calendar(soup)
    print("Current month items:", len(items))

    next_soup = next_month(session, soup, school_value, meal_value)
    if next_soup is not None:
        next_items = parse_calendar(next_soup)
        print("Next month items:", len(next_items))
        known = {(x["date"], x["main"], x["sides"]) for x in items}
        for item in next_items:
            key = (item["date"], item["main"], item["sides"])
            if key not in known:
                items.append(item)

    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=14)
    upcoming = []
    for item in items:
        try:
            item_date = datetime.date.fromisoformat(item["date"])
        except ValueError:
            continue
        if today <= item_date <= end_date:
            upcoming.append(item)

    upcoming.sort(key=lambda x: x["date"])
    save_json("trmnl_payload.json", {"merge_variables": {"menu_items": upcoming}})

    print("Upcoming lunches:")
    for item in upcoming:
        print("{} | {} | {}".format(item["date"], item["main"], item["sides"]))

    if not upcoming:
        print("ERROR: zero upcoming lunches extracted; TRMNL will not be overwritten")
        return 2

    payload = {"merge_variables": {"menu_items": upcoming}}
    push = session.post(webhook, json=payload, timeout=30)
    print("TRMNL status:", push.status_code)
    print(push.text[:500])
    push.raise_for_status()

    print("SUCCESS: sent {} lunches to TRMNL".format(len(upcoming)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
