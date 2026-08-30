import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

def parse_calendar_month(soup):
    """Helper to find the active month/year header on PayPAMS and extract rows safely."""
    months_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    # 1. Dynamically locate the calendar month/year text header
    calendar_title = ""
    for el in soup.find_all(text=True):
        text_clean = el.strip().lower()
        for month_name in months_map:
            if month_name in text_clean and ("202" in text_clean):
                calendar_title = text_clean
                break
        if calendar_title:
            break

    # Extract target month and year integer values
    target_year = 2026
    target_month = datetime.date.today().month
    if calendar_title:
        parts = calendar_title.split()
        for p in parts:
            p_clean = p.strip("<>(), ")
            if p_clean in months_map:
                target_month = months_map[p_clean]
            elif p_clean.isdigit() and len(p_clean) == 4:
                target_year = int(p_clean)

    # 2. Iterate through rows in the calendar grid
    items = []
    day_cells = soup.find_all("td", class_="CalendarDay")
    for cell in day_cells:
        try:
            day_num_el = cell.find("span") or cell.find(style=lambda v: v and "font-weight:bold" in v.lower())
            if not day_num_el or not day_num_el.text.strip().isdigit():
                continue
            day_num = int(day_num_el.text.strip())
            
            food_paragraphs = [p.text.strip() for p in cell.find_all("p") if p.text.strip()]
            if not food_paragraphs:
                continue
            
            main_dish = food_paragraphs[0]
            sides_list = ", ".join(food_paragraphs[1:]) if len(food_paragraphs) > 1 else ""
            
            formatted_date = f"{target_year}-{target_month:02d}-{day_num:02d}"
            items.append({
                "date": formatted_date,
                "main": main_dish,
                "sides": sides_list
            })
        except Exception:
            continue
    return items

def fetch_and_sync():
    trmnl_url = os.environ.get("TRMNL_WEBHOOK_URL")
    if not trmnl_url:
        print("CRITICAL ERROR: TRMNL_WEBHOOK_URL environment variable is missing!")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    base_url = "https://paypams.com"

    try:
        res = session.get(base_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        def get_view_states(current_soup):
            return {
                "__VIEWSTATE": current_soup.find("input", {"id": "__VIEWSTATE"})["value"] if current_soup.find("input", {"id": "__VIEWSTATE"}) else "",
                "__VIEWSTATEGENERATOR": current_soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"] if current_soup.find("input", {"id": "__VIEWSTATEGENERATOR"}) else "",
                "__EVENTVALIDATION": current_soup.find("input", {"id": "__EVENTVALIDATION"})["value"] if current_soup.find("input", {"id": "__EVENTVALIDATION"}) else ""
            }

        # ME
        payload = get_view_states(soup)
        payload.update({"__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlState", "ctl00$ContentPlaceHolder1$ddlState": "ME"})
        res = session.post(base_url, data=payload)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Lewiston Public Schools
        payload = get_view_states(soup)
        payload.update({"__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlDistrict", "ctl00$ContentPlaceHolder1$ddlState": "ME", "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools"})
        res = session.post(base_url, data=payload)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Geiger Elementary School
        payload = get_view_states(soup)
        payload.update({"__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlSchool", "ctl00$ContentPlaceHolder1$ddlState": "ME", "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools", "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School"})
        res = session.post(base_url, data=payload)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Lunch (Default current month view)
        payload = get_view_states(soup)
        payload.update({"__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlMenuType", "ctl00$ContentPlaceHolder1$ddlState": "ME", "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools", "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School", "ctl00$ContentPlaceHolder1$ddlMenuType": "Lunch"})
        res = session.post(base_url, data=payload)
        current_month_soup = BeautifulSoup(res.text, 'html.parser')

        # Parse Current Month
        all_menu_items = parse_calendar_month(current_month_soup)

        # TRIGGER NEXT MONTH POSTBACK (To safely grab September items)
        print("Navigating to next month view on PayPAMS calendar matrix...")
        next_month_btn = current_month_soup.find("a", text=">") or current_month_soup.find("a", string=">")
        if next_month_btn and next_month_btn.get("href"):
            href = next_month_btn["href"]
            target = href.split("'")[1] if "'" in href else "ctl00$ContentPlaceHolder1$Calendar1"
            
            payload = get_view_states(current_month_soup)
            payload.update({
                "__EVENTTARGET": target,
                "ctl00$ContentPlaceHolder1$ddlState": "ME",
                "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools",
                "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School",
                "ctl00$ContentPlaceHolder1$ddlMenuType": "Lunch"
            })
            res = session.post(base_url, data=payload)
            next_month_soup = BeautifulSoup(res.text, 'html.parser')
            
            # Parse Next Month and combine arrays
            all_menu_items.extend(parse_calendar_month(next_month_soup))

        # Filter out past days and keep clean upcoming records
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        upcoming_items = [item for item in all_menu_items if item["date"] >= today_str]
        upcoming_items.sort(key=lambda x: x["date"])

        trmnl_payload = {
            "merge_variables": {
                "menu_items": upcoming_items
            }
        }

        print(f"Pushing synchronized array containing {len(upcoming_items)} upcoming entries to TRMNL...")
        push_response = requests.post(trmnl_url, json=trmnl_payload, headers={"Content-Type": "application/json"})
        
        # Fixed comparison expression syntax error here:
        if push_response.status_code == 200 or push_response.status_code == 202:
            print("SUCCESS: Full calendar rotation synchronized smoothly!")
        else:
            print(f"WARNING: Telemetry rejected with code: {push_response.status_code}")

    except Exception as err:
        print(f"CRITICAL COMPILER ERROR: {err}")
        sys.exit(1)

if __name__ == "__main__":
    fetch_and_sync()
