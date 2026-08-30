import os
import sys
import datetime
import requests

# --- Fill these in once (see linqconnect.com Network tab -> FamilyMenu request) ---
BUILDING_ID = "PASTE-YOUR-BUILDING-ID-HERE"
DISTRICT_ID = "PASTE-YOUR-DISTRICT-ID-HERE"
SERVING_SESSION = "Lunch"  # matches the ServingSession field in the API response
DAYS_AHEAD = 10            # how many days out to request/display


def fetch_menu_json():
    today = datetime.date.today()
    end = today + datetime.timedelta(days=DAYS_AHEAD)

    params = {
        "buildingId": BUILDING_ID,
        "districtId": DISTRICT_ID,
        "startDate": today.strftime("%m-%d-%Y"),
        "endDate": end.strftime("%m-%d-%Y"),
    }
    resp = requests.get("https://api.linqconnect.com/api/FamilyMenu", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_items(api_response):
    """
    Flattens the LINQ Connect response into the same simple shape the TRMNL
    template already expects: [{"date": "YYYY-MM-DD", "main": ..., "sides": ...}]
    """
    items = []
    sessions = api_response.get("FamilyMenuSessions") or []

    for session in sessions:
        if SERVING_SESSION.lower() not in (session.get("ServingSession") or "").lower():
            continue

        for plan in session.get("MenuPlans") or []:
            for day in plan.get("Days") or []:
                date_str = day.get("Date")
                if not date_str:
                    continue

                recipe_names = []
                for meal in day.get("MenuMeals") or []:
                    for category in meal.get("RecipeCategories") or []:
                        for recipe in category.get("Recipes") or []:
                            name = (recipe.get("RecipeName") or "").strip()
                            if name:
                                recipe_names.append(name)

                if not recipe_names:
                    continue  # no school / no menu posted that day

                # Parse whatever date format the API gives back (it's typically
                # an ISO-ish string like "2026-09-02T00:00:00").
                try:
                    parsed_date = datetime.datetime.fromisoformat(date_str.split("T")[0]).date()
                except ValueError:
                    continue

                items.append({
                    "date": parsed_date.strftime("%Y-%m-%d"),
                    "main": recipe_names[0],
                    "sides": ", ".join(recipe_names[1:]),
                })

    items.sort(key=lambda x: x["date"])
    return items


def push_to_trmnl(items):
    trmnl_url = os.environ.get("TRMNL_WEBHOOK_URL")
    if not trmnl_url:
        print("CRITICAL ERROR: TRMNL_WEBHOOK_URL environment variable is missing!")
        sys.exit(1)

    payload = {"merge_variables": {"menu_items": items}}
    resp = requests.post(trmnl_url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)

    if resp.status_code in (200, 202):
        print(f"SUCCESS: pushed {len(items)} menu items to TRMNL.")
    else:
        print(f"WARNING: TRMNL rejected the push - status {resp.status_code}")
        print(resp.text[:500])


def main():
    if "PASTE-YOUR" in BUILDING_ID or "PASTE-YOUR" in DISTRICT_ID:
        print("CRITICAL ERROR: set BUILDING_ID and DISTRICT_ID at the top of this file first.")
        sys.exit(1)

    data = fetch_menu_json()
    items = extract_items(data)
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    upcoming = [i for i in items if i["date"] >= today_str]
    push_to_trmnl(upcoming)


if __name__ == "__main__":
    main()
