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

★ 2026-06-24 v3:
  1. 검은 외곽선 완전 제거 — 가독성은 국소 스크림 + 어두운 무드로 확보
  2. 이미지2(향수병) 수준의 침잠된 잉크블랙 무드 (저채도 강화 + 틴트 강화)
  3. 남성 이미지 전용 검색 — 여성/네일/반지 키워드 원천 차단
     검색어에 항상 "man / male / men" 중 하나 + "moody / dark / cinematic" 강제
  4. 슬라이드별 image_query → 내용-사진 일치
  5. used_photos.json → day 간 중복 방지
  6. latest 폴더 매번 초기화 (이전 실행분 잔존 방지)
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

W, H = 1080, 1440

# 컬러 토큰
DARK=(8,6,4); INK=(12,12,12); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240); BODY_LIGHT=(226,221,210)

# 폰트
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

print(f"📅 {DATE} | DAY {day_num} | [{sec_code}] {topic['title_main']}")
OUT = Path(f"posts/{DATE}_day{day_num:02d}")
OUT.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 3. Claude API — 콘텐츠 + image_query 생성
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

USER = f"""오늘 게시물을 JSON으로 만들어줘.

주제: {topic['title_main']}
섹션: {topic['section']}
후킹타입: {topic['hook_type']}
슬라이드수: {topic['num_slides']}

★★ 콘텐츠 원칙 ★★
- 독자가 반드시 '얻어가는 것'이 있어야 한다. 추상적 동기부여 금지.
- 각 슬라이드: (a)구체 실행 팁 (b)의외의 정보 (c)제품·선택 기준 (d)체크리스트 중 최소 하나.
- 본문 2~3줄. 한 줄 25자 이내. 줄바꿈은 의미 단위(한 단어만 떨어지는 어색한 끊김 금지).
- caption: 그 슬라이드 핵심 한 문장.

★★ image_query — 남성 전용 감도컷 필수 ★★
우리 브랜드는 남성 잡지다. 사진 선정 규칙:
1. 검색어에 반드시 "man" 또는 "male" 또는 "men" 중 하나 포함.
2. 여성·네일아트·반지·꽃 등 여성성 키워드 절대 금지.
3. 피사체는 '오브제 중심 감도컷' 우선 — 향수병, 시계, 가죽, 면도기, 남성 손, 슈트, 신발 등.
4. 인물이면 반드시 남성. 클로즈업·시크·무드 있는 구도.
5. 톤 키워드: dark / moody / cinematic / editorial 중 반드시 하나 포함.
6. 슬라이드마다 서로 다른 피사체(중복 방지).

image_query 예시:
  손톱 → "man hands clean nails dark"
  큐티클 → "male hand grooming closeup moody"
  향 → "men cologne bottle dark cinematic"
  면도 → "man shaving dark editorial"
  피부 → "man face closeup dark moody"
  시계 → "man wristwatch leather dark"
  슈트 → "man suit jacket dark cinematic"
  핸드크림 → "men hand cream luxury dark"

JSON 구조 (순수 JSON만, 코드블록 금지):
{{
  "section_label": "섹션 라벨",
  "vol": "VOL.01",
  "slides": [
    {{"slide_num": 1, "type": "cover",
      "headline_sub": "맥락 한 줄",
      "headline_main": ["메인", "헤드라인"],
      "headline_serif": "구체적 약속",
      "image_query": "man dark editorial cinematic"}},
    {{"slide_num": 2, "type": "content", "number": "01",
      "subhead": "핵심 팁 제목",
      "body": ["구체 내용 1", "구체 내용 2"],
      "caption": "핵심 한 문장",
      "image_query": "man hands clean nails dark"}}
  ],
  "caption_full": "인스타 캡션. 첫 줄 강한 후킹(광고고지 금지). 둘째 줄 (광고 아님·저장 유도). 공감 2줄, 관점 전환 1줄, 01~N 요약, 슬로건, 댓글 유도, @bodetail_official 팔로우",
  "hashtags": "#bodetail #남자그루밍 #관련태그 (8~10개)"
}}
"""

print("🤖 Claude 콘텐츠 생성 중...")
msg = client.messages.create(
    model="claude-sonnet-4-6", max_tokens=4096,
    system=SYSTEM, messages=[{"role":"user","content":USER}]
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
# 4. Pexels — 남성 이미지 전용 + 중복 회피
# ══════════════════════════════════════════════════════════════
PEXELS_KEY = os.environ.get("PEXELS_API_KEY","")
USED_FILE  = Path("content/used_photos.json")

# ★ 남성 이미지 보장 필터 — 여성성 키워드가 포함된 검색어는 강제로 남성 키워드 보정
FEMALE_WORDS = {"woman","women","female","girl","ladies","nail","ring","flower",
                "feminine","pink","makeup","cosmetic"}

def sanitize_query(q: str) -> str:
    """여성 키워드 제거 + 남성 키워드 보장"""
    words = q.lower().split()
    words = [w for w in words if w not in FEMALE_WORDS]
    has_male = any(w in {"man","male","men"} for w in words)
    if not has_male:
        words = ["man"] + words
    has_mood = any(w in {"dark","moody","cinematic","editorial","noir"} for w in words)
    if not has_mood:
        words += ["dark"]
    return " ".join(words[:6])  # Pexels 검색어 6단어 이내

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
            params={"query":q,"orientation":orientation,"size":"large","per_page":15},
            timeout=10
        )
        return [(p["id"], p["src"]["large2x"]) for p in r.json().get("photos",[])]
    except Exception as e:
        print(f"⚠️ Pexels({q[:24]}): {e}"); return []

def pick_photo(queries):
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
    left = (nw-W)//2
    top  = int((nh-H)*0.35)
    return img.crop((max(0,min(left,nw-W)), max(0,min(top,nh-H)),
                     max(0,min(left,nw-W))+W, max(0,min(top,nh-H))+H))

def fetch_for(slide, fallback_q):
    q = (slide.get("image_query") or "").strip()
    queries = [q, f"{q} dark", fallback_q, "man dark moody cinematic editorial"] if q else \
              [fallback_q, "man dark moody cinematic editorial"]
    pid, url = pick_photo(queries)
    if pid is None: return None
    session_used.append(pid)
    img = download_image(url)
    return smart_crop(img) if img else None

print("📸 슬라이드별 남성 이미지 검색 중...")
slides_data    = content.get("slides",[])
cover_data     = next((s for s in slides_data if s["type"]=="cover"), {})
content_slides = [s for s in slides_data if s["type"]=="content"]

fb = f"{topic.get('image_search','editorial men')} dark"
cover_data["_photo"] = fetch_for(cover_data, fb)
print(f"  커버: {'✅' if cover_data.get('_photo') else '⚠️ 대체'}")
for s in content_slides:
    s["_photo"] = fetch_for(s, "man grooming detail dark moody")
    print(f"  {s.get('number','?')}: {'✅' if s.get('_photo') else '⚠️ 대체'}")

save_used(used_history + session_used)

# ══════════════════════════════════════════════════════════════
# 5. 이미지 처리 — 이미지2 수준 어두운 무드
# ══════════════════════════════════════════════════════════════
def apply_dark_mood(photo=None):
    """
    이미지2(향수병) 수준의 침잠된 잉크블랙 무드.
    - 저채도 강하게 (흑백 62% 블렌드)
    - 균일 잉크 틴트 42%
    - 하단 롱 그라데이션
    - 강한 비네팅
    외곽선 없이도 글씨가 보이는 어두운 베이스를 만든다.
    """
    if photo is not None:
        base = np.array(photo, dtype=np.float32)
        if base.shape[:2] != (H,W):
            photo = photo.resize((W,H), Image.LANCZOS)
            base = np.array(photo, dtype=np.float32)
        gray = 0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base = gray[:,:,None]*0.62 + base*0.38   # ★ 저채도 강하게
        base *= 0.88
    else:
        base = np.zeros((H,W,3),dtype=np.float32); base[:] = list(DARK)
        Xg,Yg = np.meshgrid(np.arange(W),np.arange(H))
        d = np.sqrt(((Xg-W*0.52)/320.)**2+((Yg-H*0.56)/360.)**2)
        g = np.clip(1-d,0,1)*0.28
        base[:,:,0]+=g*80; base[:,:,1]+=g*68; base[:,:,2]+=g*52

    ink = np.array(DARK,dtype=np.float32)[None,None,:]
    base = base*0.58 + ink*0.42              # ★ 균일 틴트 42%

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
    """텍스트 구간에만 국소 스크림 — 외곽선 없이 가독 확보"""
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
    """커버 하단 헤드라인 가독용"""
    arr = np.array(img,dtype=np.float32)
    yv  = np.linspace(0,1,H)[:,None]
    m   = np.clip((yv-(1-ratio))/ratio,0,1)**1.4*strength
    mask= np.repeat(m[:,:,None],W,axis=1)
    ink = np.array(DARK,dtype=np.float32)[None,None,:]
    return Image.fromarray(np.clip(arr*(1-mask)+ink*mask,0,255).astype(np.uint8))

# ══════════════════════════════════════════════════════════════
# 6. 드로잉 헬퍼 (외곽선 ZERO)
# ══════════════════════════════════════════════════════════════
def ptext(draw, xy, text, font, fill):
    """★ 외곽선 없는 순수 텍스트. 가독은 어두운 무드+스크림으로 확보."""
    draw.text(xy, text, font=font, fill=fill)

def wrap_text(draw, text, font, mw):
    if text==""  : return [""]
    words=text.split(" "); lines=[]; cur=""
    for w in words:
        t=w if cur=="" else cur+" "+w
        if draw.textlength(t,font=font)<=mw: cur=t
        else:
            if cur: lines.append(cur)
            if draw.textlength(w,font=font)>mw:
                piece=""
                for ch in w:
                    if draw.textlength(piece+ch,font=font)<=mw: piece+=ch
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

    # 배지
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

    # ★ 외곽선 없이 가독 확보: 텍스트 구간 국소 스크림
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
    cbb=draw.textbbox((0,0),ct,font=cf);  cgw=cbb[2]-cbb[0]
    bar_w=64; gap=40
    wm_x=cx-wgw//2-wbb[0]; wm_y=H//2-wgh//2-wbb[1]
    wm_top=H//2-wgh//2;     wm_bot=H//2+wgh//2
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
    rendered.append((f"{slide_idx:02d}_{s.get('number',str(slide_idx))}", render_content(s)))
    slide_idx+=1

rendered.append((f"{slide_idx:02d}_마무리", render_closing()))

print(f"\n💾 PNG 저장 → {OUT}/")
for name,img in rendered:
    p=OUT/f"{name}_1080x1440.png"
    img.save(p,"PNG",optimize=True,compress_level=6)
    print(f"  ✅ {p.name}")

# latest 폴더 초기화 후 교체 (이전 실행분 잔존 방지)
latest=Path("posts/latest"); latest.mkdir(exist_ok=True)
for old in latest.glob("*.png"): old.unlink()
for name,img in rendered:
    img.save(latest/f"{name}_1080x1440.png","PNG")
(latest/"caption.txt").write_text((OUT/"caption.txt").read_text("utf-8"),encoding="utf-8")

print(f"\n🎉 {len(rendered)}장 완료 → posts/latest/ & {OUT}/")
print(f"📝 {OUT}/caption.txt")
