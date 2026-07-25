import streamlit as st
from apify_client import ApifyClient
from google import genai

# ตั้งค่าหน้าตาของเว็บ
st.set_page_config(page_title="AI เรียบเรียงข่าว Facebook", page_icon="📰", layout="centered")

st.title("📰 ระบบดึงและเรียบเรียงข่าว Facebook")
st.write("วางลิงก์โพสต์ Facebook เพื่อดึงเนื้อหามาเรียบเรียงใหม่ด้วย Gemini AI ไม่ให้ซ้ำต้นฉบับ")

# ดึง API Key จากระบบ Secrets หลังบ้าน
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
apify_token = st.secrets.get("APIFY_TOKEN", "")

# ช่องกรอกลิงก์บนหน้าเว็บ
url = st.text_input("🔗 วางลิงก์ Facebook ที่นี่:", placeholder="https://www.facebook.com/share/p/...")

# ปุ่มกดสั่งทำงาน
if st.button("🚀 เริ่มเรียบเรียงข่าว", type="primary"):
    if not url:
        st.warning("กรุณาวางลิงก์ Facebook ก่อนครับ")
    elif not gemini_api_key or not apify_token:
        st.error("ไม่พบคีย์ API ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud")
    else:
        with st.spinner("กำลังดึงข้อมูลจาก Facebook และเรียบเรียงข่าวใหม่... (อาจใช้เวลา 10-15 วินาที)"):
            try:
                # 1. ดึงข้อมูลจาก Facebook ด้วย Apify
                apify_client = ApifyClient(apify_token)
                run_input = {"startUrls": [{"url": url}], "resultsLimit": 1}
                run = apify_client.actor("apify/facebook-posts-scraper").call(run_input=run_input)
                
                dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
                
                fb_text = ""
                for item in apify_client.dataset(dataset_id).iterate_items():
                    text_content = item.get("text") or item.get("postText") or item.get("caption") or ""
                    if text_content:
                        fb_text += text_content + "\n"

                if not fb_text:
                    st.error("ไม่สามารถดึงข้อความจากลิงก์นี้ได้ กรุณาเช็กว่าเป็นโพสต์สาธารณะหรือไม่")
                else:
                    # 2. ส่งให้ Gemini เรียบเรียงข่าวใหม่
                    prompt = f"""
                    คุณคือ คอนเทนต์ครีเอเตอร์และนักข่าวมืออาชีพ 
                    หน้าที่ของคุณคือรับข่าวสารภาษาต่างประเทศมา แล้ว "เขียนเรียบเรียงใหม่ทั้งหมดเป็นภาษาไทย" ด้วยสำนวนภาษาของคุณเอง 
                    ห้ามแปลตรงตัวแบบคำต่อคำ เพื่อป้องกันปัญหาลิขสิทธิ์และการก๊อปปี้งาน

                    รูปแบบการเขียนที่ต้องการ:
                    1. 🔥 **พาดหัวข่าว (Headline):** เขียนพาดหัวใหม่ให้น่าสนใจ
                    2. 📝 **เนื้อหาข่าวเรียบเรียงใหม่ (Body):** เล่าข่าวด้วยสำนวนใหม่ อ่านสนุก กระชับ
                    3. 📌 **สรุป 3 ประเด็นสำคัญ:** ทำเป็น Bullet points สั้นๆ
                    4. 🏷️ **Hashtag:** ใส่แฮชแท็ก 3-5 อัน

                    เนื้อหาข่าวต้นฉบับ:
                    {fb_text}
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
