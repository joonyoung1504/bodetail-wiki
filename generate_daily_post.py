"""
generate_daily_post.py  — bodetail 일일 게시물 완전 자동화
=====================================================================
실행 환경: GitHub Actions (인터넷 가능)
결과물: posts/YYYY-MM-DD/ 폴더에 1080×1440 PNG + 캡션 텍스트
=====================================================================
필요한 환경변수 (GitHub Secrets):
  ANTHROPIC_API_KEY   — Claude API 키
  PEXELS_API_KEY      — Pexels API 키 (무료: pexels.com/api)
  GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAIL — 알림용(선택)

의존성: pip install anthropic requests Pillow numpy

★ 2026-06-24 v2 업데이트 (사진 + 가독성 + 디자인 대개편):
  [사진]
  1. 슬라이드마다 Claude가 만든 image_query로 개별 검색 → 내용-사진 일치
  2. 슬라이드별 개별 사진 → 한 게시물 안 사진 중복 제거
  3. content/used_photos.json 으로 과거 사용 사진 추적 → day 간 중복 방지
  [가독성·디자인]
  4. apply_shadow_stack: 사진을 어둡게 덮지 않고 '살린다'(멀티/틴트 약화)
  5. text_scrim(): 텍스트 구간에만 부드러운 국소 스크림 (사진 본체는 안 가림)
  6. dtext(): 모든 글자에 잉크블랙 외곽선 → 밝은 사진 위에서도 또렷
  7. 본문 글꼴 Light→Regular, 색 밝은 크림, 줄간격·여백 정돈
  8. 1슬라이드 1포인트 / 마무리 CTA(@bodetail_official) 유지
"""

import os, json, re, requests, io, textwrap
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

W, H = 1080, 1440   # 3:4 인스타 그리드 네이티브

# 컬러 토큰
DARK=(8,6,4); INK=(12,12,12); GOLD=(176,132,74); GOLD_D=(100,72,35); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240); MUTED=(118,110,102)
BODY_LIGHT=(226,221,210)    # ★본문 — 사진 위에서 또렷한 밝은 크림
STROKE_INK=(4,3,2)          # ★글자 외곽선 색 (잉크블랙)

# 폰트 경로 (GitHub Actions ubuntu-latest 기준)
SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF     = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

def fnt(p, s):
    return ImageFont.truetype(p, s)
def tw(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[2]-b[0]
def th(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[3]-b[1]

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
    "WHY":"오늘의 디테일", "DETAIL":"오늘의 디테일", "ROUTINE":"오늘의 루틴",
    "PICK":"오늘의 PICK", "KNOW":"오늘의 지식", "STYLE":"오늘의 스타일",
    "BODY":"오늘의 컨디션", "SCENE":"오늘의 준비"
}
SECTION_BADGE = {
    "WHY":"DETAIL INDEX", "DETAIL":"DETAIL INDEX", "ROUTINE":"ROUTINE INDEX",
    "PICK":"CURATION", "KNOW":"KNOWLEDGE", "STYLE":"STYLE NOTE",
    "BODY":"CONDITION", "SCENE":"FOR THE MOMENT"
}
sec_code = topic.get("section","DETAIL")
topic["section_label_ko"] = SECTION_KO.get(sec_code, "오늘의 디테일")
same_sec = [t for t in schedule["topics"] if t.get("section")==sec_code and t["day"]<=day_num]
topic["vol_no"] = f"VOL.{len(same_sec):02d}"

print(f"📅 {DATE} | DAY {day_num} | [{sec_code}] {topic['title_main']}")

OUT = Path(f"posts/{DATE}_day{day_num:02d}")
OUT.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 3. Claude API로 슬라이드 콘텐츠 생성
# ══════════════════════════════════════════════════════════════
import anthropic

def load_md(f):
    p = Path(f)
    return p.read_text("utf-8") if p.exists() else f"[{f} 없음]"

design_md = load_md("brand/DESIGN-bodetail-B-realphoto.md")
voice_md  = load_md("brand/voice_guide.md")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM = f"""너는 bodetail 인스타그램 콘텐츠 매니저야.
다음 디자인 시스템과 보이스 가이드를 따라 오늘의 게시물 콘텐츠를 JSON으로만 출력해.
절대 JSON 외 텍스트를 포함하지 말 것. 마크다운 코드블록도 없이 순수 JSON만.

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

★★ 절대 원칙 — 독자가 반드시 '얻어가는 것'이 있어야 한다 ★★
- 이건 무드 매거진이다. 추상적 동기부여만 있으면 실패다.
- 각 number 슬라이드는 다음 중 최소 하나: (a)구체적 실행 팁 (b)의외의 정보·사실 (c)제품·선택 기준 (d)체크리스트.
- "왜 중요한가"는 1슬라이드면 충분. 나머지는 "그래서 뭘 어떻게"로 채워라.
- 본문은 한 슬라이드당 2~3줄. 한 줄 25자 이내 권장.
- ★ 줄바꿈은 의미 단위로. body 배열의 각 원소가 그 자체로 한 호흡(완결된 구)이 되게 하라.
  한 단어만 다음 줄로 떨어지는 어색한 끊김 금지.
- caption은 그 슬라이드 핵심을 한 문장으로.

★★ image_query — 가장 중요 (사진이 내용과 따로 노는 문제 해결) ★★
- 각 슬라이드마다 그 슬라이드 '내용에 정확히 맞는' 사진을 부를 영어 검색어를 만들어라.
- 규칙: 2~4단어 + 항상 톤 키워드(dark / moody / cinematic 중 하나) 포함.
- 슬라이드 주제를 직역하지 말고 '사진으로 존재할 법한 피사체'로 번역하라.
  예) 손톱 길이 → "manicured male hands dark"
      큐티클 정리 → "male hand care closeup moody"
      향 → "perfume bottle dark cinematic"
      눈 밑 → "man face skin closeup moody"
- 슬라이드마다 서로 다른 피사체로(같은 사진 반복 방지). 커버도 반드시 넣어라.

JSON 구조 (순수 JSON만, 코드블록 금지):
{{
  "section_label": "섹션 라벨",
  "vol": "VOL.01",
  "slides": [
    {{"slide_num": 1, "type": "cover",
      "headline_sub": "맥락 한 줄",
      "headline_main": ["메인", "헤드라인"],
      "headline_serif": "구체적 약속 (예: 놓치기 쉬운 디테일 5)",
      "image_query": "dark editorial men cinematic"}},
    {{"slide_num": 2, "type": "content", "number": "01",
      "subhead": "정보가 담긴 핵심 팁 제목",
      "body": ["구체적 내용 1", "구체적 내용 2"],
      "caption": "이 슬라이드 핵심 한 문장",
      "image_query": "manicured male hands dark"}}
  ],
  "caption_full": "인스타 캡션. 첫 줄은 강한 후킹 한 문장(광고고지로 시작 금지). 둘째 줄 (광고 아님 · 저장 유도). 공감 2줄, 관점 전환 1줄, 01~N 넘버링 요약, 마무리 슬로건, 댓글 유도 질문, @bodetail_official 팔로우 유도",
  "hashtags": "#bodetail #남자그루밍 #관련태그 (총 8~10개)"
}}
"""

print("🤖 Claude로 콘텐츠 생성 중...")
msg = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=SYSTEM,
    messages=[{"role": "user", "content": USER}]
)
raw = msg.content[0].text.strip()
raw = re.sub(r'^```json\s*', '', raw)
raw = re.sub(r'\s*```$', '', raw)
content = json.loads(raw)
content["section_label"] = topic["section_label_ko"]
content["vol"] = topic["vol_no"]
print("✅ 콘텐츠 생성 완료")

(OUT / "caption.txt").write_text(
    f"{content['caption_full']}\n\n{content['hashtags']}", encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# 4. Pexels 이미지 — 슬라이드별 검색 + 중복 회피
# ══════════════════════════════════════════════════════════════
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
USED_FILE  = Path("content/used_photos.json")

def load_used():
    if USED_FILE.exists():
        try:
            return json.loads(USED_FILE.read_text("utf-8"))
        except Exception:
            return []
    return []

def save_used(lst):
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 최근 150개만 유지 (오래된 사진은 다시 써도 무방)
    USED_FILE.write_text(json.dumps(lst[-150:], ensure_ascii=False), encoding="utf-8")

used_history = load_used()          # 과거에 쓴 photo id 리스트
recent_used  = set(used_history)
session_used = []                   # 이번 게시물에서 쓴 id (한 게시물 내 중복 방지)

def search_pexels(query, orientation="portrait"):
    """쿼리로 후보 (id, url) 리스트 반환"""
    if not PEXELS_KEY or not query:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "orientation": orientation,
                    "size": "large", "per_page": 15},
            timeout=10
        )
        return [(p["id"], p["src"]["large2x"]) for p in r.json().get("photos", [])]
    except Exception as e:
        print(f"⚠️ Pexels API 오류({query[:24]}): {e}")
        return []

def pick_photo(queries):
    """쿼리 후보들을 순서대로 시도. 과거·이번세션에 안 쓴 첫 사진을 고른다.
       전부 중복이면 첫 후보로 폴백."""
    fallback = None
    for q in queries:
        for pid, url in search_pexels(q):
            if fallback is None:
                fallback = (pid, url)
            if pid in recent_used or pid in session_used:
                continue
            return pid, url
    return fallback if fallback else (None, None)

def download_image(url):
    try:
        r = requests.get(url, timeout=15)
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"⚠️ 이미지 다운로드 실패: {e}")
        return None

def smart_crop(img, target_w=W, target_h=H):
    """object-fit:cover — 빈 공간 없이 1080x1440 채움"""
    ow, oh = img.size
    scale = max(target_w / ow, target_h / oh)
    nw, nh = int(ow * scale + 1), int(oh * scale + 1)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - target_w) // 2
    top  = int((nh - target_h) * 0.35)
    left = max(0, min(left, nw - target_w))
    top  = max(0, min(top,  nh - target_h))
    return img.crop((left, top, left + target_w, top + target_h))

def fetch_for(slide, extra_fallback):
    """슬라이드용 사진 1장 확보 (image_query 기반 + 폴백 체인)"""
    q = (slide.get("image_query") or "").strip()
    queries = []
    if q:
        queries += [q, f"{q} dark"]
    queries += [extra_fallback, "dark moody editorial men cinematic"]
    pid, url = pick_photo(queries)
    if pid is None:
        return None
    session_used.append(pid)
    img = download_image(url)
    return smart_crop(img) if img else None

print("📸 Pexels에서 슬라이드별 이미지 검색 중...")
slides_data    = content.get("slides", [])
cover_data     = next((s for s in slides_data if s["type"] == "cover"), {})
content_slides = [s for s in slides_data if s["type"] == "content"]

topic_fallback = f"{topic.get('image_search', 'editorial men')} dark"
cover_data["_photo"] = fetch_for(cover_data, topic_fallback)
print(f"  ✅ 커버 이미지 {'확보' if cover_data.get('_photo') else '대체'}")
for idx, s in enumerate(content_slides, 1):
    s["_photo"] = fetch_for(s, "men grooming detail dark moody")
    print(f"  ✅ {s.get('number', idx)} 이미지 {'확보' if s.get('_photo') else '대체'}")

# 사용 이력 저장 (다음 날 이 사진들을 피하도록)
save_used(used_history + session_used)

# ══════════════════════════════════════════════════════════════
# 5. 이미지 톤 레이어 — 사진을 '살리는' 방향
# ══════════════════════════════════════════════════════════════
def apply_shadow_stack(photo=None):
    """
    잉크블랙 톤 통일 — 단, 사진을 어둡게 묻지 않고 살린다.
    (저채도 약하게 + 균일틴트 약하게 + 하단만 살짝 + 부드러운 비네팅 + 그레인)
    """
    if photo is not None:
        base = np.array(photo, dtype=np.float32)
        if base.shape[0] != H or base.shape[1] != W:
            photo = photo.resize((W, H), Image.LANCZOS)
            base = np.array(photo, dtype=np.float32)
        gray = 0.299*base[:,:,0] + 0.587*base[:,:,1] + 0.114*base[:,:,2]
        base = gray[:,:,None]*0.45 + base*0.55      # 저채도 약하게(사진 색감 유지)
        base *= 0.99
    else:
        base = np.zeros((H, W, 3), dtype=np.float32)
        base[:] = list(DARK)
        Xg, Yg = np.meshgrid(np.arange(W), np.arange(H))
        d = np.sqrt((Xg - W*0.6)**2 + (Yg - H*0.4)**2)
        g = np.clip(1 - d/(np.sqrt(W**2+H**2)*0.55), 0, 1) * 0.22
        base[:,:,0] += g*55; base[:,:,1] += g*35; base[:,:,2] += g*12

    yv = np.linspace(0, 1, H)[:, None]
    fade = np.clip((yv - 0.45) / 0.55, 0, 1) ** 1.6 * 0.42   # 하단만 가라앉힘
    total = np.clip(fade + 0.12, 0, 0.82)[:, :, None]        # 균일틴트 약하게
    total = np.repeat(total, W, axis=1)
    ink = np.array(DARK, dtype=np.float32)[None, None, :]
    out = base*(1-total) + ink*total

    Xg, Yg = np.meshgrid(np.arange(W), np.arange(H))
    cx, cy = W/2, H/2
    dist = np.sqrt(((Xg-cx)/cx)**2 + ((Yg-cy)/cy)**2)
    vig = np.clip((dist-0.70)/0.80, 0, 1) ** 1.6 * 0.42
    out = out * (1 - vig[:,:,None])

    out = np.clip(out, 0, 255).astype(np.uint8)
    arr2 = np.array(Image.fromarray(out), dtype=np.int16)
    noise = np.random.randint(-9, 9, arr2.shape, dtype=np.int16)
    arr2 = np.clip(arr2 + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr2)

def bottom_scrim(img, ratio=0.45, strength=0.72):
    """커버 하단 헤드라인용 롱 그라데이션(아래로 갈수록 진하게)."""
    arr = np.array(img, dtype=np.float32)
    yv = np.linspace(0, 1, H)[:, None]
    start = 1 - ratio
    m = np.clip((yv - start) / ratio, 0, 1) ** 1.4 * strength
    mask = np.repeat(m[:, :, None], W, axis=1)
    ink = np.array(DARK, dtype=np.float32)[None, None, :]
    out = arr*(1-mask) + ink*mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

def text_scrim(img, top_y, bot_y, strength=0.5):
    """본문 텍스트 '구간에만' 부드러운 국소 스크림. 사진 본체(하단)는 안 가린다."""
    arr = np.array(img, dtype=np.float32)
    yv = np.arange(H).astype(np.float32)
    t0, t1 = float(top_y), float(bot_y); feather = 170.0
    m = np.zeros(H, dtype=np.float32)
    m[(yv >= t0) & (yv <= t1)] = 1.0
    up = (yv < t0) & (yv >= t0-feather); m[up] = np.clip((yv[up]-(t0-feather))/feather, 0, 1)
    dn = (yv > t1) & (yv <= t1+feather); m[dn] = np.clip(((t1+feather)-yv[dn])/feather, 0, 1)
    m = (m*strength)[:, None, None]
    mask = np.repeat(m, W, axis=1)
    ink = np.array(DARK, dtype=np.float32)[None, None, :]
    out = arr*(1-mask) + ink*mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

# ══════════════════════════════════════════════════════════════
# 6. 텍스트·UI 드로잉 (외곽선 기반)
# ══════════════════════════════════════════════════════════════
def dtext(draw, xy, text, font, fill, stroke=3, sfill=STROKE_INK):
    """잉크블랙 외곽선 텍스트 — 밝은 사진 위에서도 또렷하게 뜬다."""
    draw.text(xy, text, font=font, fill=fill, stroke_width=stroke, stroke_fill=sfill)

def wrap_text(draw, text, font, max_width):
    if text == "":
        return [""]
    words = text.split(" "); lines = []; cur = ""
    for w in words:
        trial = w if cur == "" else cur + " " + w
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur: lines.append(cur)
            if draw.textlength(w, font=font) > max_width:
                piece = ""
                for ch in w:
                    if draw.textlength(piece+ch, font=font) <= max_width:
                        piece += ch
                    else:
                        lines.append(piece); piece = ch
                cur = piece
            else:
                cur = w
    if cur: lines.append(cur)
    return lines

def draw_header(draw, sec, vol):
    lf = fnt(SANS_MED, 30); vf = fnt(SANS_LT, 24)
    dtext(draw, (MAR_X, MAR_Y), sec, lf, GOLD, stroke=2)
    lw = tw(draw, sec, lf)
    ls = MAR_X + lw + 24; le = W - MAR_X - 86
    draw.line([(ls, MAR_Y+18),(le, MAR_Y+18)], fill=(*GOLD, 175), width=2)
    if vol:
        dtext(draw, (le+14, MAR_Y+6), vol, vf, (*CREAM, 210), stroke=2)

def draw_sig(draw):
    sf = fnt(SERIF, 26); t = "bodetail"
    x = (W - tw(draw, t, sf)) // 2
    dtext(draw, (x, H-62), t, sf, (*CREAM, 200), stroke=2)

def numbox(draw, n, x, y):
    nf = fnt(SANS_BLK, 50)
    bb = draw.textbbox((0,0), n, font=nf)
    gw, gh = bb[2]-bb[0], bb[3]-bb[1]
    px, py = 24, 14
    bw, bh = gw+px*2, gh+py*2
    draw.rectangle([(x, y),(x+bw, y+bh)], fill=GOLD)
    draw.text((x+px-bb[0], y+py-bb[1]), n, font=nf, fill=INK)
    return y + bh + 30

# ══════════════════════════════════════════════════════════════
# 7. 슬라이드 렌더링
# ══════════════════════════════════════════════════════════════
def render_cover(slide_data):
    img = apply_shadow_stack(slide_data.get("_photo"))
    img = bottom_scrim(img, ratio=0.5, strength=0.72)   # 하단 헤드라인 가독
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))

    # 배지
    bf = fnt(SANS_MED, 24)
    bt = SECTION_BADGE.get(topic.get("section","DETAIL"), "DETAIL INDEX")
    bb = draw.textbbox((0,0), bt, font=bf)
    gw, gh = bb[2]-bb[0], bb[3]-bb[1]
    pad_x, pad_y = 18, 12
    bx, by = MAR_X, MAR_Y + 66
    draw.rectangle([(bx, by),(bx+gw+pad_x*2, by+gh+pad_y*2)], outline=(*CREAM, 110), width=2)
    dtext(draw, (bx+pad_x-bb[0], by+pad_y-bb[1]), bt, bf, (*CREAM, 150), stroke=2)

    # 하단 정렬 헤드라인 블록
    max_w = W - MAR_X*2
    sub = slide_data.get("headline_sub", "")
    main_lines = slide_data.get("headline_main", [])
    if isinstance(main_lines, str): main_lines = [main_lines]
    serif_txt = slide_data.get("headline_serif", "")

    # 폰트 크기 자동 맞춤
    fsize = 100
    while fsize > 62:
        mf = fnt(SANS_BLK, fsize)
        wrapped = []
        for ln in main_lines: wrapped += wrap_text(draw, ln, mf, max_w)
        lh = int(fsize*1.16)
        if len(wrapped)*lh <= 470: break
        fsize -= 6

    srf = fnt(SERIF, 40); subf = fnt(SANS_LT, 36)
    block_h = (th(draw,"가",subf)+18) + len(wrapped)*lh + (th(draw,"가",srf)+22 if serif_txt else 0)
    y = H - MAR_Y - block_h - 8

    if sub:
        dtext(draw, (MAR_X, y), sub, subf, (*CREAM, 235), stroke=2); y += th(draw,"가",subf)+18
    for l in wrapped:
        dtext(draw, (MAR_X, y), l, mf, WHITE, stroke=4); y += lh
    if serif_txt:
        for sl in wrap_text(draw, serif_txt, srf, max_w):
            dtext(draw, (MAR_X, y+8), sl, srf, GOLD_BRIGHT, stroke=2); y += int(40*1.3)

    draw_sig(draw)
    return img

def render_content(slide_data):
    img = apply_shadow_stack(slide_data.get("_photo"))
    max_w = W - MAR_X*2
    sbf = fnt(SANS_BOLD, 52); bf = fnt(SANS_REG, 37)
    d0 = ImageDraw.Draw(img)

    # 본문 높이 가늠 → 텍스트 구간에만 국소 스크림
    sub_lines = wrap_text(d0, slide_data.get("subhead",""), sbf, max_w)
    body_lines = []
    for raw in slide_data.get("body", []):
        body_lines += wrap_text(d0, raw, bf, max_w) if raw else [""]
    y_start = MAR_Y + 70
    nb_h = 96
    sub_h = len(sub_lines)*int(52*1.28)
    body_h = sum(int(37*0.8) if bl=="" else int(37*1.62) for bl in body_lines)
    text_bottom = y_start + nb_h + sub_h + 34 + body_h + 24
    img = text_scrim(img, MAR_Y-24, text_bottom, strength=0.5)

    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))

    y = y_start
    n = slide_data.get("number", "")
    if n: y = numbox(draw, n, MAR_X, y)

    for sl in sub_lines:
        dtext(draw, (MAR_X, y), sl, sbf, WHITE, stroke=3); y += int(52*1.28)
    y += 34
    for bl in body_lines:
        if bl == "":
            y += int(37*0.8); continue
        dtext(draw, (MAR_X, y), bl, bf, BODY_LIGHT, stroke=3); y += int(37*1.62)

    # 캡션 박스
    cap_txt = slide_data.get("caption", "")
    if cap_txt:
        cf = fnt(SANS_MED, 33)
        cap_lines = wrap_text(draw, cap_txt, cf, max_w-44)
        lh = int(33*1.4); ch = len(cap_lines)*lh + 30
        cy = H - MAR_Y - ch - 8
        ov = Image.new("RGBA",(W,H),(0,0,0,0)); od = ImageDraw.Draw(ov)
        od.rectangle([(MAR_X,cy),(W-MAR_X,cy+ch)], fill=(*DARK,180))
        od.rectangle([(MAR_X,cy),(MAR_X+6,cy+ch)], fill=(*GOLD,255))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        draw = ImageDraw.Draw(img)
        ty = cy+16
        for cl in cap_lines:
            dtext(draw, (MAR_X+22, ty), cl, cf, WHITE, stroke=2); ty += lh

    draw_sig(draw)
    return img

def render_content_double(sd1, sd2):
    """두 항목 한 슬라이드 (★기본 비활성 — 1슬라이드 1포인트). 수동용으로만 보존."""
    img = apply_shadow_stack(sd1.get("_photo"))
    img = text_scrim(img, MAR_Y-24, int(H*0.78), strength=0.5)
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))
    sbf = fnt(SANS_BOLD,44); bf = fnt(SANS_REG,34); lh = int(34*1.5)
    max_w = W - MAR_X*2; y = MAR_Y + 70
    for idx, sd in enumerate([sd1, sd2]):
        if sd.get("number"): y = numbox(draw, sd["number"], MAR_X, y)
        for sl in wrap_text(draw, sd.get("subhead",""), sbf, max_w):
            dtext(draw, (MAR_X,y), sl, sbf, WHITE, stroke=3); y += int(44*1.3)
        y += 10
        for raw in sd.get("body", []):
            if raw=="": y += int(lh*0.5); continue
            for bl in wrap_text(draw, raw, bf, max_w):
                dtext(draw, (MAR_X,y), bl, bf, BODY_LIGHT, stroke=3); y += lh
        if idx==0:
            y += 24; draw.line([(MAR_X,y),(W-MAR_X,y)], fill=(*GOLD,90), width=1); y += 34
    draw_sig(draw)
    return img

def render_closing():
    arr = np.zeros((H, W, 3), dtype=np.uint8); arr[:] = list(DARK)
    noise = np.random.randint(-8, 8, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16)+noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr); draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], "")

    wf = fnt(SERIF_B, 88); cf = fnt(SANS_LT, 30)
    wt = "bodetail"
    ct  = "남들이 놓치는 한 끗"
    cta = "@bodetail_official 팔로우"
    cx = W // 2

    wbb = draw.textbbox((0,0), wt, font=wf); wgw = wbb[2]-wbb[0]; wgh = wbb[3]-wbb[1]
    cbb = draw.textbbox((0,0), ct, font=cf); cgw = cbb[2]-cbb[0]
    bar_w = 64; gap = 40
    wm_x = cx - wgw//2 - wbb[0]; wm_y = H//2 - wgh//2 - wbb[1]
    wm_top = H//2 - wgh//2; wm_bot = H//2 + wgh//2

    top_bar_y = wm_top - gap
    draw.rectangle([(cx-bar_w//2, top_bar_y-2),(cx+bar_w//2, top_bar_y+1)], fill=GOLD)
    draw.text((wm_x, wm_y), wt, font=wf, fill=CREAM)
    bot_bar_y = wm_bot + gap
    draw.rectangle([(cx-bar_w//2, bot_bar_y-2),(cx+bar_w//2, bot_bar_y+1)], fill=GOLD)
    draw.text((cx - cgw//2 - cbb[0], bot_bar_y + 22), ct, font=cf, fill=(150,140,124))
    ctaf = fnt(SANS_MED, 30)
    ctab = draw.textbbox((0,0), cta, font=ctaf); ctaw = ctab[2]-ctab[0]
    draw.text((cx - ctaw//2 - ctab[0], bot_bar_y + 22 + 46), cta, font=ctaf, fill=GOLD_BRIGHT)
    return img

# ══════════════════════════════════════════════════════════════
# 8. 슬라이드 조합 & 저장
# ══════════════════════════════════════════════════════════════
rendered = []
rendered.append(("01_커버", render_cover(cover_data)))

# ★ 1슬라이드 1포인트 — 항상 single
slide_idx = 2
for s in content_slides:
    img = render_content(s)
    lbl = f"{slide_idx:02d}_{s.get('number', str(slide_idx))}"
    rendered.append((lbl, img))
    slide_idx += 1

rendered.append((f"{slide_idx:02d}_마무리", render_closing()))

print(f"\n💾 PNG 저장 중 → {OUT}/")
for name, img in rendered:
    p = OUT / f"{name}_1080x1440.png"
    img.save(p, "PNG", optimize=True, compress_level=6)
    print(f"  ✅ {p.name}")

# latest 폴더는 매번 비우고 새로 채운다 (이전 실행분 잔존 방지)
latest = Path("posts/latest")
latest.mkdir(exist_ok=True)
for old in latest.glob("*.png"):
    old.unlink()
for name, img in rendered:
    img.save(latest / f"{name}_1080x1440.png", "PNG")
(latest / "caption.txt").write_text((OUT / "caption.txt").read_text("utf-8"), encoding="utf-8")

print(f"\n🎉 완료! {len(rendered)}장 생성 → posts/latest/ & {OUT}/")
print(f"📝 캡션: {OUT}/caption.txt")
