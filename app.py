import streamlit as st
from apify_client import ApifyClient
from google import genai
import requests
from bs4 import BeautifulSoup
import re

# ตั้งค่าหน้าตาของเว็บ
st.set_page_config(page_title="AI เรียบเรียงข่าวสารอัจฉริยะ", page_icon="📰", layout="centered")

st.title("📰 ระบบดึงและเรียบเรียงข่าวสารอัจฉริยะ")
st.write("วางลิงก์ข่าวสารจาก **Facebook, X (Twitter) หรือเว็บไซต์ข่าวทั่วไป** เพื่อดึงเนื้อหามาเรียบเรียงใหม่ด้วย Gemini AI")

# ดึง API Key จากระบบ Secrets หลังบ้าน
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
apify_token = st.secrets.get("APIFY_TOKEN", "")

# ช่องกรอกลิงก์บนหน้าเว็บ
url = st.text_input("🔗 วางลิงก์ข่าวสารที่นี่:", placeholder="https://... (รองรับ Facebook, X, และเว็บข่าวทั่วไป)")

def scrape_content(url_link, token):
    url_lower = url_link.lower()
    
    # 1. กรณีเป็น X (Twitter) - ใช้ระบบดึงตรงความเร็วสูง
    if "x.com" in url_lower or "twitter.com" in url_lower:
        match = re.search(r'(?:twitter|x)\.com/([^/]+)/status/(\d+)', url_link)
        if match:
            user, tweet_id = match.groups()
            vx_api_url = f"https://api.vxtwitter.com/{user}/status/{tweet_id}"
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(vx_api_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    tweet_text = data.get("text", "")
                    user_name = data.get("user_name", "")
                    if tweet_text:
                        full_content = f"โพสต์โดย {user_name}:\n{tweet_text}"
                        return full_content, "X (Twitter)"
            except Exception as e:
                pass
        
        # สำรองกรณีดึงตรงไม่ได้ ให้ลอง Apify
        apify_client = ApifyClient(token)
        run_input = {"tweetURLs": [url_link], "startUrls": [url_link], "maxItems": 1}
        run = apify_client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
        
        extracted_text = ""
        for item in apify_client.dataset(dataset_id).iterate_items():
            text_content = item.get("text") or item.get("fullText") or item.get("full_text") or ""
            if text_content:
                extracted_text += text_content + "\n"
        return extracted_text, "X (Twitter)"

    # 2. กรณีเป็น Facebook
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        apify_client = ApifyClient(token)
        run_input = {"startUrls": [{"url": url_link}], "resultsLimit": 1}
        run = apify_client.actor("apify/facebook-posts-scraper").call(run_input=run_input)
        dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
        
        extracted_text = ""
        for item in apify_client.dataset(dataset_id).iterate_items():
            text_content = item.get("text") or item.get("postText") or item.get("caption") or ""
            if text_content:
                extracted_text += text_content + "\n"
        return extracted_text, "Facebook"

    # 3. กรณีเป็นเว็บไซต์ข่าวทั่วไป
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url_link, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        
        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form"]):
            element.decompose()
        
        paragraphs = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 20]
        extracted_text = "\n".join(paragraphs)
        return extracted_text, "เว็บไซต์ข่าวทั่วไป"

# ปุ่มกดสั่งทำงาน
if st.button("🚀 เริ่มเรียบเรียงข่าว", type="primary"):
    if not url:
        st.warning("กรุณาวางลิงก์ข่าวสารก่อนครับ")
    elif not gemini_api_key:
        st.error("ไม่พบคีย์ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud")
    else:
        with st.spinner("กำลังดึงข้อมูลและเรียบเรียงข่าวใหม่..."):
            try:
                raw_text, source_type = scrape_content(url, apify_token)

                if not raw_text or not raw_text.strip():
                    st.error(f"ไม่สามารถดึงข้อความจาก {source_type} ได้ กรุณาเช็กว่าลิงก์เปิดเป็นสาธารณะหรือไม่")
                else:
                    st.info(f"📍 ตรวจพบแหล่งที่มา: **{source_type}** (ดึงเนื้อหาสำเร็จ)")
                    
                    prompt = f"""
                    คุณคือ คอนเทนต์ครีเอเตอร์และนักข่าวมืออาชีพ 
                    หน้าที่ของคุณคือรับข่าวสารมา แล้ว "เขียนเรียบเรียงใหม่ทั้งหมดเป็นภาษาไทย" ด้วยสำนวนภาษาของคุณเอง 
                    ห้ามแปลตรงตัวแบบคำต่อคำ เพื่อป้องกันปัญหาลิขสิทธิ์และการก๊อปปี้งาน

                    รูปแบบการเขียนที่ต้องการ:
                    1. 🔥 **พาดหัวข่าว (Headline):** เขียนพาดหัวใหม่ให้น่าสนใจ
                    2. 📝 **เนื้อหาข่าวเรียบเรียงใหม่ (Body):** เล่าข่าวด้วยสำนวนใหม่ อ่านสนุก กระชับ เข้าใจง่าย
                    3. 📌 **สรุป 3 ประเด็นสำคัญ:** ทำเป็น Bullet points สั้นๆ
                    4. 🏷️ **Hashtag:** ใส่แฮชแท็กที่เกี่ยวข้อง 3-5 อัน

                    เนื้อหาข่าวต้นฉบับ:
                    {raw_text}
                    """

                    gemini_client = genai.Client(api_key=gemini_api_key)
                    response = gemini_client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=prompt
                    )

                    st.success("✨ เรียบเรียงข่าวสำเร็จ!")
                    st.markdown("---")
                    st.markdown(response.text)

            except Exception as e:
                st.error(f"เกิดข้อผิดพลาด: {e}")
