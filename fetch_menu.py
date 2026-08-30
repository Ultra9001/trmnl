import re
import sys
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://paypams.com/TN_Menus.aspx"


def main():
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    print(f"Loading {BASE_URL} ...")

    response = session.get(
        BASE_URL,
        timeout=30,
    )

    response.raise_for_status()

    print(f"Status: {response.status_code}")
    print(f"Final URL: {response.url}")
    print()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    state = soup.find(
        "select",
        id="h_UC_State_h_DD_State",
    )

    if not state:
        print(
            "ERROR: State dropdown not found."
        )
        sys.exit(1)

    print("=" * 80)
    print("STATE DROPDOWN HTML")
    print("=" * 80)

    print(
        state.prettify()
    )

    print()
    print("=" * 80)
    print("STATE DROPDOWN ATTRIBUTES")
    print("=" * 80)

    for key, value in state.attrs.items():
        print(f"{key}: {value}")

    print()
    print("=" * 80)
    print("FORM HTML")
    print("=" * 80)

    form = state.find_parent("form")

    if form:
        print(
            form.prettify()[:30000]
        )
    else:
        print("No parent form found.")

    print()
    print("=" * 80)
    print("SCRIPTS CONTAINING STATE / SCHOOL REFERENCES")
    print("=" * 80)

    keywords = [
        "h_UC_State",
        "h_DD_Schools",
        "DD_State",
        "DD_Schools",
        "school",
        "state",
        "__doPostBack",
        "ajax",
        "jquery",
        "fetch(",
        "$.ajax",
        "$.post",
        "XMLHttpRequest",
        "WebMethod",
        "PageMethods",
    ]

    found_any = False

    for script_number, script in enumerate(
        soup.find_all("script"),
        start=1,
    ):
        text = script.get_text(
            "\n",
            strip=False,
        )

        lowered = text.lower()

        matching_keywords = [
            keyword
            for keyword in keywords
            if keyword.lower() in lowered
        ]

        if not matching_keywords:
            continue

        found_any = True

        print()
        print(
            f"--- SCRIPT #{script_number} ---"
        )

        print(
            "Matching keywords: "
            + ", ".join(matching_keywords)
        )

        print(
            text[:20000]
        )

    if not found_any:
        print(
            "No relevant inline scripts found."
        )

    print()
    print("=" * 80)
    print("ALL SCRIPT SRC URLs")
    print("=" * 80)

    for script in soup.find_all("script"):
        src = script.get("src")

        if src:
            print(src)

    print()
    print("=" * 80)
    print("RELEVANT HTML AROUND STATE DROPDOWN")
    print("=" * 80)

    html = response.text

    state_pos = html.find(
        "h_UC_State_h_DD_State"
    )

    if state_pos >= 0:
        start = max(
            0,
            state_pos - 10000,
        )

        end = min(
            len(html),
            state_pos + 20000,
        )

        print(
            html[start:end]
        )
    else:
        print(
            "State ID not found in raw HTML."
        )


if __name__ == "__main__":
    main()
