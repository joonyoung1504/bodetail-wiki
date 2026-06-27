"""
generate_daily_reel.py — bodetail 릴스 자동화 v3
B모드: 영상 Vision 분석 → 영상 내용 기반 자막/캡션/썸네일 완전 자동 생성
A모드: Pexels 스톡 영상 자동 처리
"""

import os, json, re, requests, subprocess, time, shutil, tempfile, base64
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

RW, RH = 1080, 1920
REEL_DURATION = 28
OUTRO_DURATION = 7

DARK=(8,6,4); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240)

SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

def fnt(p, s): return ImageFont.truetype(p, s)

ANTHROPIC_KEY = os.environ["ANTROPIC_API_KEY"]
PEXELS_KEY    = os.environ.get("PEXELS_API_KEY", "")
IG_USER_ID    = os.environ.get("IG_USER_ID", "")
IG_TOKEN      = os.environ.get("IG_ACCESS_TOKEN", "")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
REPO          = os.environ.get("REPO", "")

INBOX  = Path("videos/inbox")
USED_F = Path("content/used_reels.json")
OUT    = Path(f"reels/{DATE}")
OUT.mkdir(parents=True, exist_ok=True)
INBOX.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ══════════════════════════════════════════════════════════════
# 2. 모드 감지
# ══════════════════════════════════════════════════════════════
inbox_videos = (
    list(INBOX.glob("*.mp4")) +
    list(INBOX.glob("*.mov")) +
    list(INBOX.glob("*.MP4"))
)
MODE = "B" if inbox_videos else "A"
print(f"📱 모드: {'B (inbox 영상 분석)' if MODE == 'B' else 'A (Pexels 스톡)'}")

# A모드용 주제 로드
if MODE == "A":
    day_override = os.environ.get("DAY_OVERRIDE", "").strip()
    with open("content/topics_30.json", "r", encoding="utf-8") as f:
        schedule = json.load(f)
    if day_override:
        day_num = int(day_override)
    else:
        start_date = datetime(2026, 9, 15, tzinfo=KST)
        elapsed = max(0, (TODAY - start_date).days)
        day_num = (elapsed % 30) + 1
    topic = next(
        (t for t in schedule["topics"] if t["day"] == day_num),
        schedule["topics"][0]
    )
    print(f"📅 DAY {day_num} | {topic['title_main']}")

# ══════════════════════════════════════════════════════════════
# 3-B. 영상 Vision 분석 (B모드 핵심)
# ══════════════════════════════════════════════════════════════
def extract_frames_for_vision(video_path: Path, num_frames: int = 6) -> list:
    """영상에서 균등 간격으로 프레임 추출 → base64 반환"""
    frames = []
    duration = get_video_duration(video_path)
    interval = duration / (num_frames + 1)

    for i in range(1, num_frames + 1):
        t = interval * i
        frame_path = OUT / f"vision_frame_{i:02d}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(t),
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=540:960",
                str(frame_path)
            ], check=True, capture_output=True, timeout=15)

            if frame_path.exists():
                with open(frame_path, "rb") as f:
                    b64 = base64.standard_b64encode(f.read()).decode("utf-8")
                frames.append({"path": frame_path, "b64": b64, "time": t})
        except Exception as e:
            print(f"  ⚠️ 프레임 {i} 추출 실패: {e}")

    return frames

def analyze_video_with_vision(video_path: Path, credit_text: str) -> dict:
    """Claude Vision으로 영상 분석 → 자막/캡션/썸네일 생성"""
    print("  🔍 영상 프레임 추출 중...")
    frames = extract_frames_for_vision(video_path, num_frames=15)

    if not frames:
        print("  ⚠️ 프레임 추출 실패 → 기본 콘텐츠 생성")
        return make_content_without_vision(credit_text)

    print(f"  ✅ {len(frames)}개 프레임 추출 완료")

    # Vision 메시지 구성
    content = []
    content.append({
        "type": "text",
        "text": """이 릴스 영상 프레임들을 분석해서 bodetail 한국어 릴스 콘텐츠를 만들어줘.

bodetail은 한국 남성 그루밍·라이프스타일 브랜드야.
이 영상의 원본 영어 자막을 한국어로 번역해서 자막을 만들고,
영상 내용에 딱 맞는 캡션과 썸네일 헤드라인을 만들어.

★ 자막 원칙:
- 영상에 보이는 영어 텍스트/자막을 한국어로 그대로 번역
- 총 5~8개, 각 3~5초
- 한 줄 20자 이내
- 선언형/명령형 위주 (~해요 금지)
- 영상 흐름 순서대로

★ 썸네일 헤드라인:
- 숫자 포함 필수
- 클릭 유발하는 한 문장
- 섹션 라벨 (예: POSTURE, ROUTINE, DETAIL)

★ 캡션 (세르칸 스타일):
- 첫 줄: 강한 후킹 한 문장
- 둘째 줄: (광고 아님 · 영상 저장 추천 🔖)
- 번호별 핵심 내용 (1️⃣ 소제목\\n설명 형식, 영상 내용 기반으로)
- 출처 표기 줄
- "Start Every Detail with Awareness Now"
- "내 외모의 최고 버전이 궁금하다면? @bodetail_official"
- 해시태그 15~20개

순수 JSON만 출력 (코드블록 금지):
{
  "video_topic": "영상 주제 한 줄 요약",
  "thumbnail_headline": "클릭 유발 헤드라인 (숫자 포함)",
  "thumbnail_sub": "POSTURE",
  "best_frame_index": 2,
  "captions": [
    {"text": "한국어 자막", "duration": 4},
    {"text": "두번째 자막", "duration": 3}
  ],
  "caption_full": "캡션 전문 (\\n으로 줄바꿈)",
  "hashtags": "#bodetail #남자그루밍 ..."
}"""
    })

    # 프레임 이미지 추가
    for i, frame in enumerate(frames):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": frame["b64"]
            }
        })
        content.append({
            "type": "text",
            "text": f"[프레임 {i+1} / {len(frames)} — {frame['time']:.1f}초 지점]"
        })

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": content}]
    )

    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    result = json.loads(raw)

    print(f"  ✅ 영상 분석 완료: {result.get('video_topic', '')}")

    # 베스트 프레임 선택
    best_idx = result.get("best_frame_index", 1) - 1
    best_idx = max(0, min(best_idx, len(frames) - 1))
    result["best_frame_path"] = frames[best_idx]["path"]

    return result

# ══════════════════════════════════════════════════════════════
# 3-A. A모드 콘텐츠 생성 (topics_30 기반)
# ══════════════════════════════════════════════════════════════
def make_content_without_vision(source_info: str) -> dict:
    prompt = f"""너는 bodetail 인스타그램 릴스 편집자야.
주제: {topic['title_main'] if MODE == 'A' else '남성 라이프스타일'}
섹션: {topic['section'] if MODE == 'A' else 'LIFESTYLE'}
영상 소스: {source_info}

★ 자막 원칙:
- 총 5~7개, 각 3~5초, 한 줄 20자 이내
- 첫 자막 강한 후킹
- 선언형/명령형

★ 썸네일: 숫자 포함 헤드라인

★ 캡션: 세르칸 스타일
- 후킹 첫 줄
- (광고 아님 · 영상 저장 추천 🔖)
- 번호별 핵심 내용
- "Start Every Detail with Awareness Now"
- "내 외모의 최고 버전이 궁금하다면? @bodetail_official"
- 해시태그 15~20개

순수 JSON만 출력:
{{
  "video_topic": "주제 요약",
  "thumbnail_headline": "헤드라인",
  "thumbnail_sub": "DETAIL",
  "best_frame_index": 1,
  "captions": [{{"text": "자막", "duration": 4}}],
  "caption_full": "캡션 전문",
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
# 4-A. Pexels 영상 확보
# ══════════════════════════════════════════════════════════════
def load_used_reels():
    if USED_F.exists():
        try: return set(json.loads(USED_F.read_text("utf-8")))
        except: return set()
    return set()

def save_used_reels(ids: set):
    USED_F.parent.mkdir(parents=True, exist_ok=True)
    USED_F.write_text(json.dumps(list(ids)[-300:], ensure_ascii=False), encoding="utf-8")

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
                          key=lambda f: f.get("width",0)*f.get("height",0), reverse=True)
            if not files: continue
            url = files[0]["link"]
            if fallback is None: fallback = (vid_id, url)
            if vid_id not in used: return vid_id, url
        return fallback if fallback else (None, None)
    except Exception as e:
        print(f"⚠️ Pexels: {e}")
        return None, None

def download_video(url, out_path):
    try:
        r = requests.get(url, stream=True, timeout=60)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"⚠️ 다운로드 실패: {e}")
        return False

VIDEO_QUERIES = {
    "손톱": ["man hands nails closeup dark moody"],
    "핸드크림": ["man applying hand cream dark"],
    "면도": ["man shaving dark cinematic"],
    "향수": ["men cologne bottle dark cinematic"],
    "피부": ["man skincare dark editorial"],
    "헤어": ["man hair grooming dark"],
    "슈트": ["man suit dark cinematic"],
    "운동": ["man gym workout dark"],
}

def get_video_queries():
    title = topic.get("title_main", "")
    for kw, queries in VIDEO_QUERIES.items():
        if kw in title:
            return queries + ["man grooming dark moody"]
    img_search = topic.get("image_search", "man grooming")
    return [f"man {img_search} dark cinematic", "male dark editorial moody cinematic"]

# ══════════════════════════════════════════════════════════════
# 4-B. Inbox 처리
# ══════════════════════════════════════════════════════════════
def process_inbox():
    video = sorted(inbox_videos)[0]
    credit_f = video.parent / "credit.txt"
    credit = credit_f.read_text("utf-8").strip() if credit_f.exists() else ""
    return video, credit

# ══════════════════════════════════════════════════════════════
# 5. FFmpeg 유틸
# ══════════════════════════════════════════════════════════════
def get_video_duration(video_path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(video_path)
    ], capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return float(s.get("duration", REEL_DURATION))
    return REEL_DURATION

# ══════════════════════════════════════════════════════════════
# 6. ASS 자막 — 흰색 박스 + 검은 글씨 (상단 영어 자막 위치 덮기)
# ══════════════════════════════════════════════════════════════
def make_ass_file(captions: list, ass_path: str):
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
        # 흰색 박스(BorderStyle=4) + 검은 글씨 + 상단 배치(Alignment=8)
        "Style: Main,Noto Sans CJK KR,62,&H00000000,&H000000FF,"
        "&H00FFFFFF,&HFFFFFFFF,1,0,0,0,100,100,0,0,4,0,0,8,30,30,120,1\n\n"
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
        events.append(f"Dialogue: 0,{fmt(cur)},{fmt(cur+dur)},Main,,0,0,0,,{text}")
        cur += dur

    Path(ass_path).write_text(header + "\n".join(events), encoding="utf-8")
    return cur

# ══════════════════════════════════════════════════════════════
# 7. 아웃트로 이미지
# ══════════════════════════════════════════════════════════════
def make_outro_image() -> Path:
    img = Image.new("RGB", (RW, RH), DARK)
    arr = np.array(img, dtype=np.int16)
    noise = np.random.randint(-6, 6, arr.shape, dtype=np.int16)
    img = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)

    cx = RW // 2
    cy = RH // 2

    # ── 상단 골드 언더바 (중앙 정렬, 고정 길이) ──
    bar_w, bar_h = 60, 3
    draw.rectangle(
        [(cx - bar_w//2, cy - 180), (cx + bar_w//2, cy - 180 + bar_h)],
        fill=GOLD
    )

    # ── 메인 카피 ──
    cf = fnt(SANS_LT, 42)
    lines = ["남들이 놓치는 디테일이", "궁금하다면"]
    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=cf)
        w = bb[2] - bb[0]
        draw.text(((RW - w) // 2, cy - 148 + i * 58), line, font=cf, fill=(*CREAM, 230))

    # ── 하단 골드 언더바 (상단과 동일 크기/정렬) ──
    draw.rectangle(
        [(cx - bar_w//2, cy - 32), (cx + bar_w//2, cy - 32 + bar_h)],
        fill=GOLD
    )

    # ── CTA ──
    ctaf = fnt(SANS_MED, 34)
    cta = "@bodetail_official 팔로우"
    bb = draw.textbbox((0, 0), cta, font=ctaf)
    w = bb[2] - bb[0]
    draw.text(((RW - w) // 2, cy - 16), cta, font=ctaf, fill=(*GOLD_BRIGHT, 255))

    # ── 워드마크 ──
    wf = fnt(SERIF_B, 110)
    wt = "bodetail"
    bb = draw.textbbox((0, 0), wt, font=wf)
    w = bb[2] - bb[0]
    draw.text(((RW - w) // 2, cy + 60), wt, font=wf, fill=(*CREAM, 220))

    p = OUT / "outro.png"
    img.save(p, "PNG")
    return p

def make_wordmark_overlay() -> Path:
    overlay = Image.new("RGBA", (RW, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    sf = fnt(SANS_MED, 34)
    t = "bodetail"
    bb = draw.textbbox((0, 0), t, font=sf)
    w = bb[2] - bb[0]
    draw.text(((RW - w) // 2, 22), t, font=sf, fill=(*CREAM, 160))
    p = OUT / "wordmark.png"
    overlay.save(p, "PNG")
    return p

# ══════════════════════════════════════════════════════════════
# 8. FFmpeg 메인 파이프라인
# ══════════════════════════════════════════════════════════════
def build_reel(source_video: Path, ass_path: str,
               outro_img: Path, wordmark_img: Path) -> Path:
    processed = OUT / "processed.mp4"
    outro_vid = OUT / "outro.mp4"
    final     = OUT / "reel_final.mp4"

    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(source_video),
        "-i", str(wordmark_img),
        "-t", str(REEL_DURATION),
        "-filter_complex",
        (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1[base];"
            f"[base]ass={ass_path}[sub];"
            "[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]"
        ),
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(processed)
    ], check=True, capture_output=True, timeout=300)
    print("  ✅ 메인 영상 처리 완료")

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(outro_img),
        "-t", str(OUTRO_DURATION),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", "30", "-vf", "scale=1080:1920",
        "-movflags", "+faststart",
        str(outro_vid)
    ], check=True, capture_output=True, timeout=60)
    print("  ✅ 아웃트로 생성 완료")

    concat_f = OUT / "concat.txt"
    concat_f.write_text(
        f"file '{processed.resolve()}'\nfile '{outro_vid.resolve()}'\n",
        encoding="utf-8"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_f),
        "-c:v", "libx264", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(final)
    ], check=True, capture_output=True, timeout=120)
    print("  ✅ 최종 릴스 합성 완료")
    return final

# ══════════════════════════════════════════════════════════════
# 9. 썸네일 생성
# ══════════════════════════════════════════════════════════════
def make_thumbnail(headline: str, sub_label: str,
                   source_frame: Path = None) -> Path:
    W_T, H_T = 1080, 1440
    Xg, Yg = np.meshgrid(np.arange(W_T), np.arange(H_T))

    if source_frame and source_frame.exists():
        base = np.array(
            Image.open(source_frame).convert("RGB").resize((W_T, H_T), Image.LANCZOS),
            dtype=np.float32
        )
        gray = 0.299*base[:,:,0] + 0.587*base[:,:,1] + 0.114*base[:,:,2]
        base = gray[:,:,None]*0.55 + base*0.45
        base *= 0.82
    else:
        base = np.zeros((H_T, W_T, 3), dtype=np.float32)
        base[:] = list(DARK)
        d = np.sqrt(((Xg-W_T*0.5)/350.)**2 + ((Yg-H_T*0.55)/400.)**2)
        g = np.clip(1-d, 0, 1)*0.32
        base[:,:,0] += g*75; base[:,:,1] += g*62; base[:,:,2] += g*45

    ink = np.array(DARK, dtype=np.float32)[None,None,:]
    base = base*0.55 + ink*0.45

    yv = np.linspace(0, 1, H_T)[:,None]
    fade = np.clip((yv-0.38)/0.62, 0, 1)**1.4 * 0.78
    mask = np.repeat(fade[:,:,None], W_T, axis=1)
    base = base*(1-mask) + ink*mask

    cx, cy = W_T/2, H_T/2
    dist = np.sqrt(((Xg-cx)/cx)**2 + ((Yg-cy)/cy)**2)
    vig = np.clip((dist-0.5)/0.7, 0, 1)**1.5 * 0.55
    base = base*(1-vig[:,:,None])

    arr = np.clip(base, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    # 상단 라벨
    lf = fnt(SANS_MED, 28)
    draw.text((84, 88), "오늘의 디테일", font=lf, fill=GOLD)
    lw = draw.textlength("오늘의 디테일", font=lf)
    draw.line([(84+lw+20, 106), (W_T-84, 106)], fill=(*GOLD, 160), width=2)

    # 섹션 배지
    bf = fnt(SANS_MED, 24)
    bb = draw.textbbox((0,0), sub_label, font=bf)
    bw, bh = bb[2]-bb[0], bb[3]-bb[1]
    bx, by = 84, 148
    draw.rectangle([(bx, by), (bx+bw+32, by+bh+20)], outline=(*CREAM, 100), width=2)
    draw.text((bx+16-bb[0], by+10-bb[1]), sub_label, font=bf, fill=(*CREAM, 145))

    # 헤드라인
    max_w = W_T - 84*2
    fsize = 92
    while fsize > 56:
        mf = fnt(SANS_BLK, fsize)
        words = headline.split()
        lines_list = []; cur = ""
        for w in words:
            trial = w if cur == "" else cur + " " + w
            if draw.textlength(trial, font=mf) <= max_w: cur = trial
            else: lines_list.append(cur); cur = w
        if cur: lines_list.append(cur)
        lh = int(fsize * 1.18)
        if len(lines_list) * lh <= 380: break
        fsize -= 6

    block_h = len(lines_list) * lh
    y = H_T - 88 - block_h - 8
    for line in lines_list:
        draw.text((84, y), line, font=mf, fill=WHITE)
        y += lh

    # 하단 서명
    sf = fnt(SANS_MED, 26)
    t = "bodetail"
    sw = draw.textlength(t, font=sf)
    draw.text(((W_T-sw)//2, H_T-58), t, font=sf, fill=(*CREAM, 190))

    p = OUT / "thumbnail_1080x1440.png"
    img.save(p, "PNG")
    return p

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
# 10. Instagram 게시
# ══════════════════════════════════════════════════════════════
def upload_to_github_release(filepath: Path, filename: str):
    if not GITHUB_TOKEN or not REPO: return None
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
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
    upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={filename}"
    with open(filepath, "rb") as f:
        r = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            data=f, timeout=300
        )
    if r.status_code in (200, 201):
        return r.json().get("browser_download_url")
    print(f"⚠️ 업로드 실패: {r.status_code}")
    return None

def post_reel_to_instagram(video_url, thumb_url, caption) -> bool:
    if not IG_USER_ID or not IG_TOKEN:
        print("⚠️ IG 미설정 → 건너뜀")
        return False
    BASE = "https://graph.facebook.com/v18.0"
    r = requests.post(f"{BASE}/{IG_USER_ID}/media", params={
        "media_type": "REELS", "video_url": video_url,
        "cover_url": thumb_url, "caption": caption,
        "access_token": IG_TOKEN
    }, timeout=60)
    if r.status_code != 200:
        print(f"⚠️ 컨테이너 실패: {r.text[:200]}")
        return False
    container_id = r.json().get("id")
    for attempt in range(60):
        time.sleep(10)
        code = requests.get(f"{BASE}/{container_id}", params={
            "fields": "status_code", "access_token": IG_TOKEN
        }, timeout=30).json().get("status_code", "")
        print(f"    [{attempt+1}/60] {code}")
        if code == "FINISHED": break
        if code in ("ERROR", "EXPIRED"): return False
    else:
        return False
    pub = requests.post(f"{BASE}/{IG_USER_ID}/media_publish", params={
        "creation_id": container_id, "access_token": IG_TOKEN
    }, timeout=30)
    if pub.status_code == 200:
        print(f"  ✅ 게시 완료!")
        return True
    return False

# ══════════════════════════════════════════════════════════════
# 11. 메인 실행
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print(f"🎬 bodetail 릴스 자동화 v3 | {DATE} | 모드 {MODE}")
print("="*60)

with tempfile.TemporaryDirectory() as tmpdir:
    raw_video = Path(tmpdir) / "source.mp4"
    credit_text = ""
    used_ids = load_used_reels()
    content = {}

    if MODE == "B":
        src, credit_text = process_inbox()
        shutil.copy(src, raw_video)
        print(f"📂 inbox 영상: {src.name}")

        print("\n🔍 Claude Vision 영상 분석 중...")
        content = analyze_video_with_vision(raw_video, credit_text)

    else:
        queries = get_video_queries()
        vid_id, vid_url = None, None
        for q in queries:
            vid_id, vid_url = search_pexels_video(q)
            if vid_id: break
        if not vid_id:
            print("⚠️ Pexels 영상 없음 → 검정 배경 대체")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "color=c=black:size=1080x1920:r=30",
                "-t", str(REEL_DURATION), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", str(raw_video)
            ], capture_output=True, timeout=60)
        else:
            print(f"📸 Pexels 영상 (ID: {vid_id})")
            used_ids.add(str(vid_id))
            download_video(vid_url, raw_video)
        credit_text = "Pexels (상업적 무료)"
        content = make_content_without_vision(credit_text)

    # 캡션 완성
    captions_data = content["captions"]
    credit_line = f"\n\n📹 | {credit_text}" if credit_text else ""
    caption_full = (
        f"{content['caption_full']}\n\n"
        f"{content['hashtags']}"
        f"{credit_line}\n\n"
        f"Start Every Detail with Awareness Now\n"
        f"—\n"
        f"내 외모의 최고 버전이 궁금하다면? @bodetail_official"
    )
    (OUT / "caption.txt").write_text(caption_full, encoding="utf-8")
    print(f"  ✅ 자막 {len(captions_data)}개 생성")

    # ASS 자막
    ass_path = str(OUT / "subtitles.ass")
    total_cap_dur = make_ass_file(captions_data, ass_path)
    print(f"  ✅ ASS 자막 ({total_cap_dur:.1f}초) — 흰박스/검은글씨/상단")

    # 이미지 에셋
    print("\n🎨 이미지 에셋 생성 중...")
    outro_img    = make_outro_image()
    wordmark_img = make_wordmark_overlay()

    # 썸네일 — 베스트 프레임 사용
    best_frame = content.get("best_frame_path")
    if best_frame is None:
        frame_path = OUT / "frame.jpg"
        best_frame = extract_frame(raw_video, frame_path, t=3.0)

    thumb = make_thumbnail(
        headline=content["thumbnail_headline"],
        sub_label=content.get("thumbnail_sub", "DETAIL"),
        source_frame=best_frame
    )
    print("  ✅ 썸네일 생성 (베스트 프레임)")

    # FFmpeg
    print("\n🎬 FFmpeg 영상 처리 중...")
    final_reel = build_reel(raw_video, ass_path, outro_img, wordmark_img)
    size_mb = final_reel.stat().st_size // 1024 // 1024
    print(f"  ✅ 완성: {final_reel.name} ({size_mb}MB)")

    save_used_reels(used_ids)

    # latest 복사
    latest = Path("reels/latest")
    latest.mkdir(exist_ok=True)
    shutil.copy(final_reel, latest / "reel_final.mp4")
    shutil.copy(thumb, latest / "thumbnail_1080x1440.png")
    (latest / "caption.txt").write_text(caption_full, encoding="utf-8")

    # B모드 done 이동
    if MODE == "B":
        done_dir = INBOX / "done"
        done_dir.mkdir(exist_ok=True)
        for f in inbox_videos:
            shutil.move(str(f), str(done_dir / f.name))
        credit_f = inbox_videos[0].parent / "credit.txt"
        if credit_f.exists():
            shutil.move(str(credit_f), str(done_dir / "credit.txt"))
        print("  ✅ inbox → done/ 이동")

    # IG 게시
    if IG_USER_ID and IG_TOKEN and GITHUB_TOKEN:
        print("\n📤 인스타그램 게시 준비...")
        vid_url_pub = upload_to_github_release(final_reel, f"reel_{DATE}.mp4")
        thumb_url_pub = upload_to_github_release(thumb, f"thumb_{DATE}.png")
        if vid_url_pub:
            post_reel_to_instagram(vid_url_pub, thumb_url_pub, caption_full)
        else:
            print("  ⚠️ 공개 URL 실패 → 수동 업로드")
    else:
        print("\n💡 IG 미설정 → reels/latest/ 파일 확인")

print(f"\n🎉 완료! reels/latest/")
print(f"📝 캡션: {OUT}/caption.txt")
