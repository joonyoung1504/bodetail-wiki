"""
generate_daily_post.py  — bodetail 일일 게시물 완전 자동화
=====================================================================
실행 환경: GitHub Actions (인터넷 가능)
결과물: posts/YYYY-MM-DD/ 폴더에 1080×1440 PNG + 캡션 텍스트
=====================================================================
필요한 환경변수 (GitHub Secrets):
  ANTHROPIC_API_KEY   — Claude API 키
  PEXELS_API_KEY      — Pexels API 키 (무료: pexels.com/api)

의존성: pip install anthropic requests Pillow numpy

★ 2026-06-25 v5:
  1. SUBJECT_RULES — 슬라이드 본문 키워드로 필수 피사체 강제
     (손톱→hands/nails, 핸드크림→hand cream applying, 큐티클→hands closeup 등)
     Claude image_query만으로 해결 안 되는 부분을 코드 레벨에서 재작성
  2. 동작 키워드 포함 — "applying" / "moisturizer" 등 제품+손 동시 등장 유도
  3. PICK 섹션 전용 render_pick() 추가 — 제품 추천 게시물 템플릿
     rating stars, 제품명, 가격대, 한줄평, 구매포인트 레이아웃
"""

import os, json, re, requests, io
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ══════════════════════════════════════════════════════════════
# 1. 설정 & 날짜
# ══════════════════════════════════════════════════════════════
KST   = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)
DATE  = TODAY.strftime("%Y-%m-%d")
W, H  = 1080, 1440

DARK=(8,6,4); INK=(12,12,12); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240); BODY_LIGHT=(226,221,210)
GOLD_D=(100,72,35)

SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF     = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

def fnt(p, s): return ImageFont.truetype(p, s)
def tw(d, t, f): b=d.textbbox((0,0),t,font=f); return b[2]-b[0]
def th(d, t, f): b=d.textbbox((0,0),t,font=f); return b[3]-b[1]

MAR_X, MAR_Y = 84, 92

# ══════════════════════════════════════════════════════════════
# 1-B. ★ 주제별 필수 피사체 규칙 (코드 레벨 강제)
# ══════════════════════════════════════════════════════════════
# subhead / body 텍스트에서 키워드가 감지되면 해당 image_queries를 덮어씀
# Claude가 image_query를 잘못 만들어도 이 테이블이 최종 보정한다
SUBJECT_RULES = [
    # (감지 키워드들,  강제 image_queries 3개)
    ({"손톱","nail","nails","손끝","길이","3mm","2mm","파일"},
     ["man clean trimmed nails closeup dark",
      "male hand nails grooming moody",
      "men hands fingers closeup dark"]),

    ({"큐티클","cuticle","큐티클 정리","밀기"},
     ["man cuticle care hands closeup dark",
      "male hands grooming detail moody",
      "men hands care closeup dark"]),

    ({"핸드크림","hand cream","핸드 크림","moisturizer","보습","건조","갈라진"},
     ["man applying hand cream dark moody",
      "male hands moisturizer luxury dark",
      "men hand lotion applying closeup"]),

    ({"향수","cologne","perfume","fragrance","냄새","향"},
     ["men cologne bottle dark cinematic",
      "man perfume luxury dark moody",
      "male fragrance bottle editorial dark"]),

    ({"면도","shaving","髭","수염","shave"},
     ["man shaving dark editorial",
      "male razor shaving moody",
      "men grooming shave dark cinematic"]),

    ({"피부","스킨케어","세럼","에센스","토너","로션","skin","toner"},
     ["man skincare serum dark moody",
      "male face skin closeup editorial",
      "men skincare routine dark cinematic"]),

    ({"시계","watch","wristwatch"},
     ["man wristwatch dark cinematic",
      "male luxury watch moody",
      "men watch leather dark editorial"]),

    ({"슈트","suit","재킷","jacket","넥타이","tie"},
     ["man suit dark editorial",
      "male formal suit moody cinematic",
      "men jacket dark professional"]),

    ({"헤어","머리","hair","두피","샴푸"},
     ["man hair dark editorial moody",
      "male hairstyle dark cinematic",
      "men hair grooming dark"]),

    ({"눈","다크서클","부기","아이크림","eye"},
     ["man face closeup eyes dark moody",
      "male dark circles eye care",
      "men face skin closeup editorial"]),

    ({"신발","shoes","구두","leather"},
     ["man leather shoes dark cinematic",
      "male dress shoes dark moody",
      "men footwear editorial dark"]),
]

def subject_override(slide: dict) -> list | None:
    """슬라이드 텍스트에서 주제 키워드 감지 → 강제 image_queries 반환. 없으면 None."""
    text = " ".join([
        slide.get("subhead",""),
        " ".join(slide.get("body",[])),
        slide.get("caption",""),
    ]).lower()
    for keywords, queries in SUBJECT_RULES:
        if any(k.lower() in text for k in keywords):
            return queries
    return None

# ══════════════════════════════════════════════════════════════
# 2. 주제 로드
# ══════════════════════════════════════════════════════════════
day_override = os.environ.get("DAY_OVERRIDE", "").strip()
with open("content/topics_30.json", "r", encoding="utf-8") as f:
    schedule = json.load(f)

if day_override:
    day_num = int(day_override)
else:
    start_date = datetime(2026, 9, 15, tzinfo=KST)
    elapsed = max(0, (TODAY - start_date).days)
    day_num = (elapsed % 30) + 1

topic = next((t for t in schedule["topics"] if t["day"] == day_num),
             schedule["topics"][0])

SECTION_KO = {
    "WHY":"오늘의 디테일","DETAIL":"오늘의 디테일","ROUTINE":"오늘의 루틴",
    "PICK":"오늘의 PICK","KNOW":"오늘의 지식","STYLE":"오늘의 스타일",
    "BODY":"오늘의 컨디션","SCENE":"오늘의 준비"
}
SECTION_BADGE = {
    "WHY":"DETAIL INDEX","DETAIL":"DETAIL INDEX","ROUTINE":"ROUTINE INDEX",
    "PICK":"CURATION","KNOW":"KNOWLEDGE","STYLE":"STYLE NOTE",
    "BODY":"CONDITION","SCENE":"FOR THE MOMENT"
}
sec_code = topic.get("section","DETAIL")
topic["section_label_ko"] = SECTION_KO.get(sec_code, "오늘의 디테일")
same_sec = [t for t in schedule["topics"] if t.get("section")==sec_code and t["day"]<=day_num]
topic["vol_no"] = f"VOL.{len(same_sec):02d}"
is_pick = (sec_code == "PICK")

print(f"📅 {DATE} | DAY {day_num} | [{sec_code}{'·PICK' if is_pick else ''}] {topic['title_main']}")
OUT = Path(f"posts/{DATE}_day{day_num:02d}")
OUT.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 3. Claude API — 콘텐츠 생성
# ══════════════════════════════════════════════════════════════
import anthropic

def load_md(f):
    p = Path(f)
    return p.read_text("utf-8") if p.exists() else f"[{f} 없음]"

design_md = load_md("brand/DESIGN-bodetail-B-realphoto.md")
voice_md  = load_md("brand/voice_guide.md")
client    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM = f"""너는 bodetail 인스타그램 콘텐츠 매니저야.
다음 디자인 시스템과 보이스 가이드를 따라 오늘의 게시물 콘텐츠를 JSON으로만 출력해.
절대 JSON 외 텍스트 없이 순수 JSON만.

[DESIGN]
{design_md[:3000]}
[VOICE]
{voice_md[:2000]}
"""

# PICK 섹션 전용 프롬프트
PICK_USER = f"""오늘은 제품 추천(PICK) 게시물이야. JSON으로 만들어줘.

주제: {topic['title_main']}
섹션: PICK

★★ PICK 게시물 원칙 ★★
- 우리는 제품을 파는 게 아니라 '안목 있는 에디터'가 큐레이션하는 거다.
- 광고처럼 보이면 실패. "이게 왜 좋은지"를 명확히, 짧게.
- 추천 제품은 실제 존재하는 남성 그루밍 제품으로 (핸드크림, 향수, 면도, 스킨케어 등).
- 가격대는 현실적으로 (2만원~15만원 선).
- 각 제품 슬라이드는 1개 제품만. 별점은 5점 만점 기준.

JSON 구조 (순수 JSON만):
{{
  "section_label": "오늘의 PICK",
  "vol": "VOL.01",
  "slides": [
    {{"slide_num": 1, "type": "cover",
      "headline_sub": "에디터의 한 줄 이유",
      "headline_main": ["제품 카테고리", "큐레이션 제목"],
      "headline_serif": "이달의 추천 N선",
      "image_queries": ["men grooming product dark moody", "male skincare luxury dark", "men cologne bottle cinematic"]}},
    {{"slide_num": 2, "type": "pick",
      "number": "01",
      "product_name": "제품명 (브랜드 포함)",
      "price": "가격대 (예: 3만원대)",
      "stars": 4,
      "one_line": "한 줄 픽 이유 (15자 이내)",
      "body": ["구매 포인트 1", "구매 포인트 2"],
      "caption": "이 제품 핵심 선언.",
      "image_queries": ["men face cream luxury dark", "male skincare product moody", "men grooming cream dark"]}}
  ],
  "caption_full": "캡션. 첫 줄 강한 후킹. (광고 아님·저장 유도). 큐레이션 이유, 제품 요약, @bodetail_official 팔로우",
  "hashtags": "#bodetail #남자그루밍 #관련태그 (8~10개)"
}}
"""

CONTENT_USER = f"""오늘 게시물을 JSON으로 만들어줘.

주제: {topic['title_main']}
섹션: {topic['section']}
후킹타입: {topic['hook_type']}
슬라이드수: {topic['num_slides']}

★★ 제목·헤드라인 원칙 ★★
- 선언적이고 묵직하게. 읽는 순간 '맞다'고 느끼게.
  좋은 예: "손이 모든 걸 결정한다" / "디테일이 인상을 만든다" / "손끝이 첫인상이다"
  나쁜 예: "손이 다 말해버린다"(구어체 과잉) / "손이 중요해요"(약함)
- 숫자가 들어가면 강해진다: "아무도 안 알려준 손 디테일 5"
- 커버 headline_main은 2~3줄, 한 줄 8자 이내.

★★ 콘텐츠 원칙 ★★
- 독자가 반드시 '얻어가는 것'이 있어야 한다. 추상적 동기부여 금지.
- 각 슬라이드: 구체 실행 팁 / 의외의 정보 / 선택 기준 / 체크리스트 중 최소 하나.
- 본문 2~3줄. 한 줄 25자 이내. 줄바꿈은 의미 단위로.
- caption: 그 슬라이드 핵심을 한 문장으로, 선언형으로.

★★ image_queries — 피사체 일치가 핵심 ★★
각 슬라이드 내용에 정확히 맞는 검색어 3개를 우선순위 순으로.
규칙:
1. "man"/"male"/"men" 반드시 포함.
2. 여성·네일아트·반지·꽃 키워드 금지.
3. 피사체를 구체 오브제나 동작으로 번역:
   핸드크림 → "man applying hand cream dark"  (동작 포함)
   손톱 → "man clean nails hands closeup dark"  (신체부위 포함)
   냄새 → "men cologne bottle dark"  (오브제 포함)
   면접 → "man suit dark editorial"
4. 톤 키워드(dark/moody/cinematic/editorial) 반드시 포함.
5. 슬라이드마다 다른 피사체.

JSON 구조 (순수 JSON만, 코드블록 금지):
{{
  "section_label": "섹션 라벨",
  "vol": "VOL.01",
  "slides": [
    {{"slide_num": 1, "type": "cover",
      "headline_sub": "맥락 한 줄",
      "headline_main": ["묵직한", "선언형", "제목"],
      "headline_serif": "구체적 약속",
      "image_queries": ["man dark studio portrait", "male editorial dark", "men moody portrait"]}},
    {{"slide_num": 2, "type": "content", "number": "01",
      "subhead": "선언형 핵심 팁 제목",
      "body": ["구체 내용 1", "구체 내용 2"],
      "caption": "핵심 선언 한 문장.",
      "image_queries": ["man clean nails hands closeup dark", "male hand grooming moody", "men hands dark editorial"]}}
  ],
  "caption_full": "캡션. 첫 줄 강한 후킹(광고고지 금지). (광고 아님·저장 유도). 공감 2줄, 관점 전환 1줄, 01~N 요약, 슬로건, 댓글 유도, @bodetail_official 팔로우",
  "hashtags": "#bodetail #남자그루밍 #관련태그 (8~10개)"
}}
"""

print("🤖 Claude 콘텐츠 생성 중...")
msg = client.messages.create(
    model="claude-sonnet-4-6", max_tokens=4096,
    system=SYSTEM,
    messages=[{"role":"user","content": PICK_USER if is_pick else CONTENT_USER}]
)
raw = msg.content[0].text.strip()
raw = re.sub(r'^```json\s*','',raw); raw = re.sub(r'\s*```$','',raw)
content = json.loads(raw)
content["section_label"] = topic["section_label_ko"]
content["vol"] = topic["vol_no"]
print("✅ 콘텐츠 생성 완료")

(OUT / "caption.txt").write_text(
    f"{content['caption_full']}\n\n{content['hashtags']}", encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# 4. Pexels — 주제 보정 + 3단 폴백 + 남성 필터 + 중복 회피
# ══════════════════════════════════════════════════════════════
PEXELS_KEY = os.environ.get("PEXELS_API_KEY","")
USED_FILE  = Path("content/used_photos.json")

FEMALE_WORDS = {
    "woman","women","female","girl","girls","ladies","lady",
    "nail","nails","ring","rings","flower","flowers","floral",
    "feminine","pink","makeup","cosmetic","cosmetics","beauty"
}

def sanitize_query(q: str) -> str:
    words = q.lower().split()
    words = [w for w in words if w not in FEMALE_WORDS]
    if not any(w in {"man","male","men"} for w in words):
        words = ["man"] + words
    if not any(w in {"dark","moody","cinematic","editorial","noir","low-key"} for w in words):
        words += ["dark"]
    return " ".join(words[:6])

def load_used():
    if USED_FILE.exists():
        try: return json.loads(USED_FILE.read_text("utf-8"))
        except: return []
    return []

def save_used(lst):
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(lst[-200:], ensure_ascii=False), encoding="utf-8")

used_history = load_used()
recent_used  = set(used_history)
session_used = []

def search_pexels(query, orientation="portrait"):
    if not PEXELS_KEY: return []
    q = sanitize_query(query)
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query":q,"orientation":orientation,"size":"large","per_page":20},
            timeout=10
        )
        return [(p["id"], p["src"]["large2x"]) for p in r.json().get("photos",[])]
    except Exception as e:
        print(f"⚠️ Pexels({q[:24]}): {e}"); return []

def pick_photo(queries: list) -> tuple:
    fallback = None
    for q in queries:
        for pid, url in search_pexels(q):
            if fallback is None: fallback = (pid, url)
            if pid in recent_used or pid in session_used: continue
            return pid, url
    return fallback if fallback else (None, None)

def download_image(url):
    try:
        r = requests.get(url, timeout=15)
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"⚠️ 다운로드 실패: {e}"); return None

def smart_crop(img):
    ow, oh = img.size
    scale = max(W/ow, H/oh)
    nw, nh = int(ow*scale+1), int(oh*scale+1)
    img = img.resize((nw,nh), Image.LANCZOS)
    left = (nw-W)//2; top = int((nh-H)*0.35)
    return img.crop((max(0,min(left,nw-W)), max(0,min(top,nh-H)),
                     max(0,min(left,nw-W))+W, max(0,min(top,nh-H))+H))

def fetch_for(slide, hardcoded_fallback):
    """
    ★ 핵심: subject_override 먼저 적용 → 있으면 Claude 쿼리를 덮어씀
    없으면 Claude가 만든 image_queries 사용
    """
    # 1순위: 주제 키워드 감지로 강제 덮어쓰기
    forced = subject_override(slide)
    if forced:
        qs = forced
        print(f"    → 주제 보정 적용: {qs[0][:30]}")
    else:
        qs = slide.get("image_queries") or []
        if not qs:
            single = (slide.get("image_query") or "").strip()
            qs = [single] if single else []

    qs += [hardcoded_fallback, "man dark moody cinematic editorial"]
    pid, url = pick_photo(qs)
    if pid is None: return None
    session_used.append(pid)
    img = download_image(url)
    return smart_crop(img) if img else None

print("📸 슬라이드별 이미지 검색 중...")
slides_data    = content.get("slides",[])
cover_data     = next((s for s in slides_data if s["type"]=="cover"), {})
content_slides = [s for s in slides_data if s["type"] in ("content","pick")]

topic_fb = f"{topic.get('image_search','editorial men')} dark"
cover_data["_photo"] = fetch_for(cover_data, topic_fb)
print(f"  커버: {'✅' if cover_data.get('_photo') else '⚠️'}")
for s in content_slides:
    s["_photo"] = fetch_for(s, "man grooming detail dark moody")
    print(f"  {s.get('number','?')}: {'✅' if s.get('_photo') else '⚠️'}")

save_used(used_history + session_used)

# ══════════════════════════════════════════════════════════════
# 5. 이미지 처리
# ══════════════════════════════════════════════════════════════
def apply_dark_mood(photo=None):
    if photo is not None:
        base = np.array(photo, dtype=np.float32)
        if base.shape[:2] != (H,W):
            photo = photo.resize((W,H), Image.LANCZOS)
            base = np.array(photo, dtype=np.float32)
        gray = 0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base = gray[:,:,None]*0.62 + base*0.38
        base *= 0.88
    else:
        base = np.zeros((H,W,3),dtype=np.float32); base[:]=list(DARK)
        Xg,Yg = np.meshgrid(np.arange(W),np.arange(H))
        d = np.sqrt(((Xg-W*0.52)/320.)**2+((Yg-H*0.56)/360.)**2)
        g = np.clip(1-d,0,1)*0.28
        base[:,:,0]+=g*80; base[:,:,1]+=g*68; base[:,:,2]+=g*52

    ink = np.array(DARK,dtype=np.float32)[None,None,:]
    base = base*0.58 + ink*0.42
    yv = np.linspace(0,1,H)[:,None]
    fade = np.clip((yv-0.48)/0.52,0,1)**1.5*0.65
    mask = np.repeat(fade[:,:,None],W,axis=1)
    base = base*(1-mask)+ink*mask
    Xg,Yg = np.meshgrid(np.arange(W),np.arange(H)); cx,cy=W/2,H/2
    dist = np.sqrt(((Xg-cx)/cx)**2+((Yg-cy)/cy)**2)
    vig = np.clip((dist-0.55)/0.75,0,1)**1.5*0.60
    base = base*(1-vig[:,:,None])
    out = np.clip(base,0,255).astype(np.uint8)
    arr2 = np.array(Image.fromarray(out),dtype=np.int16)
    noise = np.random.randint(-8,8,arr2.shape,dtype=np.int16)
    return Image.fromarray(np.clip(arr2+noise,0,255).astype(np.uint8))

def text_scrim(img, top_y, bot_y, strength=0.58):
    arr = np.array(img,dtype=np.float32)
    yv  = np.arange(H).astype(np.float32)
    t0,t1 = float(top_y),float(bot_y); fe=180.0
    m = np.zeros(H,dtype=np.float32)
    m[(yv>=t0)&(yv<=t1)] = 1.0
    up=(yv<t0)&(yv>=t0-fe); m[up]=np.clip((yv[up]-(t0-fe))/fe,0,1)
    dn=(yv>t1)&(yv<=t1+fe); m[dn]=np.clip(((t1+fe)-yv[dn])/fe,0,1)
    m=(m*strength)[:,None,None]; mask=np.repeat(m,W,axis=1)
    ink=np.array(DARK,dtype=np.float32)[None,None,:]
    return Image.fromarray(np.clip(arr*(1-mask)+ink*mask,0,255).astype(np.uint8))

def bottom_scrim(img, ratio=0.48, strength=0.70):
    arr = np.array(img,dtype=np.float32)
    yv  = np.linspace(0,1,H)[:,None]
    m   = np.clip((yv-(1-ratio))/ratio,0,1)**1.4*strength
    mask= np.repeat(m[:,:,None],W,axis=1)
    ink = np.array(DARK,dtype=np.float32)[None,None,:]
    return Image.fromarray(np.clip(arr*(1-mask)+ink*mask,0,255).astype(np.uint8))

# ══════════════════════════════════════════════════════════════
# 6. 드로잉 헬퍼
# ══════════════════════════════════════════════════════════════
def ptext(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)

def wrap_text(draw, text, font, mw):
    if text == "": return [""]
    words=text.split(" "); lines=[]; cur=""
    for w in words:
        t = w if cur=="" else cur+" "+w
        if draw.textlength(t,font=font) <= mw: cur=t
        else:
            if cur: lines.append(cur)
            if draw.textlength(w,font=font) > mw:
                piece=""
                for ch in w:
                    if draw.textlength(piece+ch,font=font) <= mw: piece+=ch
                    else: lines.append(piece); piece=ch
                cur=piece
            else: cur=w
    if cur: lines.append(cur)
    return lines

def draw_header(draw, sec, vol):
    lf=fnt(SANS_MED,30); vf=fnt(SANS_LT,24)
    ptext(draw,(MAR_X,MAR_Y),sec,lf,GOLD)
    lw=tw(draw,sec,lf); ls=MAR_X+lw+24; le=W-MAR_X-86
    draw.line([(ls,MAR_Y+18),(le,MAR_Y+18)],fill=(*GOLD,180),width=2)
    if vol: ptext(draw,(le+14,MAR_Y+6),vol,vf,(*CREAM,220))

def draw_sig(draw):
    sf=fnt(SERIF,26); t="bodetail"; x=(W-tw(draw,t,sf))//2
    ptext(draw,(x,H-62),t,sf,(*CREAM,210))

def numbox(draw, n, x, y):
    nf=fnt(SANS_BLK,50); bb=draw.textbbox((0,0),n,font=nf)
    gw,gh=bb[2]-bb[0],bb[3]-bb[1]; px,py=24,14
    bw,bh=gw+px*2,gh+py*2
    draw.rectangle([(x,y),(x+bw,y+bh)],fill=GOLD)
    draw.text((x+px-bb[0],y+py-bb[1]),n,font=nf,fill=INK)
    return y+bh+30

# ══════════════════════════════════════════════════════════════
# 7. 슬라이드 렌더링
# ══════════════════════════════════════════════════════════════
def render_cover(slide_data):
    img  = apply_dark_mood(slide_data.get("_photo"))
    img  = bottom_scrim(img)
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))

    bf=fnt(SANS_MED,24)
    bt=SECTION_BADGE.get(topic.get("section","DETAIL"),"DETAIL INDEX")
    bb=draw.textbbox((0,0),bt,font=bf); gw,gh=bb[2]-bb[0],bb[3]-bb[1]
    px,py=18,12; bx,by=MAR_X,MAR_Y+66
    draw.rectangle([(bx,by),(bx+gw+px*2,by+gh+py*2)],outline=(*CREAM,110),width=2)
    ptext(draw,(bx+px-bb[0],by+py-bb[1]),bt,bf,(*CREAM,155))

    max_w=W-MAR_X*2
    sub=slide_data.get("headline_sub","")
    main_lines=slide_data.get("headline_main",[])
    if isinstance(main_lines,str): main_lines=[main_lines]
    serif_txt=slide_data.get("headline_serif","")

    fsize=100
    while fsize>62:
        mf=fnt(SANS_BLK,fsize)
        wrapped=[]
        for ln in main_lines: wrapped+=wrap_text(draw,ln,mf,max_w)
        lh=int(fsize*1.16)
        if len(wrapped)*lh<=470: break
        fsize-=6

    srf=fnt(SERIF,40); subf=fnt(SANS_LT,36)
    block_h=(th(draw,"가",subf)+18 if sub else 0)+len(wrapped)*lh+(int(40*1.3) if serif_txt else 0)
    y=H-MAR_Y-block_h-8

    if sub:
        ptext(draw,(MAR_X,y),sub,subf,(*CREAM,235)); y+=th(draw,"가",subf)+18
    for l in wrapped:
        ptext(draw,(MAR_X,y),l,mf,WHITE); y+=lh
    if serif_txt:
        for sl in wrap_text(draw,serif_txt,srf,max_w):
            ptext(draw,(MAR_X,y+8),sl,srf,GOLD_BRIGHT); y+=int(40*1.3)

    draw_sig(draw)
    return img

def render_content(slide_data):
    img=apply_dark_mood(slide_data.get("_photo"))
    max_w=W-MAR_X*2
    sbf=fnt(SANS_BOLD,52); bf=fnt(SANS_REG,37)
    d0=ImageDraw.Draw(img)

    sub_lines=wrap_text(d0,slide_data.get("subhead",""),sbf,max_w)
    body_lines=[]
    for raw in slide_data.get("body",[]):
        body_lines+=wrap_text(d0,raw,bf,max_w) if raw else [""]
    y_start=MAR_Y+70; nb_h=96
    sub_h=len(sub_lines)*int(52*1.28)
    body_h=sum(int(37*0.8) if bl=="" else int(37*1.62) for bl in body_lines)
    text_bottom=y_start+nb_h+sub_h+34+body_h+24

    img=text_scrim(img,MAR_Y-30,text_bottom,strength=0.58)
    draw=ImageDraw.Draw(img)
    draw_header(draw,content["section_label"],content.get("vol","VOL.01"))

    y=y_start
    n=slide_data.get("number","")
    if n: y=numbox(draw,n,MAR_X,y)

    for sl in sub_lines:
        ptext(draw,(MAR_X,y),sl,sbf,WHITE); y+=int(52*1.28)
    y+=34
    for bl in body_lines:
        if bl=="": y+=int(37*0.8); continue
        ptext(draw,(MAR_X,y),bl,bf,BODY_LIGHT); y+=int(37*1.62)

    cap_txt=slide_data.get("caption","")
    if cap_txt:
        cf=fnt(SANS_MED,33)
        cap_lines=wrap_text(draw,cap_txt,cf,max_w-44)
        lh=int(33*1.4); ch=len(cap_lines)*lh+30; cy=H-MAR_Y-ch-8
        ov=Image.new("RGBA",(W,H),(0,0,0,0)); od=ImageDraw.Draw(ov)
        od.rectangle([(MAR_X,cy),(W-MAR_X,cy+ch)],fill=(*DARK,185))
        od.rectangle([(MAR_X,cy),(MAR_X+6,cy+ch)],fill=(*GOLD,255))
        img=Image.alpha_composite(img.convert("RGBA"),ov).convert("RGB")
        draw=ImageDraw.Draw(img)
        ty=cy+16
        for cl in cap_lines:
            ptext(draw,(MAR_X+22,ty),cl,cf,WHITE); ty+=lh

    draw_sig(draw)
    return img

def render_pick(slide_data):
    """
    ★ PICK 전용 템플릿 — 제품 추천 슬라이드
    레이아웃: 넘버박스 / 제품명(크게) / 별점 / 가격 / 한줄픽이유 / 본문 / 캡션박스
    사진은 하단 50% — 제품 오브제가 은은하게 보이도록
    """
    img=apply_dark_mood(slide_data.get("_photo"))
    # PICK은 상단 60%를 더 어둡게 — 텍스트 공간 확보
    img=text_scrim(img, MAR_Y-30, int(H*0.60), strength=0.65)
    max_w=W-MAR_X*2
    draw=ImageDraw.Draw(img)
    draw_header(draw,content["section_label"],content.get("vol","VOL.01"))

    y=MAR_Y+70
    n=slide_data.get("number","")
    if n: y=numbox(draw,n,MAR_X,y)

    # 제품명
    pf=fnt(SANS_BOLD,54)
    product=slide_data.get("product_name","")
    for pl in wrap_text(draw,product,pf,max_w):
        ptext(draw,(MAR_X,y),pl,pf,WHITE); y+=int(54*1.22)
    y+=16

    # 별점 ★★★★☆
    stars=int(slide_data.get("stars",4))
    star_str = "★"*stars + "☆"*(5-stars)
    sf2=fnt(SANS_MED,38)
    ptext(draw,(MAR_X,y),star_str,sf2,GOLD); y+=int(38*1.3)

    # 가격 + 한줄 픽 이유
    price=slide_data.get("price","")
    one_line=slide_data.get("one_line","")
    mf2=fnt(SANS_LT,34)
    if price:
        ptext(draw,(MAR_X,y),f"{price}  ·  {one_line}",mf2,(*CREAM,210)); y+=int(34*1.5)
    y+=20

    # 구매 포인트
    bf=fnt(SANS_REG,37)
    for raw in slide_data.get("body",[]):
        for bl in wrap_text(draw,raw,bf,max_w):
            ptext(draw,(MAR_X,y),f"— {bl}",bf,BODY_LIGHT); y+=int(37*1.62)

    # 캡션 박스
    cap_txt=slide_data.get("caption","")
    if cap_txt:
        cf=fnt(SANS_MED,33)
        cap_lines=wrap_text(draw,cap_txt,cf,max_w-44)
        lh=int(33*1.4); ch=len(cap_lines)*lh+30; cy=H-MAR_Y-ch-8
        ov=Image.new("RGBA",(W,H),(0,0,0,0)); od=ImageDraw.Draw(ov)
        od.rectangle([(MAR_X,cy),(W-MAR_X,cy+ch)],fill=(*DARK,185))
        od.rectangle([(MAR_X,cy),(MAR_X+6,cy+ch)],fill=(*GOLD,255))
        img=Image.alpha_composite(img.convert("RGBA"),ov).convert("RGB")
        draw=ImageDraw.Draw(img)
        ty=cy+16
        for cl in cap_lines:
            ptext(draw,(MAR_X+22,ty),cl,cf,WHITE); ty+=lh

    draw_sig(draw)
    return img

def render_closing():
    arr=np.zeros((H,W,3),dtype=np.uint8); arr[:]=list(DARK)
    noise=np.random.randint(-8,8,arr.shape,dtype=np.int16)
    arr=np.clip(arr.astype(np.int16)+noise,0,255).astype(np.uint8)
    img=Image.fromarray(arr); draw=ImageDraw.Draw(img)
    draw_header(draw,content["section_label"],"")

    wf=fnt(SERIF_B,88); cf=fnt(SANS_LT,30)
    wt="bodetail"; ct="남들이 놓치는 한 끗"; cta="@bodetail_official 팔로우"
    cx=W//2
    wbb=draw.textbbox((0,0),wt,font=wf); wgw=wbb[2]-wbb[0]; wgh=wbb[3]-wbb[1]
    cbb=draw.textbbox((0,0),ct,font=cf); cgw=cbb[2]-cbb[0]
    bar_w=64; gap=40
    wm_x=cx-wgw//2-wbb[0]; wm_y=H//2-wgh//2-wbb[1]
    wm_top=H//2-wgh//2; wm_bot=H//2+wgh//2
    draw.rectangle([(cx-bar_w//2,wm_top-gap-2),(cx+bar_w//2,wm_top-gap+1)],fill=GOLD)
    draw.text((wm_x,wm_y),wt,font=wf,fill=CREAM)
    bot_bar_y=wm_bot+gap
    draw.rectangle([(cx-bar_w//2,bot_bar_y-2),(cx+bar_w//2,bot_bar_y+1)],fill=GOLD)
    draw.text((cx-cgw//2-cbb[0],bot_bar_y+22),ct,font=cf,fill=(150,140,124))
    ctaf=fnt(SANS_MED,30); ctab=draw.textbbox((0,0),cta,font=ctaf); ctaw=ctab[2]-ctab[0]
    draw.text((cx-ctaw//2-ctab[0],bot_bar_y+22+46),cta,font=ctaf,fill=GOLD_BRIGHT)
    return img

# ══════════════════════════════════════════════════════════════
# 8. 슬라이드 조합 & 저장
# ══════════════════════════════════════════════════════════════
rendered=[]
rendered.append(("01_커버", render_cover(cover_data)))

slide_idx=2
for s in content_slides:
    stype = s.get("type","content")
    if stype == "pick":
        img = render_pick(s)
    else:
        img = render_content(s)
    rendered.append((f"{slide_idx:02d}_{s.get('number',str(slide_idx))}", img))
    slide_idx+=1

rendered.append((f"{slide_idx:02d}_마무리", render_closing()))

print(f"\n💾 PNG 저장 → {OUT}/")
for name,img in rendered:
    p=OUT/f"{name}_1080x1440.png"
    img.save(p,"PNG",optimize=True,compress_level=6)
    print(f"  ✅ {p.name}")

latest=Path("posts/latest"); latest.mkdir(exist_ok=True)
for old in latest.glob("*.png"): old.unlink()
for name,img in rendered:
    img.save(latest/f"{name}_1080x1440.png","PNG")
(latest/"caption.txt").write_text((OUT/"caption.txt").read_text("utf-8"),encoding="utf-8")

print(f"\n🎉 {len(rendered)}장 완료 → posts/latest/ & {OUT}/")
print(f"📝 {OUT}/caption.txt")
