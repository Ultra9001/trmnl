import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

def update_form_tokens(response_text, current_tokens):
    """Decodes ASP.NET pipe-delimited strings or extracts standard HTML input tags."""
    # 1. Check if the server returned a vertical-bar split AJAX payload chunk array
    if "|" in response_text:
        chunks = response_text.split("|")
        updated = current_tokens.copy()
        for i in range(len(chunks)):
            if chunks[i] == "__VIEWSTATE":
                updated["__VIEWSTATE"] = chunks[i+1]
            elif chunks[i] == "__VIEWSTATEGENERATOR":
                updated["__VIEWSTATEGENERATOR"] = chunks[i+1]
            elif chunks[i] == "__EVENTVALIDATION":
                updated["__EVENTVALIDATION"] = chunks[i+1]
        return updated
        
    # 2. Regular HTML fallback extractor loop container setup
    soup = BeautifulSoup(response_text, 'html.parser')
    return {
        "__VIEWSTATE": soup.find("input", {"id": "__VIEWSTATE"})["value"] if soup.find("input", {"id": "__VIEWSTATE"}) else current_tokens.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"] if soup.find("input", {"id": "__VIEWSTATEGENERATOR"}) else current_tokens.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": soup.find("input", {"id": "__EVENTVALIDATION"})["value"] if soup.find("input", {"id": "__EVENTVALIDATION"}) else current_tokens.get("__EVENTVALIDATION", ""),
        "__ASYNCPOST": "true"
    }

def parse_calendar_month(soup):
    """Helper to dynamically calculate correct calendar year/month and extract rows safely."""
    months_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    calendar_title = ""
    for el in soup.find_all(text=True):
        text_clean = el.strip().lower()
        for month_name in months_map:
            if month_name in text_clean and ("202" in text_clean):
                calendar_title = text_clean
                break
        if calendar_title:
            break

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
            
            computed_date = datetime.date(target_year, target_month, day_num)
            items.append({
                "date": computed_date.strftime("%Y-%m-%d"),
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "X-MicrosoftAjax": "Delta=true",
        "Origin": "https://paypams.com",
        "Referer": "https://paypams.com"
    })
    
    base_url = "https://paypams.com"

    try:
        res = session.get(base_url)
        tokens = update_form_tokens(res.text, {})

        # Step 1: Select State -> ME
        print("Submitting state verification matrix data...")
        payload = tokens.copy()
        payload.update({
            "ctl00$ScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$ddlState",
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlState",
            "ctl00$ContentPlaceHolder1$ddlState": "ME"
        })
        res = session.post(base_url, data=payload)
        tokens = update_form_tokens(res.text, tokens)

        # Step 2: Select District -> Lewiston Public Schools
        print("Submitting district routing locks...")
        payload = tokens.copy()
        payload.update({
            "ctl00$ScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$ddlDistrict",
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlDistrict",
            "ctl00$ContentPlaceHolder1$ddlState": "ME",
            "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools"
        })
        res = session.post(base_url, data=payload)
        tokens = update_form_tokens(res.text, tokens)

        # Step 3: Select School -> Geiger Elementary School
        print("Submitting campus specific form parameters...")
        payload = tokens.copy()
        payload.update({
            "ctl00$ScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$ddlSchool",
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlSchool",
            "ctl00$ContentPlaceHolder1$ddlState": "ME",
            "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools",
            "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School"
        })
        res = session.post(base_url, data=payload)
        tokens = update_form_tokens(res.text, tokens)

        # Step 4: Select Menu Type -> Lunch
        print("Locking target lunch calendar selection grid...")
        payload = tokens.copy()
        payload.update({
            "ctl00$ScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$ddlMenuType",
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlMenuType",
            "ctl00$ContentPlaceHolder1$ddlState": "ME",
            "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools",
            "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School",
            "ctl00$ContentPlaceHolder1$ddlMenuType": "Lunch"
        })
        res = session.post(base_url, data=payload)
        
        # When update panels return text data, reconstruct the clean markup context layout
        soup_text = res.text.split("|")[-1] if "|" in res.text else res.text
        current_month_soup = BeautifulSoup(soup_text if "<html" in soup_text or "<td" in soup_text else res.text, 'html.parser')
        tokens = update_form_tokens(res.text, tokens)

        # Parse Current August Data Block
        all_menu_items = parse_calendar_month(current_month_soup)

        # Step 5: Advance Calendar -> Next Month (September)
        print("Advancing pipeline forward to target next month grid...")
        next_month_btn = current_month_soup.find("a", text=">") or current_month_soup.find("a", string=">")
        if next_month_btn and next_month_btn.get("href"):
            href = next_month_btn["href"]
            target = href.split("'")[1] if "'" in href else "ctl00$ContentPlaceHolder1$Calendar1"
            
            payload = tokens.copy()
            payload.update({
                "ctl00$ScriptManager1": f"ctl00$ContentPlaceHolder1$UpdatePanel1|{target}",
                "__EVENTTARGET": target,
                "ctl00$ContentPlaceHolder1$ddlState": "ME",
                "ctl00$ContentPlaceHolder1$ddlDistrict": "Lewiston Public Schools",
                "ctl00$ContentPlaceHolder1$ddlSchool": "Geiger Elementary School",
                "ctl00$ContentPlaceHolder1$ddlMenuType": "Lunch"
            })
            res = session.post(base_url, data=payload)
            
            sept_text = res.text.split("|")[-1] if "|" in res.text else res.text
            next_month_soup = BeautifulSoup(sept_text if "<td" in sept_text else res.text, 'html.parser')
            all_menu_items.extend(parse_calendar_month(next_month_soup))

        # Filter timeline cleanly starting from today forward
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        upcoming_items = [item for item in all_menu_items if item["date"] >= today_str]
        upcoming_items.sort(key=lambda x: x["date"])

        trmnl_payload = {
            "merge_variables": {
                "menu_items": upcoming_items
            }
        }

        print(f"Pushing payload data array containing {len(upcoming_items)} live records straight to TRMNL...")
        push_response = requests.post(trmnl_url, json=trmnl_payload, headers={"Content-Type": "application/json"})
        
        if push_response.status_code == 200 or push_response.status_code == 202:
            print("SUCCESS: Dynamic school menu synchronized cleanly!")
        else:
            print(f"WARNING: Telemetry rejected with status code: {push_response.status_code}")

    except Exception as err:
        print(f"CRITICAL PARSER ERROR: {err}")
        sys.exit(1)

if __name__ == "__main__":
    fetch_and_sync()
