from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto("https://www.google.com")
    page.screenshot(path="google.png")

    print("Screenshot saved as google.png")

# input("Press Enter to close..." )

    browser.close()