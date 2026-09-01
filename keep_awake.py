"""
ปลุก Streamlit Community Cloud ไม่ให้หลับ
ใช้เบราว์เซอร์จริง (Playwright) เข้าไปเยี่ยมแอป เพราะ ping ธรรมดาปลุกไม่ได้
"""
import os
from playwright.sync_api import sync_playwright

URL = os.environ.get(
    "APP_URL",
    "https://fb-news-translator-pkxqszjeknvdwrldfax3bz.streamlit.app/",
)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        print("→ กำลังเข้า:", URL)
        page.goto(URL, wait_until="networkidle", timeout=120000)
        try:
            btn = page.get_by_text("get this app back up", exact=False)
            if btn.count() > 0:
                print("→ เจอปุ่มปลุกแอป กำลังกด...")
                btn.first.click()
                page.wait_for_timeout(60000)
        except Exception as e:
            print("ไม่มีปุ่มปลุก (แอปน่าจะตื่นอยู่แล้ว):", e)
        page.wait_for_timeout(15000)
        print("✓ เยี่ยมแอปเรียบร้อย")
        browser.close()

if __name__ == "__main__":
    main()
