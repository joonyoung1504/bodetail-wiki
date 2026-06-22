"""
generate_daily_post.py  — bodetail 일일 게시물 완전 자동화
=====================================================================
실행 환경: GitHub Actions (인터넷 가능)
결과물: posts/YYYY-MM-DD/ 폴더에 1080×1440 PNG 5장 + 캡션 텍스트
=====================================================================
필요한 환경변수 (GitHub Secrets):
  ANTHROPIC_API_KEY   — Claude API 키
  PEXELS_API_KEY      — Pexels API 키 (무료: pexels.com/api)
  GMAIL_USER          — 알림용 Gmail 주소
  GMAIL_APP_PASSWORD  — Gmail 앱 비밀번호
  NOTIFY_EMAIL        — 받을 이메일

의존성: pip install anthropic requests Pillow numpy
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
DARK=(8,6,4); INK=(12,12,12); GOLD=(176,132,74); GOLD_D=(100,72,35)
CREAM=(237,230,216); WHITE=(245,244,240); MUTED=(118,110,102)

# 폰트 경로 (GitHub Actions ubuntu-latest 기준)
SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF     = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
SERIF_B   = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

def fnt(p, s):
    return ImageFont.truetype(p, s)
def tw(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[2]-b[0]
def th(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[3]-b[1]

MAR_X, MAR_Y = 78, 88

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

print(f"📅 {DATE} | DAY {day_num} | {topic['title_main']}")

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
카테고리: {topic['category']}
섹션라벨: {topic['section_label']}
후킹타입: {topic['hook_type']}
슬라이드수: {topic['num_slides']}

아래 JSON 구조로 출력:
{{
  "section_label": "섹션 라벨",
  "vol": "VOL.01",
  "slides": [
    {{
      "slide_num": 1,
      "type": "cover",
      "headline_sub": "보조줄",
      "headline_main": ["메인", "헤드라인", "줄바꿈"],
      "headline_serif": "— 서브 한 줄"
    }},
    {{
      "slide_num": 2,
      "type": "content",
      "number": "01",
      "subhead": "소제목",
      "body": ["본문줄1", "본문줄2", ""],
      "caption": "캡션 한 줄"
    }}
  ],
  "caption_full": "전체 인스타 캡션 (세르칸 6단 구조)",
  "hashtags": "#bodetail #태그1 #태그2"
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
print("✅ 콘텐츠 생성 완료")

# 캡션 저장
(OUT / "caption.txt").write_text(
    f"{content['caption_full']}\n\n{content['hashtags']}", encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# 4. Pexels에서 실사 이미지 다운로드
# ══════════════════════════════════════════════════════════════
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")

def get_pexels_photo(query, orientation="portrait"):
    """Pexels API로 무드 맞는 사진 URL 가져오기"""
    if not PEXELS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "orientation": orientation,
                    "size": "large", "per_page": 5},
            timeout=10
        )
        photos = r.json().get("photos", [])
        if photos:
            # 첫 번째 결과의 large2x URL (최고화질)
            return photos[0]["src"]["large2x"]
    except Exception as e:
        print(f"⚠️ Pexels API 오류: {e}")
    return None

def download_image(url):
    """URL에서 PIL Image로 로드"""
    try:
        r = requests.get(url, timeout=15)
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"⚠️ 이미지 다운로드 실패: {e}")
        return None

def smart_crop(img, target_w=W, target_h=H):
    """중앙 기준 스마트 크롭 → 1080×1440"""
    ow, oh = img.size
    target_ratio = target_w / target_h
    source_ratio = ow / oh
    if source_ratio > target_ratio:
        # 너무 넓음 → 좌우 잘라냄
        new_w = int(oh * target_ratio)
        left = (ow - new_w) // 2
        img = img.crop((left, 0, left + new_w, oh))
    else:
        # 너무 높음 → 위아래 잘라냄 (상단 30% 기준으로 약간 위쪽)
        new_h = int(ow / target_ratio)
        top = int((oh - new_h) * 0.3)
        img = img.crop((0, top, ow, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)

# 슬라이드용 이미지 검색어 목록 (슬라이드마다 다른 사진)
photo_queries = [
    f"{topic['image_search']} dark",         # 커버
    f"men grooming detail close up moody",   # 02
    f"men dark suit editorial portrait",     # 03
    f"perfume fragrance dark luxury minimal",# 04
    None,                                    # 마무리 (사진 불필요)
]

photos = []
print("📸 Pexels에서 이미지 검색 중...")
for q in photo_queries:
    if q:
        url = get_pexels_photo(q)
        if url:
            img = download_image(url)
            if img:
                img = smart_crop(img)
                photos.append(img)
                print(f"  ✅ '{q[:30]}' 이미지 확보")
                continue
    photos.append(None)
    if q:
        print(f"  ⚠️ '{q[:30]}' 대체 사용")

# ══════════════════════════════════════════════════════════════
# 5. 그림자 레이어 시스템 (7단 스택)
# ══════════════════════════════════════════════════════════════
def apply_shadow_stack(photo=None):
    """
    7단 그림자 레이어:
    1. 원본 사진 (or 잉크블랙 캔버스)
    2. 저채도·톤커브
    3. 잉크블랙 멀티플라이 오버레이
    4. 하단 롱 그라데이션 (35~55% 커버)
    5. 비네팅
    6. 필름 그레인
    → PIL RGB 1080×1440
    """
    if photo:
        # ① 저채도 처리
        arr = np.array(photo, dtype=np.float32)
        gray = 0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]
        # saturate ~20%
        sat = 0.22
        arr = gray[:,:,np.newaxis] * (1-sat) + arr * sat
        # 약간 어둡게
        arr *= 0.80
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
    else:
        # 사진 없으면 잉크블랙 그라데이션 캔버스
        arr = np.zeros((H, W, 3), dtype=np.float32)
        arr[:] = list(DARK)
        Xg, Yg = np.meshgrid(np.arange(W), np.arange(H))
        d = np.sqrt((Xg - W*0.6)**2 + (Yg - H*0.4)**2)
        g = np.clip(1 - d / (np.sqrt(W**2+H**2)*0.55), 0, 1) * 0.25
        arr[:,:,0] += g*55; arr[:,:,1] += g*35; arr[:,:,2] += g*12
        img = Image.fromarray(np.clip(arr,0,255).astype(np.uint8))

    # ③ 잉크블랙 멀티플라이 오버레이 (rgba alpha_composite)
    ov = Image.new("RGBA", (W, H), (*DARK, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle([(0,0),(W,H)], fill=(*DARK, 120))  # ~47% 오버레이
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    # ④ 하단 롱 그라데이션 (57%)
    scrim = Image.new("RGBA", (W, H), (0,0,0,0))
    sd = ImageDraw.Draw(scrim)
    sh = int(H * 0.57)
    for i in range(sh):
        t = i / sh
        a = int(250 * (1 - t**1.65))
        sd.line([(0, H-sh+i),(W, H-sh+i)], fill=(*DARK, a))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")

    # ⑤ 비네팅 (사각형 기반)
    vig = Image.new("RGBA", (W, H), (0,0,0,0))
    vd = ImageDraw.Draw(vig)
    steps = 55
    for k in range(steps, 0, -1):
        frac = k / steps
        a = int(195 * (1 - frac)**1.7)
        if a <= 0: continue
        mx = int(W * (1-frac) / 2)
        my = int(H * (1-frac) / 2)
        x0, y0, x1, y1 = mx, my, W-mx, H-my
        if x1 > x0 and y1 > y0:
            vd.rectangle([(x0,y0),(x1,y1)],
                          outline=(0,0,0,a), width=max(1, W//55))
    img = Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")

    # ⑥ 필름 그레인
    arr2 = np.array(img, dtype=np.int16)
    noise = np.random.randint(-15, 15, arr2.shape, dtype=np.int16)
    arr2 = np.clip(arr2 + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr2)

# ══════════════════════════════════════════════════════════════
# 6. 공통 UI 드로잉 함수
# ══════════════════════════════════════════════════════════════
def draw_header(draw, sec, vol):
    lf = fnt(SANS_MED, 30); vf = fnt(SANS_LT, 24)
    draw.text((MAR_X, MAR_Y), sec.upper(), font=lf, fill=GOLD)
    lw = tw(draw, sec.upper(), lf)
    ls = MAR_X + lw + 22
    le = W - MAR_X - 70
    draw.line([(ls, MAR_Y+17),(le, MAR_Y+17)], fill=(*GOLD_D, 155), width=2)
    draw.text((le+12, MAR_Y+5), vol, font=vf, fill=(*CREAM, 85))

def draw_sig(draw):
    sf = fnt(SERIF, 26)
    t = "bodetail"
    x = (W - tw(draw, t, sf)) // 2
    draw.text((x, H-58), t, font=sf, fill=(*CREAM, 72))

def numbox(img, draw, n, x, y):
    nf = fnt(SANS_BLK, 58)
    nw = tw(draw, n, nf); nh = th(draw, n, nf)
    px, py = 24, 12
    draw.rectangle([(x,y),(x+nw+px*2, y+nh+py*2)], fill=GOLD)
    draw.text((x+px, y+py), n, font=nf, fill=INK)
    return y + nh + py*2 + 24

def capbox(img, x, y, lines):
    cf = fnt(SANS_REG, 34)
    lh = th(ImageDraw.Draw(img), "가", cf) + 12
    bh = len(lines) * lh + 28
    ov = Image.new("RGBA", (W,H), (0,0,0,0))
    od = ImageDraw.Draw(ov)
    od.rectangle([(x,y),(W-MAR_X,y+bh)], fill=(*DARK, 168))
    od.rectangle([(x,y),(x+5,y+bh)], fill=(*GOLD,255))
    img2 = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    d2 = ImageDraw.Draw(img2)
    ty = y + 14
    for l in lines:
        d2.text((x+20, ty), l, font=cf, fill=WHITE)
        ty += lh
    return img2, d2, y + bh

def divline(draw, y):
    draw.line([(MAR_X,y),(W-MAR_X,y)], fill=(*GOLD_D,55), width=1)

# ══════════════════════════════════════════════════════════════
# 7. 슬라이드 렌더링
# ══════════════════════════════════════════════════════════════
def render_cover(slide_data, photo):
    img = apply_shadow_stack(photo)
    draw = ImageDraw.Draw(img)
    sec = content["section_label"]
    vol = content.get("vol", "VOL.01")
    draw_header(draw, sec, vol)

    # 배지
    bf = fnt(SANS_MED, 28)
    bt = "DETAIL INDEX"
    bw = tw(draw, bt, bf)
    bx, by = MAR_X, MAR_Y + 68
    draw.rectangle([(bx,by),(bx+bw+28, by+42)], outline=(*CREAM, 70), width=1)
    draw.text((bx+14, by+6), bt, font=bf, fill=(*CREAM, 100))

    # 보조줄
    sf2 = fnt(SANS_LT, 38)
    sub = slide_data.get("headline_sub", "")
    draw.text((MAR_X, MAR_Y+140), sub, font=sf2, fill=MUTED)

    # 메인 헤드라인
    mf = fnt(SANS_BLK, 112)
    lh = th(draw, "가", mf) + 10
    by2 = MAR_Y + 195
    for l in slide_data.get("headline_main", []):
        draw.text((MAR_X, by2), l, font=mf, fill=WHITE)
        by2 += lh

    # 서브 서리프
    srf = fnt(SERIF, 44)
    serif_txt = slide_data.get("headline_serif", "")
    draw.text((MAR_X, by2 + 10), serif_txt, font=srf, fill=(*CREAM, 175))

    draw_sig(draw)
    return img

def render_content(slide_data, photo):
    img = apply_shadow_stack(photo)
    draw = ImageDraw.Draw(img)
    sec = content["section_label"]
    vol = content.get("vol", "VOL.01")
    draw_header(draw, sec, vol)

    y = MAR_Y + 72
    n = slide_data.get("number", "")
    if n:
        y = numbox(img, draw, n, MAR_X, y)

    sbf = fnt(SANS_BOLD, 52)
    draw.text((MAR_X, y), slide_data.get("subhead",""), font=sbf, fill=CREAM)
    y += th(draw, "가", sbf) + 24

    bf = fnt(SANS_LT, 38)
    lh = th(draw, "가", bf) + 12
    for l in slide_data.get("body", []):
        if l: draw.text((MAR_X, y), l, font=bf, fill=MUTED)
        y += lh

    cap_txt = slide_data.get("caption", "")
    if cap_txt:
        cap_y = H - MAR_Y - 155
        img, draw, _ = capbox(img, MAR_X, cap_y, [cap_txt])

    draw_sig(draw)
    return img

def render_content_double(sd1, sd2, photo):
    """두 섹션을 한 슬라이드에 (03, 04형)"""
    img = apply_shadow_stack(photo)
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))

    sbf = fnt(SANS_BOLD, 48); bf = fnt(SANS_LT, 36); lh = th(draw,"가",bf)+12
    y = MAR_Y + 72

    for sd in [sd1, sd2]:
        if sd.get("number"):
            y = numbox(img, draw, sd["number"], MAR_X, y)
        draw.text((MAR_X, y), sd.get("subhead",""), font=sbf, fill=CREAM)
        y += th(draw, "가", sbf) + 20
        for l in sd.get("body", []):
            if l: draw.text((MAR_X, y), l, font=bf, fill=MUTED)
            y += lh
        if sd != [sd1, sd2][-1]:
            y += 16; divline(draw, y); y += 26

    draw_sig(draw)
    return img

def render_closing():
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    arr[:] = list(DARK)
    noise = np.random.randint(-8, 8, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16)+noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], "")

    wf = fnt(SERIF_B, 92); cf = fnt(SANS_LT, 32)
    wt = "bodetail"; ct = "Detail changes everything"
    ww = tw(draw, wt, wf); cw = tw(draw, ct, cf)
    cx = W // 2

    bw = 80
    by1 = H//2 - 100
    draw.rectangle([(cx-bw//2, by1),(cx+bw//2, by1+3)], fill=GOLD)
    wmy = H//2 - 78
    draw.text((cx - ww//2, wmy), wt, font=wf, fill=CREAM)
    wh = th(draw, wt, wf)
    by2 = wmy + wh + 16
    draw.rectangle([(cx-bw//2, by2),(cx+bw//2, by2+3)], fill=GOLD)
    draw.text((cx - cw//2, by2+22), ct, font=cf, fill=(72,66,60))
    return img

# ══════════════════════════════════════════════════════════════
# 8. 슬라이드 조합 & 저장
# ══════════════════════════════════════════════════════════════
slides_data = content.get("slides", [])
content_slides = [s for s in slides_data if s["type"] == "content"]

rendered = []

# 슬라이드 1: 커버
cover_data = next((s for s in slides_data if s["type"] == "cover"), {})
rendered.append(("01_커버", render_cover(cover_data, photos[0] if photos else None)))

# 콘텐츠 슬라이드 분배 (01~N번)
# 1개씩 또는 2개씩 묶어서 (총 슬라이드 수에 맞게)
i = 0
slide_idx = 2
while i < len(content_slides):
    s = content_slides[i]
    photo_idx = min(slide_idx - 1, len(photos) - 2)
    photo = photos[photo_idx] if photo_idx < len(photos) else None

    # 다음 슬라이드도 content이면 2개 묶기 (공간 여유 판단)
    if (i + 1 < len(content_slides) and
        len(content_slides) > topic['num_slides'] - 2):
        img = render_content_double(content_slides[i], content_slides[i+1], photo)
        lbl = f"{slide_idx:02d}_{s.get('number','')}-{content_slides[i+1].get('number','')}"
        rendered.append((lbl, img))
        i += 2
    else:
        img = render_content(s, photo)
        lbl = f"{slide_idx:02d}_{s.get('number',str(slide_idx))}"
        rendered.append((lbl, img))
        i += 1
    slide_idx += 1

# 마무리
rendered.append((f"{slide_idx:02d}_마무리", render_closing()))

# 저장
print(f"\n💾 PNG 저장 중 → {OUT}/")
for name, img in rendered:
    p = OUT / f"{name}_1080x1440.png"
    img.save(p, "PNG", optimize=True, compress_level=6)
    print(f"  ✅ {p.name}")

# 오늘자 latest 폴더에도 복사 (고정 경로)
latest = Path("posts/latest")
latest.mkdir(exist_ok=True)
for name, img in rendered:
    img.save(latest / f"{name}_1080x1440.png", "PNG")
(latest / "caption.txt").write_text(
    (OUT / "caption.txt").read_text("utf-8"), encoding="utf-8")

print(f"\n🎉 완료! {len(rendered)}장 생성 → posts/latest/ & {OUT}/")
print(f"📝 캡션: {OUT}/caption.txt")
