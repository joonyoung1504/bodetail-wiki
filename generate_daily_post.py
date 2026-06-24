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

★ 2026-06-24 업데이트 (텍스트 가독성 패치):
  1. apply_text_safezone() 신규 — 본문 슬라이드 상단~중단에 잉크블랙 안전지대
  2. 본문 글자색 MUTED(회색) → BODY_LIGHT(밝은 크림)
  3. 1슬라이드 1포인트 — render_content_double 자동 호출 비활성화
  4. render_closing() 에 CTA(@bodetail_official 팔로우) 추가
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
BODY_LIGHT=(212,206,194)   # ★추가: 본문용 밝은 크림 (실사 위에서 회색은 묻히므로 밝게)

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

# 섹션 라벨 한글 매핑 (커버 좌상단 + VOL 표기에 사용)
SECTION_KO = {
    "WHY":"오늘의 디테일", "DETAIL":"오늘의 디테일", "ROUTINE":"오늘의 루틴",
    "PICK":"오늘의 PICK", "KNOW":"오늘의 지식", "STYLE":"오늘의 스타일",
    "BODY":"오늘의 컨디션", "SCENE":"오늘의 준비"
}
# 커버 배지 영문 라벨 (섹션별)
SECTION_BADGE = {
    "WHY":"DETAIL INDEX", "DETAIL":"DETAIL INDEX", "ROUTINE":"ROUTINE INDEX",
    "PICK":"CURATION", "KNOW":"KNOWLEDGE", "STYLE":"STYLE NOTE",
    "BODY":"CONDITION", "SCENE":"FOR THE MOMENT"
}
sec_code = topic.get("section","DETAIL")
topic["section_label_ko"] = SECTION_KO.get(sec_code, "오늘의 디테일")
# 같은 섹션이 몇 번째로 등장하는지 = VOL 번호
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
- 이건 무드 매거진이다. 추상적 동기부여("관리하면 자존감이 올라간다")만 있으면 실패다.
- 각 슬라이드(number 슬라이드)는 다음 중 최소 하나를 담아라:
  (a) 구체적 실행 팁 — 당장 따라할 수 있는 행동/순서/수치
  (b) 의외의 정보·사실 — "몰랐던" 디테일, 흔한 오해 교정
  (c) 제품·도구 추천 또는 선택 기준 — 무엇을, 왜, 어떻게 고르는지
  (d) 기준·체크리스트 — 판단할 수 있는 명확한 잣대
- "왜 중요한가"는 1슬라이드면 충분. 나머지는 전부 "그래서 뭘 어떻게"로 채워라.
- 제목이 뻔하면(예: 외모관리가 자존감이다) 각도를 비틀어 구체적 정보로 만들어라.
  예: "거울 보는 습관"이 아니라 "거울 볼 때 체크하는 5포인트".
- 본문은 한 슬라이드당 2~3줄. 한 줄은 30자 이내 권장(자동 줄바꿈되지만 짧을수록 좋다).
- ★ 줄바꿈은 의미 단위로 끊어라. 한 단어만 다음 줄로 떨어지지 않게, body 배열의 각 원소가 자연스러운 한 호흡이 되게 하라.
- caption(슬라이드 하단 박스)은 그 슬라이드의 핵심을 한 문장으로 요약.

JSON 구조 (순수 JSON만, 코드블록 금지):
{{
  "section_label": "섹션 라벨",
  "vol": "VOL.01",
  "slides": [
    {{"slide_num": 1, "type": "cover",
      "headline_sub": "맥락 한 줄 (예: 면접 시즌 / 환절기)",
      "headline_main": ["메인", "헤드라인", "2~3줄"],
      "headline_serif": "구체적 약속 (예: 놓치기 쉬운 디테일 5)"}},
    {{"slide_num": 2, "type": "content", "number": "01",
      "subhead": "핵심 팁 제목 (정보가 담긴)",
      "body": ["구체적 내용 1", "구체적 내용 2"],
      "caption": "이 슬라이드 핵심 한 문장"}}
  ],
  "caption_full": "인스타 캡션. 첫 줄은 강한 후킹 한 문장(광고고지로 시작하지 말 것). 둘째 줄에 (광고 아님 · 저장 유도). 공감 도입 2줄, 관점 전환 1줄, 01~N 넘버링 요약, 마무리 슬로건, 댓글 유도 질문, @bodetail_official 팔로우 유도",
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
# 섹션 라벨/VOL은 우리가 계산한 값으로 강제 (Claude 출력 무시)
content["section_label"] = topic["section_label_ko"]
content["vol"] = topic["vol_no"]
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
    """CSS object-fit:cover 방식 — 빈 공간 없이 1080x1440 완전히 채움"""
    ow, oh = img.size
    target_ratio = target_w / target_h
    source_ratio = ow / oh
    # 1) 짧은 쪽을 타겟에 맞춰 업스케일 (항상 타겟보다 크거나 같게)
    scale = max(target_w / ow, target_h / oh)
    nw, nh = int(ow * scale + 1), int(oh * scale + 1)
    img = img.resize((nw, nh), Image.LANCZOS)
    # 2) 중앙(세로는 상단 35%) 기준 크롭
    left = (nw - target_w) // 2
    top  = int((nh - target_h) * 0.35)
    left = max(0, min(left, nw - target_w))
    top  = max(0, min(top,  nh - target_h))
    img = img.crop((left, top, left + target_w, top + target_h))
    return img

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
    잉크블랙 그림자 레이어 (numpy 기반, 칼선 없는 부드러운 페이드):
    1. 사진을 1080x1440 전체에 깔기 (cover) + 저채도
    2. 전체 높이 수직 그라데이션 (위는 살짝, 아래로 갈수록 짙게) — 칼선 제거
    3. 균일 잉크 틴트 (톤 통일)
    4. 부드러운 비네팅
    5. 필름 그레인
    → PIL RGB 1080x1440
    """
    if photo is not None:
        base = np.array(photo, dtype=np.float32)
        if base.shape[0] != H or base.shape[1] != W:
            photo = photo.resize((W, H), Image.LANCZOS)
            base = np.array(photo, dtype=np.float32)
        # 저채도 (흑백 22% 블렌드) + 살짝 어둡게
        gray = 0.299*base[:,:,0] + 0.587*base[:,:,1] + 0.114*base[:,:,2]
        sat = 0.30
        base = gray[:,:,None]*(1-sat) + base*sat
        base *= 0.92
    else:
        # 사진 없을 때: 잉크블랙 + 따뜻한 방사 글로우
        base = np.zeros((H, W, 3), dtype=np.float32)
        base[:] = list(DARK)
        Xg, Yg = np.meshgrid(np.arange(W), np.arange(H))
        d = np.sqrt((Xg - W*0.6)**2 + (Yg - H*0.4)**2)
        g = np.clip(1 - d/(np.sqrt(W**2+H**2)*0.55), 0, 1) * 0.22
        base[:,:,0] += g*55; base[:,:,1] += g*35; base[:,:,2] += g*12

    # ── 수직 페이드 마스크 (0=원본 유지, 1=완전 잉크) ──
    # 위 0%에서 시작해 아래로 갈수록 짙어짐. 부드러운 곡선이라 칼선 없음.
    yv = np.linspace(0, 1, H)[:, None]          # 0(위) → 1(아래)
    # 상단 28%까지는 거의 투명, 그 아래로 완만하게 상승, 하단은 강하게
    fade = np.clip((yv - 0.18) / 0.82, 0, 1) ** 1.45
    fade = fade * 0.82                            # 하단 최대 82% 잉크
    # 전체 균일 틴트도 살짝 (톤 통일)
    tint = 0.30
    total = np.clip(fade + tint, 0, 0.96)[:, :, None]  # (H,1,1) 브로드캐스트용
    total = np.repeat(total, W, axis=1)           # (H,W,1)

    ink = np.array(DARK, dtype=np.float32)[None, None, :]
    out = base*(1-total) + ink*total

    # ── 비네팅 (부드러운 방사) ──
    Xg, Yg = np.meshgrid(np.arange(W), np.arange(H))
    cx, cy = W/2, H/2
    dist = np.sqrt(((Xg-cx)/cx)**2 + ((Yg-cy)/cy)**2)   # 0(중앙)~~1.4(모서리)
    vig = np.clip((dist-0.65)/0.75, 0, 1) ** 1.6 * 0.55
    out = out * (1 - vig[:,:,None])

    out = np.clip(out, 0, 255).astype(np.uint8)
    img = Image.fromarray(out)

    # ── 필름 그레인 ──
    arr2 = np.array(img, dtype=np.int16)
    noise = np.random.randint(-12, 12, arr2.shape, dtype=np.int16)
    arr2 = np.clip(arr2 + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr2)

# ══════════════════════════════════════════════════════════════
# 5-B. ★추가: 본문 텍스트 안전지대 (Text Safe Zone)
# ══════════════════════════════════════════════════════════════
def apply_text_safezone(img, cover_to=0.58, strength=0.78):
    """
    ★ 본문 슬라이드 전용 텍스트 안전지대.
    apply_shadow_stack 의 그라데이션은 '하단'만 어둡게 하지만, 본문 텍스트는
    화면 '상단'부터 깔린다. 그 엇갈림 때문에 글자가 사진의 밝은 부분에 묻힌다.
    → 본문 텍스트가 놓이는 상단~중단을 잉크블랙으로 한 겹 더 덮어 가독을 확보한다.

    cover_to : 상단부터 이 비율까지는 균일하게 덮고, 그 아래로는 부드럽게 0으로 페이드.
    strength : 최대 불투명도(0~1). 높을수록 사진이 덜 비치고 글자가 또렷.
    """
    arr = np.array(img, dtype=np.float32)
    yv = np.linspace(0, 1, H)[:, None]                 # 0(위) → 1(아래)
    feather = 0.14                                     # 경계 부드럽게 (칼선 방지)
    m = np.where(
        yv < cover_to, 1.0,
        np.clip((cover_to + feather - yv) / feather, 0, 1)
    ).astype(np.float32)
    m = m * strength
    mask = np.repeat(m, W, axis=1)[:, :, None]          # (H,W,1)
    ink = np.array(DARK, dtype=np.float32)[None, None, :]
    out = arr * (1 - mask) + ink * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

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
    nf = fnt(SANS_BLK, 52)
    # 실제 글리프 bbox (offset 포함) 계산
    bb = draw.textbbox((0, 0), n, font=nf)
    gw = bb[2] - bb[0]
    gh = bb[3] - bb[1]
    px, py = 26, 16
    box_w = gw + px * 2
    box_h = gh + py * 2
    draw.rectangle([(x, y), (x + box_w, y + box_h)], fill=GOLD)
    # 글리프 offset(bb[0], bb[1])을 보정해 박스 정중앙에 배치
    tx = x + px - bb[0]
    ty = y + py - bb[1]
    draw.text((tx, ty), n, font=nf, fill=INK)
    return y + box_h + 24

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

def wrap_text(draw, text, font, max_width):
    """max_width(px)를 넘지 않게 자동 줄바꿈. 공백 단위 우선, 길면 글자 단위."""
    if text == "":
        return [""]
    words = text.split(" ")
    lines = []
    cur = ""
    for w in words:
        trial = w if cur == "" else cur + " " + w
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            # 단어 하나가 폭을 넘으면 글자 단위로 쪼갬
            if draw.textlength(w, font=font) > max_width:
                piece = ""
                for ch in w:
                    if draw.textlength(piece + ch, font=font) <= max_width:
                        piece += ch
                    else:
                        lines.append(piece)
                        piece = ch
                cur = piece
            else:
                cur = w
    if cur:
        lines.append(cur)
    return lines

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

    # 배지 (bbox 기반 상하좌우 균등 패딩)
    bf = fnt(SANS_MED, 24)
    bt = SECTION_BADGE.get(topic.get("section","DETAIL"), "DETAIL INDEX")
    bb = draw.textbbox((0, 0), bt, font=bf)
    gw = bb[2] - bb[0]
    gh = bb[3] - bb[1]
    pad_x, pad_y = 18, 12          # 좌우 18, 상하 12 균등
    bx, by = MAR_X, MAR_Y + 66
    box_w = gw + pad_x * 2
    box_h = gh + pad_y * 2
    draw.rectangle([(bx, by), (bx + box_w, by + box_h)],
                   outline=(*CREAM, 90), width=1)
    # 글리프 offset 보정해 박스 정중앙에
    draw.text((bx + pad_x - bb[0], by + pad_y - bb[1]), bt, font=bf, fill=(*CREAM, 120))

    # 보조줄
    sf2 = fnt(SANS_LT, 36)
    sub = slide_data.get("headline_sub", "")
    draw.text((MAR_X, MAR_Y+132), sub, font=sf2, fill=MUTED)

    # 메인 헤드라인 (자동 줄바꿈 + 폭 넘으면 폰트 축소)
    main_lines = slide_data.get("headline_main", [])
    if isinstance(main_lines, str):
        main_lines = [main_lines]
    max_w = W - MAR_X*2
    fsize = 104
    while fsize > 64:
        mf = fnt(SANS_BLK, fsize)
        wrapped = []
        for ln in main_lines:
            wrapped += wrap_text(draw, ln, mf, max_w)
        lh = int(fsize * 1.18)
        total_h = len(wrapped) * lh
        if total_h <= 560:
            break
        fsize -= 6
    by2 = MAR_Y + 188
    for l in wrapped:
        draw.text((MAR_X, by2), l, font=mf, fill=WHITE)
        by2 += lh

    # 서브 서리프 (한글 가능 Noto Serif, 골드)
    srf = fnt(SERIF, 40)
    serif_txt = slide_data.get("headline_serif", "")
    if serif_txt:
        for sl in wrap_text(draw, serif_txt, srf, max_w):
            draw.text((MAR_X, by2 + 14), sl, font=srf, fill=(*GOLD_BRIGHT, 220) if 'GOLD_BRIGHT' in globals() else (*CREAM,185))
            by2 += int(40*1.3)

    draw_sig(draw)
    return img

def render_content(slide_data, photo):
    img = apply_shadow_stack(photo)
    img = apply_text_safezone(img)          # ★추가: 본문 안전지대 (가독성 핵심)
    draw = ImageDraw.Draw(img)
    sec = content["section_label"]
    vol = content.get("vol", "VOL.01")
    draw_header(draw, sec, vol)

    y = MAR_Y + 80
    n = slide_data.get("number", "")
    if n:
        y = numbox(img, draw, n, MAR_X, y)

    sbf = fnt(SANS_BOLD, 50)
    max_w = W - MAR_X*2
    for sline in wrap_text(draw, slide_data.get("subhead",""), sbf, max_w):
        draw.text((MAR_X, y), sline, font=sbf, fill=CREAM)
        y += int(50*1.3)
    y += 12

    bf = fnt(SANS_LT, 36)
    lh = int(36 * 1.5)
    for raw in slide_data.get("body", []):
        if raw == "":
            y += int(lh*0.5)
            continue
        for bl in wrap_text(draw, raw, bf, max_w):
            draw.text((MAR_X, y), bl, font=bf, fill=BODY_LIGHT)   # ★변경: MUTED→BODY_LIGHT
            y += lh

    cap_txt = slide_data.get("caption", "")
    if cap_txt:
        cf = fnt(SANS_REG, 32)
        cap_lines = wrap_text(draw, cap_txt, cf, W - MAR_X*2 - 40)
        cap_h = len(cap_lines) * int(32*1.4) + 28
        cap_y = H - MAR_Y - cap_h - 20
        img, draw, _ = capbox(img, MAR_X, cap_y, cap_lines)

    draw_sig(draw)
    return img

def render_content_double(sd1, sd2, photo):
    """두 섹션을 한 슬라이드에 (★기본 비활성화 — 1슬라이드 1포인트 원칙).
       남겨두되 조합부에서 호출하지 않는다. 수동으로 쓸 때를 위해 안전지대는 적용."""
    img = apply_shadow_stack(photo)
    img = apply_text_safezone(img, cover_to=0.74, strength=0.78)   # ★추가
    draw = ImageDraw.Draw(img)
    draw_header(draw, content["section_label"], content.get("vol","VOL.01"))

    sbf = fnt(SANS_BOLD, 44); bf = fnt(SANS_LT, 33)
    lh = int(33 * 1.45)
    max_w = W - MAR_X*2
    y = MAR_Y + 80
    items = [sd1, sd2]
    for idx, sd in enumerate(items):
        if sd.get("number"):
            y = numbox(img, draw, sd["number"], MAR_X, y)
        for sline in wrap_text(draw, sd.get("subhead",""), sbf, max_w):
            draw.text((MAR_X, y), sline, font=sbf, fill=CREAM)
            y += int(44*1.3)
        y += 8
        for raw in sd.get("body", []):
            if raw == "":
                y += int(lh*0.5); continue
            for bl in wrap_text(draw, raw, bf, max_w):
                draw.text((MAR_X, y), bl, font=bf, fill=BODY_LIGHT)   # ★변경: MUTED→BODY_LIGHT
                y += lh
        if idx == 0:
            y += 22; divline(draw, y); y += 32

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

    wf = fnt(SERIF_B, 88); cf = fnt(SANS_LT, 30)
    wt = "bodetail"
    ct  = "남들이 놓치는 한 끗"                 # ★변경: 태그라인(한글 슬로건)
    cta = "@bodetail_official 팔로우"          # ★추가: CTA (팔로우 유도)
    cx = W // 2

    # 워드마크 실제 글리프 bbox로 정확한 높이/중앙 계산
    wbb = draw.textbbox((0,0), wt, font=wf)
    wgw = wbb[2]-wbb[0]; wgh = wbb[3]-wbb[1]
    cbb = draw.textbbox((0,0), ct, font=cf)
    cgw = cbb[2]-cbb[0]

    bar_w = 64
    gap = 40            # 바와 글자 사이 위/아래 동일 간격
    # 워드마크를 화면 정중앙에 배치
    wm_x = cx - wgw//2 - wbb[0]
    wm_y = H//2 - wgh//2 - wbb[1]
    # 워드마크의 화면상 실제 top/bottom
    wm_top = H//2 - wgh//2
    wm_bot = H//2 + wgh//2

    # 위 골드 바: 워드마크 top에서 gap 위
    top_bar_y = wm_top - gap
    draw.rectangle([(cx-bar_w//2, top_bar_y-2),(cx+bar_w//2, top_bar_y+1)], fill=GOLD)
    # 워드마크
    draw.text((wm_x, wm_y), wt, font=wf, fill=CREAM)
    # 아래 골드 바: 워드마크 bottom에서 gap 아래 (위와 동일 간격)
    bot_bar_y = wm_bot + gap
    draw.rectangle([(cx-bar_w//2, bot_bar_y-2),(cx+bar_w//2, bot_bar_y+1)], fill=GOLD)
    # 태그라인
    draw.text((cx - cgw//2 - cbb[0], bot_bar_y + 22), ct, font=cf, fill=(150,140,124))
    # ★추가: CTA (골드, 태그라인 아래)
    ctaf = fnt(SANS_MED, 30)
    ctab = draw.textbbox((0,0), cta, font=ctaf)
    ctaw = ctab[2]-ctab[0]
    draw.text((cx - ctaw//2 - ctab[0], bot_bar_y + 22 + 46), cta, font=ctaf, fill=GOLD_BRIGHT)
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
# ★변경: 1슬라이드 1포인트 — 항상 single 렌더 (render_content_double 자동 호출 비활성화)
i = 0
slide_idx = 2
while i < len(content_slides):
    s = content_slides[i]
    photo_idx = min(slide_idx - 1, len(photos) - 2)
    photo = photos[photo_idx] if photo_idx < len(photos) else None

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
