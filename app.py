import json
import re
import os
import time

import streamlit as st
from apify_client import ApifyClient
from google import genai
import requests
from bs4 import BeautifulSoup
import streamlit.components.v1 as components

st.set_page_config(page_title="พุ่งล้ม — ข่าว/สคริปต์/ไฮไลต์", page_icon="📰", layout="centered")

# ---------- คีย์หลังบ้าน ----------
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
apify_token = st.secrets.get("APIFY_TOKEN", "")

HISTORY_FILE = "history.json"
MAX_HISTORY = 10

MODELS = [
    "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.4-flash",
    "gemini-3.6-flash-lite", "gemini-3.2-flash-lite",
    "gemini-2.0-flash", "gemini-1.5-flash",
]

# ---------- อ่าน mode + url จาก query param ----------
def get_qp(name, default=""):
    try:
        v = st.query_params.get(name, default)
        return v if v is not None else default
    except Exception:
        qp = st.experimental_get_query_params()
        return qp.get(name, [default])[0] if qp.get(name) else default

mode = (get_qp("mode", "news") or "news").lower()
prefill_url = get_qp("url", "")


# ---------- Gemini helper (มี fallback) ----------
@st.cache_resource(show_spinner=False)
def get_client(key):
    return genai.Client(api_key=key)

def gemini_generate(prompt):
    if not gemini_api_key:
        return None, ""
    client = get_client(gemini_api_key)
    for m in MODELS:
        try:
            resp = client.models.generate_content(model=m, contents=prompt)
            if resp and resp.text:
                return resp.text, m
        except Exception:
            continue
    return None, ""


# ---------- ประวัติ (session + ไฟล์ best-effort) ----------
def load_history():
    if "history" in st.session_state:
        return st.session_state["history"]
    data = []
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = []
    st.session_state["history"] = data
    return data

def save_history(hist):
    st.session_state["history"] = hist
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
    except Exception:
        pass

def add_history(item):
    hist = load_history()
    hist.insert(0, item)
    del hist[MAX_HISTORY:]
    save_history(hist)


# ---------- ประกอบข้อความ / parse ----------
def parse_ai_json(text):
    if not text:
        return None
    c = text.strip()
    c = re.sub(r"^```(?:json)?", "", c).strip()
    c = re.sub(r"```$", "", c).strip()
    mm = re.search(r"\{.*\}", c, re.DOTALL)
    if mm:
        c = mm.group(0)
    try:
        return json.loads(c)
    except Exception:
        return None

def build_copy_text(data):
    parts = []
    if data.get("headline"):
        parts.append(str(data["headline"]).strip())
    if data.get("body"):
        parts.append(str(data["body"]).strip())
    pts = data.get("key_points") or []
    if pts:
        parts.append("\n".join("• " + str(p).strip() for p in pts))
    tags = data.get("hashtags") or []
    if tags:
        parts.append(" ".join((t if str(t).startswith("#") else "#"+str(t)) for t in tags))
    return "\n\n".join(parts).strip()

def render_copy_button(copy_text, label="📋 คัดลอกทั้งหมด", h=90):
    safe = json.dumps(copy_text)
    html = """
    <div style="font-family:'Kanit',system-ui,sans-serif">
      <button id="cb" style="width:100%;padding:12px;border:none;border-radius:10px;
        background:#e8622a;color:#fff;font-size:15px;font-weight:700;cursor:pointer">__LABEL__</button>
      <textarea id="cs" style="position:absolute;left:-9999px;top:-9999px"></textarea>
      <div id="cm" style="text-align:center;color:#12a150;font-size:13px;margin-top:6px;min-height:16px"></div>
    </div>
    <script>
      const TXT=__TXT__;const b=document.getElementById('cb'),m=document.getElementById('cm');
      b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(TXT);m.textContent='\u2713 \u0e04\u0e31\u0e14\u0e25\u0e2d\u0e01\u0e41\u0e25\u0e49\u0e27!';}
        catch(e){const t=document.getElementById('cs');t.value=TXT;t.select();document.execCommand('copy');m.textContent='\u2713 \u0e04\u0e31\u0e14\u0e25\u0e2d\u0e01\u0e41\u0e25\u0e49\u0e27!';}
        setTimeout(()=>m.textContent='',2500);});
    </script>
    """.replace("__TXT__", safe).replace("__LABEL__", label)
    components.html(html, height=h)


# ---------- สคริปต์พูด (voiceover 30วิ-1นาที) ----------
LEN_MAP = {
    "30 วินาที": (30, "70-90 คำ"),
    "45 วินาที": (45, "100-130 คำ"),
    "60 วินาที (1 นาที)": (60, "140-180 คำ"),
}

def make_voice_script(item, seconds, words):
    src = build_copy_text(item)
    prompt = f"""
คุณคือครีเอเตอร์ทำคลิปข่าวบอลสั้นลง YouTube/TikTok
เขียน "บทพากย์ (voiceover) ภาษาไทย" สำหรับพูดยาวประมาณ {seconds} วินาที ({words})
สไตล์: พูดคุยเป็นกันเอง กระชับ มีฮุกเปิดให้คนหยุดดูใน 3 วินาทีแรก จบด้วยชวนกดติดตาม/คอมเมนต์
ห้ามใส่หัวข้อ/วงเล็บกำกับ ให้เขียนเป็นบทพูดล้วน ๆ ที่อ่านออกเสียงได้ต่อเนื่อง

ข่าวต้นทาง:
{src}
"""
    text, _ = gemini_generate(prompt)
    return text or ""

def render_script_ui(item, key_prefix):
    c1, c2 = st.columns([2, 1])
    length_label = c1.selectbox("ความยาวคลิป", list(LEN_MAP.keys()), key=f"len_{key_prefix}")
    go = c2.button("🎙️ สร้างสคริปต์พูด", key=f"btn_{key_prefix}", use_container_width=True)
    store_key = f"script_{key_prefix}_{length_label}"
    if go:
        secs, words = LEN_MAP[length_label]
        with st.spinner("กำลังเขียนบทพากย์..."):
            st.session_state[store_key] = make_voice_script(item, secs, words)
    if st.session_state.get(store_key):
        script = st.session_state[store_key]
        st.text_area("บทพากย์ (แก้ไขได้)", script, height=170, key=f"ta_{store_key}")
        render_copy_button(st.session_state.get(f"ta_{store_key}", script), "📋 คัดลอกบทพากย์", h=90)


# ---------- ขูดเนื้อหา ----------
def scrape_content(url_link, token):
    low = url_link.lower()
    if "x.com" in low or "twitter.com" in low:
        mm = re.search(r'(?:twitter|x)\.com/([^/]+)/status/(\d+)', url_link)
        if mm:
            user, tid = mm.groups()
            try:
                r = requests.get(f"https://api.vxtwitter.com/{user}/status/{tid}",
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    if d.get("text"):
                        return f"โพสต์โดย {d.get('user_name','')}:\n{d['text']}", "X (Twitter)"
            except Exception:
                pass
        ac = ApifyClient(token)
        run = ac.actor("apidojo/tweet-scraper").call(run_input={"tweetURLs": [url_link], "startUrls": [url_link], "maxItems": 1})
        did = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
        txt = ""
        for it in ac.dataset(did).iterate_items():
            t = it.get("text") or it.get("fullText") or it.get("full_text") or ""
            if t:
                txt += t + "\n"
        return txt, "X (Twitter)"
    elif "facebook.com" in low or "fb.watch" in low or "fb.com" in low:
        ac = ApifyClient(token)
        run = ac.actor("apify/facebook-posts-scraper").call(run_input={"startUrls": [{"url": url_link}], "resultsLimit": 1})
        did = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
        txt = ""
        for it in ac.dataset(did).iterate_items():
            t = it.get("text") or it.get("postText") or it.get("caption") or ""
            if t:
                txt += t + "\n"
        return txt, "Facebook"
    else:
        r = requests.get(url_link, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        for el in soup(["script", "style", "header", "footer", "nav", "aside", "form"]):
            el.decompose()
        ps = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 20]
        return "\n".join(ps), "เว็บไซต์ข่าวทั่วไป"


NEWS_STYLES = {
    "📰 ข่าวทั่วไป": "เขียนแบบข่าวมาตรฐาน อ่านสนุก กระชับ เข้าใจง่าย เป็นกลาง น่าเชื่อถือ",
    "💸 ข่าวซื้อขาย / ตลาดนักเตะ": "เขียนสไตล์ข่าวตลาดซื้อขายนักเตะ เน้น ใคร-ย้ายจากไหน-ไปไหน-ค่าตัว-สถานะดีล (ปิดดีล/ใกล้ปิด/สนใจ/ข่าวลือ) ใส่ตัวเลขค่าตัวและระยะสัญญาถ้ามี โทนกระชับเร้าใจแบบเพจข่าวลูกหนัง",
    "😂 ข่าวตลก / Gossip": "เขียนสไตล์บันเทิง/แซว อ่านสนุก กวน ๆ มีอารมณ์ขัน เล่นมุกเหน็บเบา ๆ ได้ แต่คงใจความข่าวจริง ไม่ใส่ร้ายหรือสร้างข้อมูลเท็จ",
}


# =====================================================================
#  โหมดไฮไลต์
# =====================================================================
def render_highlight_mode():
    st.title("🎬 ตัวช่วยทำคลิปไฮไลต์นักเตะ")
    st.caption("ช่วยวางแผน + เขียนบท ให้เอาไปตัดต่อเองได้เร็วขึ้น (ไม่ได้โหลด/ตัดคลิปคนอื่นมาให้)")

    with st.expander("⚠️ อ่านก่อน: เรื่องฟุตเทจ & ลิขสิทธิ์ (สำคัญ)", expanded=True):
        st.markdown("""
- ฟุตเทจการแข่งเป็น **ลิขสิทธิ์ของลีก/ช่องถ่ายทอด** (พรีเมียร์ลีก, ลาลีกา ฯลฯ) การ **ก๊อปคลิปคนอื่น/ตัดจากการถ่ายทอดมาลง YouTube เสี่ยงโดนแจ้งลิขสิทธิ์ (copyright strike) ปิดรายได้ หรือปิดช่อง**
- ระบบนี้จึง **ไม่ไปโหลดหรือตัดคลิปให้อัตโนมัติ** — มันช่วย "เขียนบท/วางโครง/ทำ SEO" ให้ ส่วนภาพคุณต้องหามาถูกลิขสิทธิ์เอง
- แหล่งฟุตเทจที่ปลอดภัยกว่า: ภาพที่ **คุณถ่าย/บันทึกเอง**, สต็อกฟรี (Pexels, Pixabay, Mixkit) สำหรับ B-roll สนาม/บรรยากาศ, หรือ **ขอ/ซื้อสิทธิ์** จากเจ้าของ (Getty/Imagn เสียเงิน) — คลิปไฮไลต์เฉพาะนักเตะที่ฟรี+ถูกลิขสิทธิ์จริง ๆ แทบไม่มี นั่นคือเหตุผลที่ช่องไฮไลต์ส่วนใหญ่อยู่ในโซนเสี่ยง
- ตัดต่อฟรี: **CapCut / DaVinci Resolve** (ฟรี ทำคลิป 8–10 นาทีได้สบายกว่าทำในเว็บ)
        """)

    player = st.text_input("⚽ ชื่อนักเตะ", placeholder="เช่น Lamine Yamal, บุกาโย ซาก้า")
    c1, c2 = st.columns(2)
    kind = c1.selectbox("ประเภทคลิป", ["สั้น (1–3 นาที)", "ยาว (8–10 นาที)"])
    if "สั้น" in kind:
        minutes = c2.slider("ความยาว (นาที)", 1, 3, 2)
    else:
        minutes = c2.slider("ความยาว (นาที)", 6, 12, 9)

    angle = st.text_input("มุมคลิป (ไม่ใส่ก็ได้)", placeholder="เช่น สกิลเลี้ยงเลื้อย, ทุกประตูฤดูกาลนี้, เดบิวต์สุดโหด")

    if st.button("🚀 สร้างบท + โครงคลิป", type="primary"):
        if not player.strip():
            st.warning("ใส่ชื่อนักเตะก่อนครับ")
        elif not gemini_api_key:
            st.error("ไม่พบ GEMINI_API_KEY ใน Secrets")
        else:
            with st.spinner("กำลังร่างบทและโครงคลิป..."):
                prompt = f"""
คุณคือครีเอเตอร์ช่อง YouTube ไฮไลต์ฟุตบอลภาษาไทย
ช่วยวางแผนคลิปไฮไลต์นักเตะ: "{player}"
ความยาวเป้าหมาย: ประมาณ {minutes} นาที
มุมคลิป: {angle or "ไฮไลต์รวมความสามารถเด่น"}

ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความนอก JSON, ห้ามครอบ ```):
{{
  "title": "ชื่อคลิปภาษาไทยที่คนอยากคลิก",
  "hook": "บทพูดเปิด 2-3 ประโยค ให้คนหยุดดูใน 5 วิแรก",
  "intro_script": "บทพากย์อินโทรสั้น ๆ",
  "segments": [
    {{"time": "0:00", "topic": "ช่วงคลิป", "voiceover": "บทพากย์ช่วงนี้ (สั้น)", "footage": "ควรใส่ภาพอะไร"}}
  ],
  "outro_script": "บทปิด ชวนกดติดตาม/คอมเมนต์",
  "youtube_description": "คำอธิบายใต้คลิป",
  "tags": ["แท็ก1", "แท็ก2"],
  "hashtags": ["#แท็ก1", "#แท็ก2"]
}}
ให้จำนวน segments เหมาะกับความยาว {minutes} นาที (คลิปยาวใส่หลายช่วง) และ time ไล่ตามลำดับจนเกือบครบความยาว
"""
                text, used = gemini_generate(prompt)
                if not text:
                    st.error("❌ โมเดลไม่พร้อมใช้งาน ลองใหม่อีกครั้ง")
                else:
                    st.session_state["hl_result"] = parse_ai_json(text) or {"_raw": text}

    data = st.session_state.get("hl_result")
    if data:
        st.markdown("---")
        if data.get("_raw"):
            st.markdown(data["_raw"])
        else:
            st.subheader("🎬 " + str(data.get("title", "")))
            if data.get("hook"):
                st.markdown("**🪝 ฮุกเปิด**"); st.write(data["hook"])
            if data.get("intro_script"):
                st.markdown("**🎙️ อินโทร**"); st.write(data["intro_script"])
            segs = data.get("segments") or []
            if segs:
                st.markdown("**🧩 โครงคลิป + shot list**")
                for s in segs:
                    st.markdown(f"**{s.get('time','')} — {s.get('topic','')}**")
                    if s.get("voiceover"):
                        st.write("🎙️ " + str(s["voiceover"]))
                    if s.get("footage"):
                        st.caption("🎞️ ภาพ: " + str(s["footage"]))
            if data.get("outro_script"):
                st.markdown("**👋 เอาต์โทร**"); st.write(data["outro_script"])
            if data.get("youtube_description"):
                st.markdown("**📄 คำอธิบาย YouTube**"); st.write(data["youtube_description"])
            tags = data.get("tags") or []
            hh = data.get("hashtags") or []
            if tags:
                st.markdown("**🏷️ แท็ก:** " + ", ".join(str(t) for t in tags))
            if hh:
                st.markdown("**#️⃣ แฮชแท็ก:** " + " ".join((t if str(t).startswith("#") else "#"+str(t)) for t in hh))

            # ก้อนข้อความสำหรับคัดลอกไปวางใต้คลิป
            copy_all = "\n\n".join(filter(None, [
                str(data.get("title", "")),
                str(data.get("youtube_description", "")),
                " ".join((t if str(t).startswith("#") else "#"+str(t)) for t in hh),
            ]))
            st.markdown("---")
            render_copy_button(copy_all, "📋 คัดลอกชื่อ+คำอธิบาย+แฮชแท็ก", h=90)


# =====================================================================
#  โหมดข่าว (แปล + ประวัติ + สคริปต์)
# =====================================================================
def render_news_mode():
    st.title("📰 แปลข่าว + ประวัติ + สคริปต์พูด")
    tab_translate, tab_history = st.tabs(["🔄 แปลข่าว", f"🕘 ประวัติ + 🎙️ สคริปต์พูด"])

    with tab_translate:
        st.write("วางลิงก์ข่าวจาก **Facebook, X หรือเว็บข่าว** เพื่อเรียบเรียงใหม่ด้วย Gemini")
        url = st.text_input("🔗 ลิงก์ข่าว", value=prefill_url, placeholder="https://...")
        label = st.selectbox("🎭 ประเภทข่าว", list(NEWS_STYLES.keys()))

        if st.button("🚀 เริ่มเรียบเรียงข่าว", type="primary"):
            if not url:
                st.warning("กรุณาวางลิงก์ก่อนครับ")
            elif not gemini_api_key:
                st.error("ไม่พบ GEMINI_API_KEY ใน Secrets")
            else:
                with st.spinner("กำลังดึงและเรียบเรียงข่าว..."):
                    try:
                        raw, src = scrape_content(url, apify_token)
                        if not raw or not raw.strip():
                            st.error(f"ดึงข้อความจาก {src} ไม่ได้ (เช็กว่าลิงก์เปิดสาธารณะไหม)")
                        else:
                            st.info(f"📍 แหล่งที่มา: **{src}**")
                            prompt = f"""
คุณคือคอนเทนต์ครีเอเตอร์และนักข่าวมืออาชีพ
เขียนเรียบเรียงข่าวใหม่ทั้งหมดเป็นภาษาไทยด้วยสำนวนของคุณเอง ห้ามแปลตรงตัวคำต่อคำ
สไตล์: {NEWS_STYLES[label]}

ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความนอก JSON, ห้ามครอบ ```):
{{"headline":"พาดหัวใหม่","body":"เนื้อหาเรียบเรียงใหม่ 2-4 ย่อหน้า","key_points":["ประเด็น1","ประเด็น2","ประเด็น3"],"hashtags":["#แท็ก1","#แท็ก2","#แท็ก3"]}}

ข่าวต้นฉบับ:
{raw}
"""
                            text, used = gemini_generate(prompt)
                            if not text:
                                st.error("❌ โมเดลไม่พร้อมใช้งาน ลองใหม่อีกครั้ง")
                            else:
                                data = parse_ai_json(text)
                                if not data:
                                    data = {"headline": "", "body": text, "key_points": [], "hashtags": []}
                                item = {
                                    "headline": data.get("headline", ""),
                                    "body": data.get("body", ""),
                                    "key_points": data.get("key_points", []),
                                    "hashtags": data.get("hashtags", []),
                                    "source": src, "url": url,
                                    "id": str(int(time.time() * 1000)),
                                    "time": time.strftime("%d/%m %H:%M"),
                                }
                                add_history(item)
                                st.session_state["last_item"] = item
                                st.success(f"✨ สำเร็จ! (โมเดล: {used}) — บันทึกลงประวัติแล้ว")
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาด: {e}")

        item = st.session_state.get("last_item")
        if item:
            st.markdown("---")
            st.subheader("🔥 " + str(item.get("headline", "")))
            st.write(item.get("body", ""))
            if item.get("key_points"):
                st.markdown("**📌 ประเด็นสำคัญ**")
                for p in item["key_points"]:
                    st.markdown("- " + str(p))
            if item.get("hashtags"):
                st.markdown("**🏷️ " + " ".join((t if str(t).startswith("#") else "#"+str(t)) for t in item["hashtags"]) + "**")
            st.markdown("---")
            render_copy_button(build_copy_text(item), "📋 คัดลอกทั้งหมด (หัวข่าว + เนื้อหา + #)")
            with st.expander("🎙️ ทำสคริปต์พูดจากข่าวนี้ (30วิ–1นาที)"):
                render_script_ui(item, "current")

    with tab_history:
        hist = load_history()
        st.caption(f"เก็บ {len(hist)}/{MAX_HISTORY} ข่าวล่าสุด · ประวัติอยู่บนเซิร์ฟเวอร์ (ฟรีแพลนอาจรีเซ็ตถ้าแอปรีสตาร์ท และแชร์ร่วมกันถ้ามีหลายคนใช้ลิงก์เดียวกัน)")
        if st.button("🗑️ ล้างประวัติทั้งหมด"):
            save_history([])
            st.rerun()
        hist = load_history()
        if not hist:
            st.info("ยังไม่มีประวัติ — ไปแท็บ 'แปลข่าว' แล้วแปลสักข่าวก่อนครับ")
        for i, it in enumerate(hist):
            head = it.get("headline") or (it.get("body", "")[:40] + "...")
            with st.expander(f"{i+1}. {head}  ·  🕒 {it.get('time','')}  ·  {it.get('source','')}"):
                st.write(it.get("body", ""))
                if it.get("hashtags"):
                    st.markdown("**🏷️ " + " ".join((t if str(t).startswith("#") else "#"+str(t)) for t in it["hashtags"]) + "**")
                render_copy_button(build_copy_text(it), "📋 คัดลอกข่าวนี้", h=90)
                st.markdown("**🎙️ ทำสคริปต์พูดสำหรับคลิป**")
                render_script_ui(it, it.get("id", str(i)))


# ---------- เรียกตามโหมด ----------
if mode == "highlight":
    render_highlight_mode()
else:
    render_news_mode()
