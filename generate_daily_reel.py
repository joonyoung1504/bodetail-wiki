"""
generate_daily_reel.py — bodetail 일일 릴스 완전 자동화
=====================================================================
모드 A: Pexels 스톡 영상 → 자막·합성·게시 완전 자동 (손 0%)
모드 B: 준영님이 videos/inbox/에 영상+credit.txt 넣으면 → 자동 처리

모드 자동 판별: inbox에 파일 있으면 B, 없으면 A

결과물: reels/YYYY-MM-DD/ 폴더
  ├── reel_final.mp4       ← 인스타 게시용 완성 릴스 (9:16)
  ├── thumbnail_1080x1440.png ← 썸네일
  └── caption.txt          ← 캡션 + 해시태그

필요한 GitHub Secrets:
  ANTHROPIC_API_KEY   — Claude
  PEXELS_API_KEY      — Pexels 사진/영상
  IG_USER_ID          — 인스타그램 비즈니스 계정 ID
  IG_ACCESS_TOKEN     — 메타 Graph API 토큰 (60일 갱신 필요)
  GITHUB_TOKEN        — 자동 제공 (영상 임시 공개 URL용)
  REPO                — "joonyoung1504/bodetail-wiki"

의존성: pip install anthropic requests Pillow numpy
시스템: sudo apt-get install -y ffmpeg fonts-noto-cjk
"""

import os, json, re, requests, io, subprocess, time, shutil, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import anthropic

# ══════════════════════════════════════════════════════════════
# 1. 설정
# ══════════════════════════════════════════════════════════════
KST   = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)
DATE  = TODAY.strftime("%Y-%m-%d")

# 릴스 규격 (인스타그램 네이티브 세로)
RW, RH = 1080, 1920   # 9:16
REEL_DURATION = 28    # 자막 구간 (초) — 아웃트로 7초 별도
OUTRO_DURATION = 7    # 아웃트로 CTA (초)

# 컬러
DARK=(8,6,4); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240)

# 폰트
SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

def fnt(p, s): return ImageFont.truetype(p, s)

# API 키
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
PEXELS_KEY     = os.environ.get("PEXELS_API_KEY", "")
IG_USER_ID     = os.environ.get("IG_USER_ID", "")
IG_TOKEN       = os.environ.get("IG_ACCESS_TOKEN", "")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
REPO           = os.environ.get("REPO", "")

# 디렉토리
INBOX   = Path("videos/inbox")
USED_F  = Path("content/used_reels.json")
OUT     = Path(f"reels/{DATE}")
OUT.mkdir(parents=True, exist_ok=True)
INBOX.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ══════════════════════════════════════════════════════════════
# 2. 모드 감지 (A vs B)
# ══════════════════════════════════════════════════════════════
inbox_videos = list(INBOX.glob("*.mp4")) + list(INBOX.glob("*.mov")) + list(INBOX.glob("*.MP4"))
MODE = "B" if inbox_videos else "A"
print(f"📱 모드: {'B (inbox 영상)' if MODE == 'B' else 'A (Pexels 스톡)'}")

# 주제 로드 (이미지 파이프라인과 공유)
day_override = os.environ.get("DAY_OVERRIDE", "").strip()
with open("content/topics_30.json", "r", encoding="utf-8") as f:
    schedule = json.load(f)
if day_override:
    day_num = int(day_override)
else:
    start_date = datetime(2026, 9, 15, tzinfo=KST)
    elapsed = max(0, (TODAY - start_date).days)
    day_num = (elapsed % 30) + 1
topic = next((t for t in schedule["topics"] if t["day"] == day_num), schedule["topics"][0])
print(f"📅 DAY {day_num} | {topic['title_main']}")

# ══════════════════════════════════════════════════════════════
# 3. Claude — 자막 + 캡션 생성
# ══════════════════════════════════════════════════════════════
def make_content(source_info: str) -> dict:
    """Claude로 자막 텍스트, 캡션, 해시태그 생성"""
    prompt = f"""너는 bodetail 인스타그램 릴스 편집자야.
오늘 릴스의 주제와 영상 소스를 보고, 릴스에 올릴 콘텐츠를 JSON으로만 출력해.

주제: {topic['title_main']}
섹션: {topic['section']}
영상 소스 정보: {source_info}
릴스 길이: {REEL_DURATION}초 (아웃트로 {OUTRO_DURATION}초 별도)

★★ 자막(captions) 원칙 ★★
- 총 5~7개, 각 자막이 화면에 머무는 시간은 3~5초
- 각 자막은 한 줄, 20자 이내의 임팩트 있는 키 메시지
- 첫 자막이 가장 강한 후킹 (예: "이거 모르면 손해임")
- 정보형 + 행동 유발형 교차
- "~해요" 금지, 선언형/명령형 위주 ("바로 이게 차이다", "손끝이 전부다")
- 세르칸처럼: 핵심 키워드 + 숫자 + 임팩트

★★ 썸네일 헤드라인 원칙 ★★
- 그리드에서 클릭을 부르는 한 문장
- 숫자 포함 필수 (예: "손 관리 7초 루틴", "아무도 안 알려준 디테일 5")
- 좌하단 섹션 라벨도 짧게 (예: "DETAIL", "ROUTINE")

★★ 캡션 원칙 ★★
- 첫 줄: 강한 후킹 (광고고지 금지)
- 둘째 줄: (광고 아님 · 영상 저장 추천 🔖)
- 본문: 핵심 정보 3줄
- 출처: {source_info}
- 시그니처: "Start Every Detail with Awareness Now"
- CTA: @bodetail_official 팔로우
- 해시태그: 15~20개 남자그루밍 관련

순수 JSON만 출력 (코드블록 금지):
{{
  "thumbnail_headline": "그리드 클릭 유발 헤드라인",
  "thumbnail_sub": "DETAIL",
  "captions": [
    {{"text": "자막 텍스트", "duration": 4}},
    {{"text": "두번째 자막", "duration": 3}}
  ],
  "caption_full": "인스타 캡션 전문",
  "hashtags": "#bodetail #남자그루밍 ..."
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

# ══════════════════════════════════════════════════════════════
# 4-A. Pexels 영상 확보 (모드 A)
# ══════════════════════════════════════════════════════════════
def load_used_reels():
    if USED_F.exists():
        try: return set(json.loads(USED_F.read_text("utf-8")))
        except: return set()
    return set()

def save_used_reels(ids: set):
    USED_F.parent.mkdir(parents=True, exist_ok=True)
    lst = list(ids)[-300:]
    USED_F.write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")

MALE_FILTER = {"woman","women","female","girl","nail","ring","flower","feminine"}

def sanitize_q(q):
    words = q.lower().split()
    words = [w for w in words if w not in MALE_FILTER]
    if not any(w in {"man","male","men"} for w in words):
        words = ["man"] + words
    if not any(w in {"dark","moody","cinematic","editorial"} for w in words):
        words += ["dark"]
    return " ".join(words[:5])

def search_pexels_video(query) -> tuple:
    if not PEXELS_KEY: return None, None
    q = sanitize_q(query)
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": q, "per_page": 15, "orientation": "portrait", "size": "large"},
            timeout=15
        )
        videos = r.json().get("videos", [])
        used = load_used_reels()
        fallback = None
        for v in videos:
            vid_id = str(v["id"])
            files = sorted(v.get("video_files", []),
                          key=lambda f: f.get("width", 0) * f.get("height", 0), reverse=True)
            if not files: continue
            url = files[0]["link"]
            if fallback is None: fallback = (vid_id, url)
            if vid_id not in used:
                return vid_id, url
        return fallback if fallback else (None, None)
    except Exception as e:
        print(f"⚠️ Pexels video({q[:20]}): {e}")
        return None, None

def download_video(url, out_path):
    try:
        r = requests.get(url, stream=True, timeout=60)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"⚠️ 영상 다운로드 실패: {e}")
        return False

# 주제별 영상 검색 쿼리 (SUBJECT_RULES와 유사)
VIDEO_QUERIES = {
    "손톱": ["man hands nails closeup dark moody", "male hands dark cinematic"],
    "핸드크림": ["man applying hand cream dark", "male hands moisturizer moody"],
    "면도": ["man shaving dark cinematic", "male grooming razor moody"],
    "향수": ["men cologne bottle dark cinematic", "male perfume luxury moody"],
    "피부": ["man skincare dark editorial", "male face skin closeup moody"],
    "헤어": ["man hair grooming dark", "male hairstyle cinematic moody"],
    "슈트": ["man suit dark cinematic", "male formal editorial"],
    "운동": ["man gym workout dark", "male fitness cinematic moody"],
}

def get_video_queries():
    """주제 키워드 기반 최적 검색어 반환"""
    title = topic.get("title_main", "")
    for kw, queries in VIDEO_QUERIES.items():
        if kw in title:
            return queries + [f"man dark cinematic {kw}", "man grooming dark moody"]
    img_search = topic.get("image_search", "man grooming")
    return [
        f"man {img_search} dark cinematic",
        f"male {img_search} moody",
        "man grooming lifestyle dark",
        "male dark editorial moody cinematic",
    ]

# ══════════════════════════════════════════════════════════════
# 4-B. Inbox 영상 처리 (모드 B)
# ══════════════════════════════════════════════════════════════
def process_inbox():
    """inbox 폴더의 가장 오래된 영상 파일과 credit.txt 읽기"""
    video = sorted(inbox_videos)[0]
    credit_f = video.parent / "credit.txt"
    credit = credit_f.read_text("utf-8").strip() if credit_f.exists() else ""
    return video, credit

# ══════════════════════════════════════════════════════════════
# 5. FFmpeg — 영상 처리 파이프라인
# ══════════════════════════════════════════════════════════════
def get_duration(video_path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(video_path)
    ], capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return float(s.get("duration", REEL_DURATION))
    return REEL_DURATION

def make_ass_file(captions: list, ass_path: str):
    """ASS 자막 파일 생성 — 한글 안전"""
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Main,Noto Sans CJK KR,68,&H00FFFFFF,&H000000FF,"
        "&H00000000,&HC0000000,1,0,0,0,100,100,0,0,3,3,0,2,40,40,80,1\n"
        "Style: Small,Noto Sans CJK KR,48,&H00EDE6D8,&H000000FF,"
        "&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,2,0,2,40,40,60,1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )

    def fmt(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    events = []
    cur = 0.0
    for c in captions:
        dur = float(c.get("duration", 4))
        text = c["text"].replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{fmt(cur)},{fmt(cur+dur)},Main,,0,0,0,,{text}"
        )
        cur += dur

    Path(ass_path).write_text(header + "\n".join(events), encoding="utf-8")
    return cur  # 총 자막 길이 반환

def make_outro_image() -> Path:
    """아웃트로 CTA 이미지 (Pillow) — 세르칸 마지막 장 스타일"""
    img = Image.new("RGB", (RW, RH), DARK)
    draw = ImageDraw.Draw(img)

    arr = np.array(img, dtype=np.int16)
    noise = np.random.randint(-6, 6, arr.shape, dtype=np.int16)
    img = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)

    cx = RW // 2
    # 상단 골드 바
    bar_w = 80
    draw.rectangle([(cx-bar_w//2, RH//2-160), (cx+bar_w//2, RH//2-157)], fill=GOLD)

    # 메인 카피
    cf = fnt(SANS_LT, 44)
    line1 = "남들이 놓치는 디테일이"
    line2 = "궁금하다면"
    for i, line in enumerate([line1, line2]):
        bb = draw.textbbox((0,0), line, font=cf)
        w = bb[2]-bb[0]
        draw.text(((RW-w)//2, RH//2-130 + i*56), line, font=cf, fill=(*CREAM, 230))

    # 하단 골드 바
    draw.rectangle([(cx-bar_w//2, RH//2-24), (cx+bar_w//2, RH//2-21)], fill=GOLD)

    # CTA
    ctaf = fnt(SANS_MED, 36)
    cta = "@bodetail_official 팔로우"
    bb = draw.textbbox((0,0), cta, font=ctaf)
    draw.text(((RW-bb[2]+bb[0])//2, RH//2+8), cta, font=ctaf, fill=(*tuple(GOLD_BRIGHT), 255))

    # 워드마크 대형
    wf = fnt(SERIF_B, 120)
    wt = "bodetail"
    bb = draw.textbbox((0,0), wt, font=wf)
    wx = (RW-bb[2]+bb[0])//2
    wy = RH//2 + 100
    draw.text((wx, wy), wt, font=wf, fill=(*CREAM, 220))

    p = OUT / "outro.png"
    img.save(p, "PNG")
    return p

def make_wordmark_overlay() -> Path:
    """매 프레임 하단 중앙에 표시할 반투명 워드마크 이미지"""
    overlay = Image.new("RGBA", (RW, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    sf = fnt(SANS_MED, 34)
    t = "bodetail"
    bb = draw.textbbox((0,0), t, font=sf)
    w = bb[2]-bb[0]
    draw.text(((RW-w)//2, 22), t, font=sf, fill=(*CREAM, 160))
    p = OUT / "wordmark.png"
    overlay.save(p, "PNG")
    return p

def build_reel(source_video: Path, ass_path: str,
               outro_img: Path, wordmark_img: Path,
               subtitle_duration: float) -> Path:
    """FFmpeg 메인 파이프라인 — 크롭→자막→워드마크→아웃트로 합성"""
    processed = OUT / "processed.mp4"
    outro_vid = OUT / "outro.mp4"
    final     = OUT / "reel_final.mp4"

    src_duration = get_duration(source_video)
    # 원본 영상에서 쓸 길이: 자막 구간 (원본이 짧으면 루프)
    use_dur = min(float(REEL_DURATION), src_duration)

    # ── Step 1: 원본 영상 크롭 + 자막 + 워드마크 ──
    # 9:16으로 크롭, 자막 삽입, 하단 워드마크 오버레이
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",        # 짧은 영상 루프
        "-i", str(source_video),
        "-i", str(wordmark_img),
        "-t", str(REEL_DURATION),
        "-filter_complex",
        (
            # 1) 9:16 크롭
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1[base];"
            # 2) 자막 (ASS)
            f"[base]ass={ass_path}[sub];"
            # 3) 워드마크 오버레이 (하단 중앙, y=1920-100)
            "[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]"
        ),
        "-map", "[out]",
        "-map", "0:a?",             # 오디오 있으면 포함
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(processed)
    ]
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True, timeout=300)
    print("  ✅ 메인 영상 처리 완료")

    # ── Step 2: 아웃트로 이미지 → 영상 변환 ──
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(outro_img),
        "-t", str(OUTRO_DURATION),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-vf", "scale=1080:1920",
        "-movflags", "+faststart",
        str(outro_vid)
    ], check=True, capture_output=True, timeout=60)
    print("  ✅ 아웃트로 영상 생성 완료")

    # ── Step 3: 메인 + 아웃트로 concat ──
    # concat list 파일
    concat_f = OUT / "concat.txt"
    concat_f.write_text(
        f"file '{processed.resolve()}'\nfile '{outro_vid.resolve()}'\n",
        encoding="utf-8"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_f),
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(final)
    ], check=True, capture_output=True, timeout=120)
    print("  ✅ 최종 릴스 합성 완료")

    return final

# ══════════════════════════════════════════════════════════════
# 6. 썸네일 생성 (Pillow — 이미지 파이프라인과 동일 무드)
# ══════════════════════════════════════════════════════════════
def make_thumbnail(headline: str, sub_label: str,
                   source_frame: Path = None) -> Path:
    """그리드 썸네일 — 1080×1440, 무드 배경 + 헤드라인"""
    W_T, H_T = 1080, 1440

    if source_frame and source_frame.exists():
        base = np.array(Image.open(source_frame).convert("RGB").resize((W_T, H_T), Image.LANCZOS), dtype=np.float32)
        gray = 0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base = gray[:,:,None]*0.62 + base*0.38
        base *= 0.88
    else:
        base = np.zeros((H_T, W_T, 3), dtype=np.float32)
        base[:] = list(DARK)
        Xg, Yg = np.meshgrid(np.arange(W_T), np.arange(H_T))
        d = np.sqrt(((Xg-W_T*0.5)/350.)**2+((Yg-H_T*0.55)/400.)**2)
        g = np.clip(1-d,0,1)*0.32
        base[:,:,0]+=g*75; base[:,:,1]+=g*62; base[:,:,2]+=g*45

    # 잉크 틴트
    ink = np.array(DARK, dtype=np.float32)[None,None,:]
    base = base*0.58 + ink*0.42

    # 하단 그라데이션
    yv = np.linspace(0,1,H_T)[:,None]
    fade = np.clip((yv-0.42)/0.58,0,1)**1.5*0.72
    mask = np.repeat(fade[:,:,None],W_T,axis=1)
    base = base*(1-mask)+ink*mask

    # 비네팅
    cx, cy = W_T/2, H_T/2
    dist = np.sqrt(((Xg-cx)/cx)**2+((Yg-cy)/cy)**2)
    vig = np.clip((dist-0.55)/0.75,0,1)**1.5*0.60
    base = base*(1-vig[:,:,None])

    arr = np.clip(base,0,255).astype(np.uint8)
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    # 상단 라벨
    lf = fnt(SANS_MED, 30)
    draw.text((84, 92), "오늘의 디테일", font=lf, fill=GOLD)
    lw = draw.textlength("오늘의 디테일", font=lf)
    draw.line([(84+lw+24, 110), (W_T-84-86, 110)], fill=(*GOLD, 180), width=2)

    # 섹션 배지
    bf = fnt(SANS_MED, 26)
    bb = draw.textbbox((0,0), sub_label, font=bf)
    bw, bh = bb[2]-bb[0], bb[3]-bb[1]
    bx, by = 84, 160
    draw.rectangle([(bx, by), (bx+bw+36, by+bh+24)], outline=(*CREAM, 110), width=2)
    draw.text((bx+18-bb[0], by+12-bb[1]), sub_label, font=bf, fill=(*CREAM, 155))

    # 하단 헤드라인 (크게)
    max_w = W_T - 84*2
    fsize = 96
    while fsize > 58:
        mf = fnt(SANS_BLK, fsize)
        words = headline.split()
        lines = []; cur = ""
        for w in words:
            trial = w if cur == "" else cur + " " + w
            if draw.textlength(trial, font=mf) <= max_w: cur = trial
            else: lines.append(cur); cur = w
        if cur: lines.append(cur)
        lh = int(fsize * 1.16)
        if len(lines) * lh <= 360: break
        fsize -= 6

    block_h = len(lines) * lh
    y = H_T - 92 - block_h - 8
    for l in lines:
        draw.text((84, y), l, font=mf, fill=WHITE)
        y += lh

    # 하단 서명
    sf = fnt(SANS_MED, 28)
    t = "bodetail"
    sw = draw.textlength(t, font=sf)
    draw.text(((W_T-sw)//2, H_T-62), t, font=sf, fill=(*CREAM, 200))

    p = OUT / "thumbnail_1080x1440.png"
    img.save(p, "PNG")
    return p

# ══════════════════════════════════════════════════════════════
# 7. 영상에서 첫 프레임 추출 (썸네일용)
# ══════════════════════════════════════════════════════════════
def extract_frame(video_path: Path, out_path: Path, t: float = 1.0):
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(t),
            "-i", str(video_path), "-frames:v", "1",
            "-vf", "scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440",
            str(out_path)
        ], check=True, capture_output=True, timeout=30)
        return out_path if out_path.exists() else None
    except:
        return None

# ══════════════════════════════════════════════════════════════
# 8. Instagram Graph API 게시
# ══════════════════════════════════════════════════════════════
def upload_to_github_release(filepath: Path, filename: str) -> str | None:
    """GitHub Release에 파일 업로드 → 공개 다운로드 URL 반환"""
    if not GITHUB_TOKEN or not REPO:
        return None
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    # temp-reels 릴리즈 찾기 or 생성
    releases = requests.get(
        f"https://api.github.com/repos/{REPO}/releases",
        headers=headers, timeout=15
    ).json()
    temp_r = next((r for r in releases if r.get("tag_name") == "temp-reels"), None)
    if not temp_r:
        temp_r = requests.post(
            f"https://api.github.com/repos/{REPO}/releases",
            headers=headers, timeout=15,
            json={"tag_name": "temp-reels", "name": "Temp Reel Storage",
                  "body": "자동 릴스 업로드 임시 저장소", "draft": False, "prerelease": True}
        ).json()
    release_id = temp_r["id"]
    # 기존 동명 파일 삭제
    assets = requests.get(
        f"https://api.github.com/repos/{REPO}/releases/{release_id}/assets",
        headers=headers, timeout=15
    ).json()
    for a in assets:
        if a.get("name") == filename:
            requests.delete(
                f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}",
                headers=headers, timeout=15
            )
    # 업로드
    upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={filename}"
    with open(filepath, "rb") as f:
        r = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            data=f, timeout=300
        )
    if r.status_code in (200, 201):
        return r.json().get("browser_download_url")
    print(f"⚠️ GitHub Release 업로드 실패: {r.status_code}")
    return None

def post_reel_to_instagram(video_url: str, thumb_url: str, caption: str) -> bool:
    """Instagram Graph API로 릴스 게시"""
    if not IG_USER_ID or not IG_TOKEN:
        print("⚠️ IG_USER_ID 또는 IG_ACCESS_TOKEN 없음 → 게시 건너뜀")
        return False
    BASE = "https://graph.facebook.com/v18.0"

    # Step 1: 미디어 컨테이너 생성
    print("  📤 인스타그램 미디어 컨테이너 생성 중...")
    r = requests.post(
        f"{BASE}/{IG_USER_ID}/media",
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "cover_url": thumb_url,
            "caption": caption,
            "access_token": IG_TOKEN
        }, timeout=60
    )
    if r.status_code != 200:
        print(f"⚠️ 컨테이너 생성 실패: {r.text[:200]}")
        return False
    container_id = r.json().get("id")
    print(f"  컨테이너 ID: {container_id}")

    # Step 2: 처리 완료 대기 (최대 10분)
    print("  ⏳ 영상 처리 대기 중...")
    for attempt in range(60):
        time.sleep(10)
        status_r = requests.get(
            f"{BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
            timeout=30
        )
        status = status_r.json()
        code = status.get("status_code", "")
        print(f"    [{attempt+1}/60] {code}")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            print(f"⚠️ 영상 처리 오류: {status}")
            return False
    else:
        print("⚠️ 처리 시간 초과")
        return False

    # Step 3: 게시
    print("  🚀 게시 중...")
    pub_r = requests.post(
        f"{BASE}/{IG_USER_ID}/media_publish",
        params={"creation_id": container_id, "access_token": IG_TOKEN},
        timeout=30
    )
    if pub_r.status_code == 200:
        post_id = pub_r.json().get("id", "")
        print(f"  ✅ 게시 완료! Post ID: {post_id}")
        return True
    else:
        print(f"⚠️ 게시 실패: {pub_r.text[:200]}")
        return False

# ══════════════════════════════════════════════════════════════
# 9. 메인 파이프라인 실행
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print(f"🎬 bodetail 릴스 자동화 | {DATE} | 모드 {MODE}")
print("="*60)

# ── 영상 소스 확보 ──
with tempfile.TemporaryDirectory() as tmpdir:
    raw_video = Path(tmpdir) / "source.mp4"
    credit_text = ""
    used_ids = load_used_reels()

    if MODE == "B":
        src, credit_text = process_inbox()
        shutil.copy(src, raw_video)
        print(f"📂 inbox 영상 사용: {src.name}")
        if credit_text:
            print(f"   출처: {credit_text}")
    else:
        queries = get_video_queries()
        vid_id, vid_url = None, None
        for q in queries:
            vid_id, vid_url = search_pexels_video(q)
            if vid_id: break
        if not vid_id:
            print("⚠️ Pexels 영상 없음 → 검정 배경으로 대체")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=black:size=1080x1920:r=30",
                "-t", str(REEL_DURATION), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", str(raw_video)
            ], capture_output=True, timeout=60)
        else:
            print(f"📸 Pexels 영상 확보 (ID: {vid_id})")
            used_ids.add(str(vid_id))
            download_video(vid_url, raw_video)
        credit_text = "Pexels (상업적 무료)"

    source_info = credit_text or "Pexels 무료 스톡"

    # ── Claude 콘텐츠 생성 ──
    print("\n🤖 Claude 콘텐츠 생성 중...")
    content = make_content(source_info)
    captions_data = content["captions"]
    caption_full = f"{content['caption_full']}\n\n{content['hashtags']}"
    if credit_text:
        caption_full += f"\n\n🎥 | {credit_text}"
    caption_full += "\n\nStart Every Detail with Awareness Now — @bodetail_official"
    (OUT / "caption.txt").write_text(caption_full, encoding="utf-8")
    print(f"  ✅ 자막 {len(captions_data)}개 생성")

    # ── ASS 자막 파일 ──
    ass_path = str(OUT / "subtitles.ass")
    total_cap_dur = make_ass_file(captions_data, ass_path)
    print(f"  ✅ ASS 자막 파일 생성 ({total_cap_dur:.1f}초)")

    # ── 아웃트로 + 워드마크 이미지 ──
    print("\n🎨 이미지 에셋 생성 중...")
    outro_img   = make_outro_image()
    wordmark_img = make_wordmark_overlay()
    print("  ✅ 아웃트로 + 워드마크 생성")

    # ── 썸네일 ──
    frame_path = OUT / "frame.jpg"
    frame = extract_frame(raw_video, frame_path)
    thumb = make_thumbnail(
        headline=content["thumbnail_headline"],
        sub_label=content.get("thumbnail_sub", "DETAIL"),
        source_frame=frame
    )
    print(f"  ✅ 썸네일 생성")

    # ── FFmpeg 파이프라인 ──
    print("\n🎬 FFmpeg 영상 처리 중...")
    final_reel = build_reel(
        source_video=raw_video,
        ass_path=ass_path,
        outro_img=outro_img,
        wordmark_img=wordmark_img,
        subtitle_duration=total_cap_dur
    )
    print(f"  ✅ 최종 릴스: {final_reel.name} ({final_reel.stat().st_size//1024//1024}MB)")

    # ── 사용 이력 저장 ──
    save_used_reels(used_ids)

    # ── latest 폴더 업데이트 ──
    latest = Path("reels/latest")
    latest.mkdir(exist_ok=True)
    shutil.copy(final_reel, latest / "reel_final.mp4")
    shutil.copy(thumb, latest / "thumbnail_1080x1440.png")
    (latest / "caption.txt").write_text(caption_full, encoding="utf-8")

    # ── B 모드: 처리 완료된 inbox 영상 이동 ──
    if MODE == "B":
        done_dir = INBOX / "done"
        done_dir.mkdir(exist_ok=True)
        for f in inbox_videos:
            shutil.move(str(f), str(done_dir / f.name))
        credit_f = inbox_videos[0].parent / "credit.txt"
        if credit_f.exists():
            shutil.move(str(credit_f), str(done_dir / "credit.txt"))
        print("  ✅ Inbox 영상 → done/ 이동")

    # ── Instagram 게시 ──
    if IG_USER_ID and IG_TOKEN and GITHUB_TOKEN:
        print("\n📤 인스타그램 게시 준비 중...")
        vid_public_url = upload_to_github_release(final_reel, f"reel_{DATE}.mp4")
        thumb_public_url = upload_to_github_release(thumb, f"thumb_{DATE}.png")
        if vid_public_url:
            print(f"  공개 URL: {vid_public_url[:60]}...")
            success = post_reel_to_instagram(vid_public_url, thumb_public_url, caption_full)
            if not success:
                print("  ⚠️ 게시 실패 — reels/latest/ 파일로 수동 업로드하세요")
        else:
            print("  ⚠️ 공개 URL 생성 실패 — 수동 업로드 필요")
    else:
        print("\n💡 IG_USER_ID / IG_ACCESS_TOKEN 미설정 → reels/latest/에 파일 생성됨")
        print("   나중에 Secrets 추가하면 자동 게시됩니다")

print(f"\n🎉 완료! reels/latest/ & {OUT}/")
print(f"📝 캡션: {OUT}/caption.txt")
