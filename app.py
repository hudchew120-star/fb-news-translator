import json
import re

import streamlit as st
from apify_client import ApifyClient
from google import genai
import requests
from bs4 import BeautifulSoup
import streamlit.components.v1 as components

# ตั้งค่าหน้าตาของเว็บ
st.set_page_config(page_title="AI เรียบเรียงข่าวสารอัจฉริยะ", page_icon="📰", layout="centered")

st.title("📰 ระบบดึงและเรียบเรียงข่าวสารอัจฉริยะ")
st.write("วางลิงก์ข่าวสารจาก **Facebook, X (Twitter) หรือเว็บไซต์ข่าวทั่วไป** เพื่อดึงเนื้อหามาเรียบเรียงใหม่ด้วย Gemini AI")

# ดึง API Key จากระบบ Secrets หลังบ้าน
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
apify_token = st.secrets.get("APIFY_TOKEN", "")

# ---------- รับลิงก์ที่ส่งมาจากเว็บรวม (deep-link ?url=...) ----------
prefill_url = ""
try:
    prefill_url = st.query_params.get("url", "")
except Exception:
    qp = st.experimental_get_query_params()
    prefill_url = qp.get("url", [""])[0] if qp.get("url") else ""

# ช่องกรอกลิงก์บนหน้าเว็บ
url = st.text_input(
    "🔗 วางลิงก์ข่าวสารที่นี่:",
    value=prefill_url,
    placeholder="https://... (รองรับ Facebook, X, และเว็บข่าวทั่วไป)",
)

# ---------- เลือกประเภทข่าว (คุมโทนการเรียบเรียง) ----------
NEWS_STYLES = {
    "📰 ข่าวทั่วไป": (
        "เขียนแบบข่าวมาตรฐาน อ่านสนุก กระชับ เข้าใจง่าย เป็นกลาง น่าเชื่อถือ"
    ),
    "💸 ข่าวซื้อขาย / ตลาดนักเตะ": (
        "เขียนสไตล์ข่าวตลาดซื้อขายนักเตะ เน้นความชัดของ ใคร-ย้ายจากไหน-ไปไหน-ค่าตัว-สถานะดีล "
        "(ปิดดีล/ใกล้ปิด/สนใจ/ข่าวลือ) ใส่ตัวเลขค่าตัวและระยะสัญญาถ้ามี ใช้โทนกระชับเร้าใจแบบเพจข่าวลูกหนัง"
    ),
    "😂 ข่าวตลก / Gossip": (
        "เขียนสไตล์บันเทิง/แซว อ่านสนุก กวน ๆ มีอารมณ์ขัน เล่นมุก เหน็บเบา ๆ ได้ "
        "แต่ยังคงใจความข่าวจริงไว้ ไม่ใส่ร้ายหรือสร้างข้อมูลเท็จ"
    ),
}
news_style_label = st.selectbox("🎭 ประเภทข่าว (ปรับสำนวนการเขียน):", list(NEWS_STYLES.keys()))
style_instruction = NEWS_STYLES[news_style_label]


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
            except Exception:
                pass

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


def parse_ai_json(text):
    """ดึง JSON ออกจากคำตอบของ AI แบบทนทาน (เผื่อมี ```json ครอบ หรือมีข้อความนำ)"""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(0)
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def build_copy_text(data):
    """ประกอบข้อความสำหรับ copy: หัวข่าว + เนื้อหา + สรุป + แฮชแท็ก (เอาไปโพสต์ได้เลย)"""
    parts = []
    if data.get("headline"):
        parts.append(str(data["headline"]).strip())
    if data.get("body"):
        parts.append(str(data["body"]).strip())
    points = data.get("key_points") or []
    if points:
        parts.append("\n".join("• " + str(p).strip() for p in points))
    tags = data.get("hashtags") or []
    if tags:
        norm = []
        for t in tags:
            t = str(t).strip()
            if t and not t.startswith("#"):
                t = "#" + t
            norm.append(t)
        parts.append(" ".join(norm))
    return "\n\n".join(parts).strip()


def render_copy_button(copy_text):
    """ปุ่ม copy จริง (คัดลอกทั้งหัวข่าว+เนื้อหา+แฮชแท็กในคลิกเดียว)"""
    safe = json.dumps(copy_text)
    components.html(
        """
        <div style="font-family:'Kanit',system-ui,sans-serif">
          <button id="copyBtn" style="width:100%;padding:12px;border:none;border-radius:10px;
            background:#e8622a;color:#fff;font-size:15px;font-weight:700;cursor:pointer">
            📋 คัดลอกทั้งหมด (หัวข่าว + เนื้อหา + #)
          </button>
          <textarea id="copySrc" style="position:absolute;left:-9999px;top:-9999px"></textarea>
          <div id="copyMsg" style="text-align:center;color:#12a150;font-size:13px;margin-top:6px;min-height:16px"></div>
        </div>
        <script>
          const TXT = __TXT__;
          const btn = document.getElementById('copyBtn');
          const msg = document.getElementById('copyMsg');
          btn.addEventListener('click', async () => {
            try {
              await navigator.clipboard.writeText(TXT);
              msg.textContent = '\u2713 \u0e04\u0e31\u0e14\u0e25\u0e2d\u0e01\u0e41\u0e25\u0e49\u0e27! \u0e44\u0e1b\u0e27\u0e32\u0e07\u0e43\u0e19\u0e42\u0e1e\u0e2a\u0e15\u0e4c\u0e44\u0e14\u0e49\u0e40\u0e25\u0e22';
            } catch (e) {
              const ta = document.getElementById('copySrc');
              ta.value = TXT; ta.select();
              document.execCommand('copy');
              msg.textContent = '\u2713 \u0e04\u0e31\u0e14\u0e25\u0e2d\u0e01\u0e41\u0e25\u0e49\u0e27!';
            }
            setTimeout(()=>msg.textContent='', 2500);
          });
        </script>
        """.replace("__TXT__", safe),
        height=90,
    )


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
หน้าที่: รับข่าวสารมา แล้ว "เขียนเรียบเรียงใหม่ทั้งหมดเป็นภาษาไทย" ด้วยสำนวนของคุณเอง
ห้ามแปลตรงตัวคำต่อคำ เพื่อป้องกันปัญหาลิขสิทธิ์

สไตล์/โทนที่ต้องใช้สำหรับข่าวชิ้นนี้:
{style_instruction}

ตอบกลับเป็น JSON ที่ถูกต้องเท่านั้น (ห้ามมีข้อความอื่นนอก JSON, ห้ามครอบด้วย ```):
{{
  "headline": "พาดหัวข่าวใหม่ที่น่าสนใจ (1 บรรทัด)",
  "body": "เนื้อหาข่าวเรียบเรียงใหม่ อ่านสนุก กระชับ (2-4 ย่อหน้า)",
  "key_points": ["ประเด็นสำคัญ 1", "ประเด็นสำคัญ 2", "ประเด็นสำคัญ 3"],
  "hashtags": ["#แฮชแท็ก1", "#แฮชแท็ก2", "#แฮชแท็ก3"]
}}

เนื้อหาข่าวต้นฉบับ:
{raw_text}
"""

                    models_to_try = [
                        "gemini-3.6-flash",
                        "gemini-3.5-flash",
                        "gemini-3.4-flash",
                        "gemini-3.6-flash-lite",
                        "gemini-3.2-flash-lite",
                        "gemini-2.0-flash",
                        "gemini-1.5-flash",
                    ]

                    gemini_client = genai.Client(api_key=gemini_api_key)
                    response = None
                    used_model = ""

                    for model_name in models_to_try:
                        try:
                            response = gemini_client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                            )
                            if response and response.text:
                                used_model = model_name
                                break
                        except Exception:
                            st.caption(f"⚠️ โมเดล {model_name} ไม่พร้อมใช้งาน กำลังสลับไปใช้โมเดลสำรอง...")
                            continue

                    if response and response.text:
                        st.success(f"✨ เรียบเรียงข่าวสำเร็จ! (ประมวลผลด้วย: `{used_model}`)")
                        st.markdown("---")

                        data = parse_ai_json(response.text)

                        if data:
                            st.subheader("🔥 " + str(data.get("headline", "")))
                            st.write(data.get("body", ""))
                            pts = data.get("key_points") or []
                            if pts:
                                st.markdown("**📌 ประเด็นสำคัญ**")
                                for p in pts:
                                    st.markdown("- " + str(p))
                            tags = data.get("hashtags") or []
                            if tags:
                                st.markdown("**🏷️ " + " ".join(
                                    (t if str(t).startswith("#") else "#" + str(t)) for t in tags
                                ) + "**")

                            st.markdown("---")
                            render_copy_button(build_copy_text(data))
                        else:
                            st.markdown(response.text)
                            st.markdown("---")
                            render_copy_button(response.text)
                    else:
                        st.error("❌ โมเดล Gemini ทุกตัวไม่พร้อมใช้งานในขณะนี้ กรุณาลองใหม่อีกครั้ง")

            except Exception as e:
                st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
