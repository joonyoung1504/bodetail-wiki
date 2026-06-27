"""
generate_daily_reel.py — bodetail 릴스 자동화 v5
B모드: 타임라인 자막 감지 → 영어 자막 위치·타이밍에 흰박스+한국어 덮기
A모드: Pexels 스톡
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
REEL_DURATION_A = 28      # A모드(Pexels) 길이
OUTRO_DURATION  = 7

DARK=(8,6,4); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240)

SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

# 한국어 자막용 폰트 (PIL 측정 + ASS 렌더 동일 계열)
KO_SUB_FONT_FILE = SANS_BOLD
KO_SUB_FONT_NAME = "Noto Sans CJK KR"
KO_SUB_SIZE      = 52

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
    list(INBOX.glob("*.MP4")) +
    list(INBOX.glob("*.MOV"))
)
MODE = "B" if inbox_videos else "A"
print(f"📱 모드: {'B (inbox 영상 분석)' if MODE == 'B' else 'A (Pexels 스톡)'}")

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
# 3. FFmpeg 유틸
# ══════════════════════════════════════════════════════════════
def get_video_duration(video_path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(video_path)
    ], capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            d = s.get("duration")
            if d: return float(d)
    # format duration fallback
    result2 = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path)
    ], capture_output=True, text=True, timeout=30)
    fmt = json.loads(result2.stdout).get("format", {})
    return float(fmt.get("duration", 20.0))

def normalize_video(src: Path) -> Path:
    """원본 → 1080x1920 크롭 (길이·오디오 유지)"""
    out = OUT / "normalized.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
               "crop=1080:1920,setsar=1",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out)
    ], check=True, capture_output=True, timeout=300)
    return out

# ══════════════════════════════════════════════════════════════
# 4-B. Inbox 처리
# ══════════════════════════════════════════════════════════════
def process_inbox():
    video = max(inbox_videos, key=lambda f: f.stat().st_mtime)
    credit_f   = video.parent / "credit.txt"
    headline_f = video.parent / "headline.txt"
    credit   = credit_f.read_text("utf-8").strip()   if credit_f.exists()   else ""
    headline = headline_f.read_text("utf-8").strip() if headline_f.exists() else ""
    print(f"  선택된 영상: {video.name}")
    if headline:
        print(f"  📝 수동 헤드라인: {headline}")
    return video, credit, headline

# ══════════════════════════════════════════════════════════════
# 5. 타임라인 프레임 추출
# ══════════════════════════════════════════════════════════════
def extract_timeline_frames(video_path: Path, interval: float = 1.0) -> list:
    """1초 간격으로 프레임 추출 (540x960, 좌표는 ×2하면 1080x1920)"""
    duration = get_video_duration(video_path)
    n = int(duration / interval)
    n = max(8, min(n, 40))
    step = duration / n
    frames = []
    for i in range(n):
        t = step * i + step * 0.5
        fp = OUT / f"tl_{i:02d}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{t:.2f}",
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=540:960",
                str(fp)
            ], check=True, capture_output=True, timeout=15)
            if fp.exists():
                with open(fp, "rb") as f:
                    b64 = base64.standard_b64encode(f.read()).decode("utf-8")
                frames.append({"index": i, "path": fp, "b64": b64, "time": round(t, 2)})
        except Exception as e:
            print(f"  ⚠️ 프레임 {i} 실패: {e}")
    return frames

# ══════════════════════════════════════════════════════════════
# 6. Vision STEP 1 — 프레임별 텍스트·위치 감지
# ══════════════════════════════════════════════════════════════
def detect_subtitles_timeline(frames: list) -> list:
    print("  🔍 자막 위치·타이밍 분석 중...")

    content = [{
        "type": "text",
        "text": """이 프레임들은 한 영상을 시간 순서대로 1초 간격으로 캡처한 거야.
각 이미지 크기는 540x960 (세로 9:16)이야.

각 프레임에서 '영상에 박혀있는 자막/텍스트'를 찾아줘.
(영어 자막, 한국어 자막, 노란 박스 텍스트 등 화면에 표시된 모든 글자)

- 텍스트가 있으면 그 글자 덩어리를 감싸는 박스 좌표를 540x960 기준으로 알려줘
- 박스는 글자보다 약간 넉넉하게 (좌우상하 여백 포함)
- 같은 자막이 여러 프레임에 걸쳐 나오면 매 프레임 동일 텍스트로 표기
- 화면에 글자가 여러 줄/여러 위치면 box를 가장 바깥으로 크게 잡아

순수 JSON만 출력 (코드블록·설명 금지):
{
  "frames": [
    {"i": 0, "has_text": true, "text": "감지된 글자 전체", "box": {"x": 40, "y": 130, "w": 460, "h": 70}},
    {"i": 1, "has_text": false, "text": "", "box": null}
  ]
}"""
    }]

    for fr in frames:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": fr["b64"]}
        })
        content.append({"type": "text", "text": f"[프레임 i={fr['index']} / {fr['time']}초]"})

    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=4000,
        messages=[{"role": "user", "content": content}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    data = json.loads(raw)

    # 좌표 ×2 (540x960 → 1080x1920)
    detected = {}
    for fr in data.get("frames", []):
        if fr.get("has_text") and fr.get("box"):
            b = fr["box"]
            detected[fr["i"]] = {
                "text": fr.get("text", "").strip(),
                "box": {
                    "x": int(b["x"]*2), "y": int(b["y"]*2),
                    "w": int(b["w"]*2), "h": int(b["h"]*2)
                }
            }
    print(f"  ✅ 텍스트 감지 프레임: {len(detected)}개")
    return detected

# ══════════════════════════════════════════════════════════════
# 7. 자막 구간 묶기
# ══════════════════════════════════════════════════════════════
def _norm_text(t: str) -> str:
    return re.sub(r'[^a-z0-9가-힣]', '', t.lower())

def _similar(a: str, b: str) -> bool:
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb: return False
    if na == nb: return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    return short in long and len(short) >= max(4, len(long)*0.5)

def build_segments(detected: dict, frames: list) -> list:
    """연속 동일 텍스트 프레임 → 하나의 자막 구간"""
    seq = [(fr["index"], fr["time"]) for fr in frames]
    step = frames[1]["time"] - frames[0]["time"] if len(frames) > 1 else 1.0

    segments = []
    cur = None
    for idx, t in seq:
        d = detected.get(idx)
        if d is None:
            if cur: segments.append(cur); cur = None
            continue
        if cur and _similar(cur["text_en"], d["text"]):
            cur["end"] = t + step*0.5
            # box 합집합
            cb, nb = cur["en_box"], d["box"]
            x1 = min(cb["x"], nb["x"]); y1 = min(cb["y"], nb["y"])
            x2 = max(cb["x"]+cb["w"], nb["x"]+nb["w"])
            y2 = max(cb["y"]+cb["h"], nb["y"]+nb["h"])
            cur["en_box"] = {"x": x1, "y": y1, "w": x2-x1, "h": y2-y1}
            if len(d["text"]) > len(cur["text_en"]):
                cur["text_en"] = d["text"]
        else:
            if cur: segments.append(cur)
            cur = {
                "text_en": d["text"],
                "en_box": dict(d["box"]),
                "start": max(0, t - step*0.5),
                "end": t + step*0.5
            }
    if cur: segments.append(cur)

    # 너무 짧은 구간 최소 1.2초 보장
    for s in segments:
        if s["end"] - s["start"] < 1.2:
            s["end"] = s["start"] + 1.2
    print(f"  ✅ 자막 구간: {len(segments)}개")
    return segments

# ══════════════════════════════════════════════════════════════
# 8. Vision STEP 2 — 번역 + 캡션 + 썸네일
# ══════════════════════════════════════════════════════════════
def translate_and_generate(segments: list, frames: list,
                           headline_override: str, credit_text: str) -> dict:
    print("  🤖 번역·캡션 생성 중...")

    en_list = "\n".join([f"{i+1}. {s['text_en']}" for i, s in enumerate(segments)])

    hint = ""
    if headline_override:
        hint = f'\n★ thumbnail_headline 은 반드시 이 문장 그대로 써: "{headline_override}"'

    content = [{
        "type": "text",
        "text": f"""너는 bodetail 한국 남성 그루밍·라이프스타일 릴스 편집자야.

아래는 영상에서 시간순으로 감지된 자막 {len(segments)}개야:
{en_list}

각 자막을 자연스러운 한국어로 번역하고, 캡션·썸네일을 만들어줘.

★ 번역(translations) 원칙:
- 위 자막과 정확히 같은 개수, 같은 순서로 번역
- 직역투 절대 금지. 한국 인스타 릴스 톤, 짧고 임팩트
- 한 줄 18자 이내 (길면 자연스럽게 2줄 가능, \\n 사용)
- 선언형/명령형 (~해요/~합니다 금지, ~다/~하라/~된다 체)
- 영상에 이미 한국어가 있으면 그 뉘앙스 살려서 다듬기

★ 썸네일 헤드라인:
- 부담스러운 큰 숫자(100번 등) 쓰지 마. 매력·결과 중심 카피
- 좋은 예: "굽은 자세는 매력을 깎는다", "하루 10분 자세 교정", "등이 펴지면 인상이 산다"{hint}

★ 캡션은 아래 형식 그대로 (이 부분 품질이 중요):
- 첫 줄: 강한 후킹 질문
- (광고 아님 · 영상 저장 추천 🔖)
- 도입 1~2문장
- 번호별 핵심 (①②③… 소제목 — 설명)
- 해시태그 15~20개 (남성 그루밍·자세·자기관리)

순수 JSON만 출력 (코드블록 금지):
{{
  "video_topic": "영상 주제 한 줄",
  "thumbnail_headline": "썸네일 큰 글씨",
  "thumbnail_sub": "POSTURE",
  "best_frame_time": 5.0,
  "translations": ["한국어 자막1", "한국어 자막2"],
  "caption_full": "캡션 전문",
  "hashtags": "#bodetail #남자그루밍 ..."
}}

best_frame_time: 인물/핵심이 잘 보이는 프레임의 초 단위 시점."""
    }]

    # 맥락용 대표 프레임 5장
    pick = frames[::max(1, len(frames)//5)][:5]
    for fr in pick:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": fr["b64"]}
        })
        content.append({"type": "text", "text": f"[{fr['time']}초]"})

    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=3000,
        messages=[{"role": "user", "content": content}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    result = json.loads(raw)

    # 번역 개수 맞추기
    trans = result.get("translations", [])
    for i, s in enumerate(segments):
        s["text_ko"] = trans[i] if i < len(trans) else s["text_en"]

    if headline_override:
        result["thumbnail_headline"] = headline_override

    print(f"  ✅ 생성 완료: {result.get('video_topic','')}")
    return result

# ══════════════════════════════════════════════════════════════
# 9. 자막 박스 레이아웃 계산 (흰박스 + 한국어 위치)
# ══════════════════════════════════════════════════════════════
def layout_segment(seg: dict) -> dict:
    ko = seg["text_ko"].replace("\\n", "\n")
    font = fnt(KO_SUB_FONT_FILE, KO_SUB_SIZE)
    dummy = Image.new("RGB", (10,10)); dd = ImageDraw.Draw(dummy)

    # 줄 단위 (명시적 \n 우선, 아니면 자동 wrap)
    if "\n" in ko:
        lines = ko.split("\n")
    else:
        # 18자 넘으면 두 줄로
        if len(ko) > 18:
            mid = len(ko)//2
            sp = ko.rfind(" ", 0, mid+4)
            if sp == -1: sp = mid
            lines = [ko[:sp].strip(), ko[sp:].strip()]
        else:
            lines = [ko]

    line_h = int(KO_SUB_SIZE * 1.25)
    text_w = max(dd.textlength(l, font=font) for l in lines)
    text_h = line_h * len(lines)

    pad_x, pad_y = 44, 26
    eb = seg["en_box"]
    box_w = int(max(eb["w"], text_w) + pad_x*2)
    box_h = int(max(eb["h"], text_h) + pad_y*2)

    # 중심은 영어 자막 중심
    cx = eb["x"] + eb["w"]/2
    cy = eb["y"] + eb["h"]/2

    box_x = int(cx - box_w/2)
    box_y = int(cy - box_h/2)
    # 화면 안으로 clamp
    box_x = max(8, min(box_x, RW - box_w - 8))
    box_y = max(8, min(box_y, RH - box_h - 8))
    box_w = min(box_w, RW - 16)
    cx = box_x + box_w/2
    cy = box_y + box_h/2

    seg["draw_box"] = {"x": box_x, "y": box_y, "w": box_w, "h": box_h}
    seg["ko_pos"]   = (int(cx), int(cy))
    seg["ko_lines"] = lines
    return seg

# ══════════════════════════════════════════════════════════════
# 10. ASS 자막 (라인별 \pos, 검은 글씨)
# ══════════════════════════════════════════════════════════════
def build_ass(segments: list, ass_path: str):
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: KO,{KO_SUB_FONT_NAME},{KO_SUB_SIZE},&H00000000,&H000000FF,"
        "&H00FFFFFF,&H00FFFFFF,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    def fmt(t):
        h=int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h}:{m:02d}:{s:05.2f}"

    events = []
    for s in segments:
        cx, cy = s["ko_pos"]
        text = "\\N".join(s["ko_lines"])
        events.append(
            f"Dialogue: 0,{fmt(s['start'])},{fmt(s['end'])},KO,,0,0,0,,"
            f"{{\\pos({cx},{cy})\\an5}}{text}"
        )
    Path(ass_path).write_text(header + "\n".join(events), encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# 11. drawbox 필터 (영어 자막 영역 흰색 덮기)
# ══════════════════════════════════════════════════════════════
def build_drawbox_chain(segments: list) -> str:
    parts = []
    for s in segments:
        b = s["draw_box"]
        parts.append(
            f"drawbox=x={b['x']}:y={b['y']}:w={b['w']}:h={b['h']}:"
            f"color=white@1.0:t=fill:"
            f"enable='between(t,{s['start']:.2f},{s['end']:.2f})'"
        )
    return ",".join(parts)

# ══════════════════════════════════════════════════════════════
# 12. A모드 콘텐츠
# ══════════════════════════════════════════════════════════════
def make_content_without_vision(source_info: str) -> dict:
    prompt = f"""너는 bodetail 인스타그램 릴스 편집자야.
주제: {topic['title_main'] if MODE=='A' else '남성 라이프스타일'}
섹션: {topic['section'] if MODE=='A' else 'LIFESTYLE'}
영상 소스: {source_info}

★ 자막: 총 5~7개, 각 3~5초, 18자 이내, 선언형
★ 썸네일: 부담스러운 큰 숫자 금지, 매력·결과형 카피
★ 캡션: 후킹 첫 줄 / (광고 아님 · 영상 저장 추천 🔖) / 번호별 핵심 / 해시태그 15~20개

순수 JSON:
{{
  "video_topic":"주제","thumbnail_headline":"헤드라인","thumbnail_sub":"DETAIL",
  "captions":[{{"text":"자막","duration":4}}],
  "caption_full":"캡션","hashtags":"#bodetail ..."
}}"""
    msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=2048,
        messages=[{"role":"user","content":prompt}])
    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*','',raw); raw = re.sub(r'\s*```$','',raw)
    return json.loads(raw)

def make_ass_simple(captions, ass_path):
    """A모드용 하단 자막"""
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Main,{KO_SUB_FONT_NAME},58,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H64000000,1,0,0,0,100,100,0,0,1,3,2,2,40,40,170,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    def fmt(t):
        h=int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h}:{m:02d}:{s:05.2f}"
    ev=[]; cur=0.0
    for c in captions:
        dur=float(c.get("duration",4)); txt=c["text"].replace("\n","\\N")
        ev.append(f"Dialogue: 0,{fmt(cur)},{fmt(cur+dur)},Main,,0,0,0,,{txt}")
        cur+=dur
    Path(ass_path).write_text(header+"\n".join(ev), encoding="utf-8")
    return cur

# ══════════════════════════════════════════════════════════════
# 13. Pexels (A모드)
# ══════════════════════════════════════════════════════════════
def load_used_reels():
    if USED_F.exists():
        try: return set(json.loads(USED_F.read_text("utf-8")))
        except: return set()
    return set()
def save_used_reels(ids):
    USED_F.parent.mkdir(parents=True, exist_ok=True)
    USED_F.write_text(json.dumps(list(ids)[-300:], ensure_ascii=False), encoding="utf-8")
MALE_FILTER={"woman","women","female","girl","nail","ring","flower","feminine"}
def sanitize_q(q):
    w=[x for x in q.lower().split() if x not in MALE_FILTER]
    if not any(x in {"man","male","men"} for x in w): w=["man"]+w
    if not any(x in {"dark","moody","cinematic","editorial"} for x in w): w+=["dark"]
    return " ".join(w[:5])
def search_pexels_video(query):
    if not PEXELS_KEY: return None,None
    try:
        r=requests.get("https://api.pexels.com/videos/search",
            headers={"Authorization":PEXELS_KEY},
            params={"query":sanitize_q(query),"per_page":15,"orientation":"portrait","size":"large"},
            timeout=15)
        vids=r.json().get("videos",[]); used=load_used_reels(); fb=None
        for v in vids:
            vid=str(v["id"])
            files=sorted(v.get("video_files",[]),key=lambda f:f.get("width",0)*f.get("height",0),reverse=True)
            if not files: continue
            url=files[0]["link"]
            if fb is None: fb=(vid,url)
            if vid not in used: return vid,url
        return fb if fb else (None,None)
    except Exception as e:
        print(f"⚠️ Pexels: {e}"); return None,None
def download_video(url,out):
    try:
        r=requests.get(url,stream=True,timeout=60)
        with open(out,"wb") as f:
            for ch in r.iter_content(chunk_size=1024*1024): f.write(ch)
        return True
    except Exception as e:
        print(f"⚠️ 다운로드 실패: {e}"); return False
VIDEO_QUERIES={"손톱":["man hands nails closeup dark moody"],"핸드크림":["man applying hand cream dark"],
    "면도":["man shaving dark cinematic"],"향수":["men cologne bottle dark cinematic"],
    "피부":["man skincare dark editorial"],"헤어":["man hair grooming dark"],
    "슈트":["man suit dark cinematic"],"운동":["man gym workout dark"]}
def get_video_queries():
    title=topic.get("title_main","")
    for kw,q in VIDEO_QUERIES.items():
        if kw in title: return q+["man grooming dark moody"]
    return [f"man {topic.get('image_search','grooming')} dark cinematic","male dark editorial moody"]

# ══════════════════════════════════════════════════════════════
# 14. 아웃트로 + 워드마크
# ══════════════════════════════════════════════════════════════
def make_outro_image() -> Path:
    img = Image.new("RGB",(RW,RH),DARK)
    arr=np.array(img,dtype=np.int16)
    img=Image.fromarray(np.clip(arr+np.random.randint(-6,6,arr.shape,dtype=np.int16),0,255).astype(np.uint8))
    draw=ImageDraw.Draw(img); cx=RW//2; cy=RH//2; bw,bh=60,3
    draw.rectangle([(cx-bw//2,cy-180),(cx+bw//2,cy-180+bh)],fill=GOLD)
    cf=fnt(SANS_LT,42)
    for i,line in enumerate(["남들이 놓치는 디테일이","궁금하다면"]):
        bb=draw.textbbox((0,0),line,font=cf); w=bb[2]-bb[0]
        draw.text(((RW-w)//2,cy-148+i*58),line,font=cf,fill=(*CREAM,230))
    draw.rectangle([(cx-bw//2,cy-32),(cx+bw//2,cy-32+bh)],fill=GOLD)
    ctaf=fnt(SANS_MED,34); cta="@bodetail_official 팔로우"
    bb=draw.textbbox((0,0),cta,font=ctaf); w=bb[2]-bb[0]
    draw.text(((RW-w)//2,cy-16),cta,font=ctaf,fill=(*GOLD_BRIGHT,255))
    wf=fnt(SERIF_B,110); wt="bodetail"
    bb=draw.textbbox((0,0),wt,font=wf); w=bb[2]-bb[0]
    draw.text(((RW-w)//2,cy+60),wt,font=wf,fill=(*CREAM,220))
    p=OUT/"outro.png"; img.save(p,"PNG"); return p

def make_wordmark_overlay() -> Path:
    ov=Image.new("RGBA",(RW,80),(0,0,0,0)); draw=ImageDraw.Draw(ov)
    sf=fnt(SANS_MED,34); t="bodetail"
    bb=draw.textbbox((0,0),t,font=sf); w=bb[2]-bb[0]
    draw.text(((RW-w)//2,22),t,font=sf,fill=(*CREAM,160))
    p=OUT/"wordmark.png"; ov.save(p,"PNG"); return p

# ══════════════════════════════════════════════════════════════
# 15. 썸네일 (영어 자막 마스킹)
# ══════════════════════════════════════════════════════════════
def extract_full_frame(video_path: Path, t: float) -> Path:
    p = OUT / "thumb_src.jpg"
    subprocess.run([
        "ffmpeg","-y","-ss",f"{t:.2f}","-i",str(video_path),
        "-frames:v","1","-vf","scale=1080:1920",str(p)
    ], check=True, capture_output=True, timeout=30)
    return p if p.exists() else None

def mask_boxes_on_frame(frame_path: Path, boxes: list) -> Path:
    img = Image.open(frame_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for b in boxes:
        x1=max(0,b["x"]-10); y1=max(0,b["y"]-10)
        x2=min(RW,b["x"]+b["w"]+10); y2=min(RH,b["y"]+b["h"]+10)
        draw.rectangle([(x1,y1),(x2,y2)], fill=DARK)
    p = OUT / "thumb_masked.jpg"
    img.save(p, "JPEG", quality=92)
    return p

def make_thumbnail(headline, sub_label, source_frame=None) -> Path:
    W_T,H_T=1080,1440
    Xg,Yg=np.meshgrid(np.arange(W_T),np.arange(H_T))
    if source_frame and Path(source_frame).exists():
        base=np.array(Image.open(source_frame).convert("RGB").resize((W_T,H_T),Image.LANCZOS),dtype=np.float32)
        gray=0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base=gray[:,:,None]*0.55+base*0.45; base*=0.82
    else:
        base=np.zeros((H_T,W_T,3),dtype=np.float32); base[:]=list(DARK)
        d=np.sqrt(((Xg-W_T*0.5)/350.)**2+((Yg-H_T*0.55)/400.)**2)
        g=np.clip(1-d,0,1)*0.32
        base[:,:,0]+=g*75; base[:,:,1]+=g*62; base[:,:,2]+=g*45
    ink=np.array(DARK,dtype=np.float32)[None,None,:]
    base=base*0.55+ink*0.45
    yv=np.linspace(0,1,H_T)[:,None]
    fade=np.clip((yv-0.38)/0.62,0,1)**1.4*0.78
    base=base*(1-np.repeat(fade[:,:,None],W_T,axis=1))+ink*np.repeat(fade[:,:,None],W_T,axis=1)
    cx,cy=W_T/2,H_T/2
    dist=np.sqrt(((Xg-cx)/cx)**2+((Yg-cy)/cy)**2)
    vig=np.clip((dist-0.5)/0.7,0,1)**1.5*0.55
    base=base*(1-vig[:,:,None])
    img=Image.fromarray(np.clip(base,0,255).astype(np.uint8)); draw=ImageDraw.Draw(img)

    lf=fnt(SANS_MED,28)
    draw.text((84,88),"오늘의 디테일",font=lf,fill=GOLD)
    lw=draw.textlength("오늘의 디테일",font=lf)
    draw.line([(84+lw+20,106),(W_T-84,106)],fill=(*GOLD,160),width=2)

    bf=fnt(SANS_MED,24); bb=draw.textbbox((0,0),sub_label,font=bf)
    bw,bh=bb[2]-bb[0],bb[3]-bb[1]; bx,by=84,148
    draw.rectangle([(bx,by),(bx+bw+32,by+bh+20)],outline=(*CREAM,100),width=2)
    draw.text((bx+16-bb[0],by+10-bb[1]),sub_label,font=bf,fill=(*CREAM,145))

    max_w=W_T-84*2; fsize=92
    while fsize>56:
        mf=fnt(SANS_BLK,fsize); words=headline.split()
        lines=[]; cur=""
        for w in words:
            tr=w if cur=="" else cur+" "+w
            if draw.textlength(tr,font=mf)<=max_w: cur=tr
            else: lines.append(cur); cur=w
        if cur: lines.append(cur)
        lh=int(fsize*1.18)
        if len(lines)*lh<=380: break
        fsize-=6
    y=H_T-88-len(lines)*lh-8
    for line in lines:
        draw.text((84,y),line,font=mf,fill=WHITE); y+=lh

    sf=fnt(SANS_MED,26); t="bodetail"; sw=draw.textlength(t,font=sf)
    draw.text(((W_T-sw)//2,H_T-58),t,font=sf,fill=(*CREAM,190))
    p=OUT/"thumbnail_1080x1440.png"; img.save(p,"PNG"); return p

# ══════════════════════════════════════════════════════════════
# 16. FFmpeg 합성
# ══════════════════════════════════════════════════════════════
def build_reel_B(normalized: Path, drawbox_chain: str, ass_path: str,
                 outro_img: Path, wordmark_img: Path, main_dur: float) -> Path:
    processed=OUT/"processed.mp4"; outro_vid=OUT/"outro.mp4"; final=OUT/"reel_final.mp4"
    vf = (f"[0:v]{drawbox_chain},ass={ass_path}[sub];"
          f"[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]") if drawbox_chain else \
         (f"[0:v]ass={ass_path}[sub];[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]")
    subprocess.run([
        "ffmpeg","-y","-i",str(normalized),"-i",str(wordmark_img),
        "-filter_complex",vf,"-map","[out]","-map","0:a?",
        "-c:v","libx264","-crf","20","-preset","fast","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-movflags","+faststart",str(processed)
    ], check=True, capture_output=True, timeout=400)
    print("  ✅ 메인 처리 완료")
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",str(outro_img),"-f","lavfi",
        "-i","anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",str(OUTRO_DURATION),"-c:v","libx264","-pix_fmt","yuv420p","-r","30",
        "-vf","scale=1080:1920","-c:a","aac","-shortest","-movflags","+faststart",str(outro_vid)
    ], check=True, capture_output=True, timeout=60)
    print("  ✅ 아웃트로 완료")
    cf=OUT/"concat.txt"
    cf.write_text(f"file '{processed.resolve()}'\nfile '{outro_vid.resolve()}'\n",encoding="utf-8")
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(cf),
        "-c:v","libx264","-crf","20","-c:a","aac","-b:a","192k",
        "-movflags","+faststart",str(final)
    ], check=True, capture_output=True, timeout=180)
    print("  ✅ 최종 합성 완료")
    return final

def build_reel_A(source_video, ass_path, outro_img, wordmark_img) -> Path:
    processed=OUT/"processed.mp4"; outro_vid=OUT/"outro.mp4"; final=OUT/"reel_final.mp4"
    subprocess.run([
        "ffmpeg","-y","-stream_loop","-1","-i",str(source_video),"-i",str(wordmark_img),
        "-t",str(REEL_DURATION_A),"-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base];"
        f"[base]ass={ass_path}[sub];[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]",
        "-map","[out]","-map","0:a?","-c:v","libx264","-crf","20","-preset","fast",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(processed)
    ], check=True, capture_output=True, timeout=300)
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",str(outro_img),"-t",str(OUTRO_DURATION),
        "-c:v","libx264","-pix_fmt","yuv420p","-r","30","-vf","scale=1080:1920",
        "-movflags","+faststart",str(outro_vid)
    ], check=True, capture_output=True, timeout=60)
    cf=OUT/"concat.txt"
    cf.write_text(f"file '{processed.resolve()}'\nfile '{outro_vid.resolve()}'\n",encoding="utf-8")
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(cf),
        "-c:v","libx264","-crf","20","-c:a","aac","-b:a","192k",
        "-movflags","+faststart",str(final)
    ], check=True, capture_output=True, timeout=120)
    return final

# ══════════════════════════════════════════════════════════════
# 17. Instagram 게시
# ══════════════════════════════════════════════════════════════
def upload_to_github_release(filepath, filename):
    if not GITHUB_TOKEN or not REPO: return None
    h={"Authorization":f"token {GITHUB_TOKEN}","Accept":"application/vnd.github.v3+json"}
    rs=requests.get(f"https://api.github.com/repos/{REPO}/releases",headers=h,timeout=15).json()
    tr=next((r for r in rs if r.get("tag_name")=="temp-reels"),None)
    if not tr:
        tr=requests.post(f"https://api.github.com/repos/{REPO}/releases",headers=h,timeout=15,
            json={"tag_name":"temp-reels","name":"Temp Reel Storage","body":"auto","draft":False,"prerelease":True}).json()
    rid=tr["id"]
    assets=requests.get(f"https://api.github.com/repos/{REPO}/releases/{rid}/assets",headers=h,timeout=15).json()
    for a in assets:
        if a.get("name")==filename:
            requests.delete(f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}",headers=h,timeout=15)
    with open(filepath,"rb") as f:
        r=requests.post(f"https://uploads.github.com/repos/{REPO}/releases/{rid}/assets?name={filename}",
            headers={**h,"Content-Type":"video/mp4"},data=f,timeout=300)
    return r.json().get("browser_download_url") if r.status_code in (200,201) else None

def post_reel_to_instagram(video_url,thumb_url,caption):
    if not IG_USER_ID or not IG_TOKEN: return False
    B="https://graph.facebook.com/v18.0"
    r=requests.post(f"{B}/{IG_USER_ID}/media",params={"media_type":"REELS","video_url":video_url,
        "cover_url":thumb_url,"caption":caption,"access_token":IG_TOKEN},timeout=60)
    if r.status_code!=200:
        print(f"⚠️ 컨테이너 실패: {r.text[:200]}"); return False
    cid=r.json().get("id")
    for i in range(60):
        time.sleep(10)
        code=requests.get(f"{B}/{cid}",params={"fields":"status_code","access_token":IG_TOKEN},timeout=30).json().get("status_code","")
        print(f"    [{i+1}/60] {code}")
        if code=="FINISHED": break
        if code in ("ERROR","EXPIRED"): return False
    else: return False
    pub=requests.post(f"{B}/{IG_USER_ID}/media_publish",params={"creation_id":cid,"access_token":IG_TOKEN},timeout=30)
    if pub.status_code==200: print("  ✅ 게시 완료!"); return True
    return False

# ══════════════════════════════════════════════════════════════
# 18. 메인
# ══════════════════════════════════════════════════════════════
print("\n"+"="*60)
print(f"🎬 bodetail 릴스 자동화 v5 | {DATE} | 모드 {MODE}")
print("="*60)

used_ids=load_used_reels(); content={}; caption_full=""; thumb=None; final_reel=None
credit_text=""

if MODE=="B":
    src, credit_text, headline_override = process_inbox()
    print("\n🎞️ 영상 정규화(1080x1920) 중...")
    normalized = normalize_video(src)
    dur = get_video_duration(normalized)
    print(f"  ✅ 길이 {dur:.1f}초")

    print("\n🔍 타임라인 프레임 추출 중...")
    frames = extract_timeline_frames(normalized, interval=1.0)
    print(f"  ✅ {len(frames)}프레임")

    detected = detect_subtitles_timeline(frames)
    segments = build_segments(detected, frames)

    content = translate_and_generate(segments, frames, headline_override, credit_text)

    # 자막이 하나도 없으면 캡션만, 영상 그대로
    for s in segments:
        layout_segment(s)

    caption_full = (
        f"{content['caption_full']}\n\n{content['hashtags']}"
        f"{f'\n\n📹 | {credit_text}' if credit_text else ''}\n\n"
        f"Start Every Detail with Awareness Now\n—\n"
        f"내 외모의 최고 버전이 궁금하다면? @bodetail_official"
    )
    (OUT/"caption.txt").write_text(caption_full,encoding="utf-8")
    print(f"  ✅ 자막 {len(segments)}개 / 캡션 작성")

    ass_path=str(OUT/"subtitles.ass")
    build_ass(segments, ass_path)
    drawbox_chain=build_drawbox_chain(segments)

    print("\n🎨 이미지 에셋...")
    outro_img=make_outro_image(); wordmark_img=make_wordmark_overlay()

    # 썸네일
    best_t=float(content.get("best_frame_time", dur*0.4))
    best_t=max(0.5, min(best_t, dur-0.5))
    bf=extract_full_frame(normalized, best_t)
    # best_t 시점에 떠있는 영어 자막 마스킹
    cover=[s["en_box"] for s in segments if s["start"]<=best_t<=s["end"]]
    masked = mask_boxes_on_frame(bf, cover) if cover else bf
    thumb=make_thumbnail(content["thumbnail_headline"],
                         content.get("thumbnail_sub","DETAIL"), masked)
    print("  ✅ 썸네일 (영어 자막 마스킹)")

    print("\n🎬 FFmpeg 합성...")
    final_reel=build_reel_B(normalized, drawbox_chain, ass_path,
                            outro_img, wordmark_img, dur)

else:
    raw_video=OUT/"source.mp4"
    queries=get_video_queries(); vid_id=vid_url=None
    for q in queries:
        vid_id,vid_url=search_pexels_video(q)
        if vid_id: break
    if not vid_id:
        subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=c=black:size=1080x1920:r=30",
            "-t",str(REEL_DURATION_A),"-c:v","libx264","-pix_fmt","yuv420p",str(raw_video)],
            capture_output=True,timeout=60)
    else:
        used_ids.add(str(vid_id)); download_video(vid_url,raw_video)
    credit_text="Pexels (상업적 무료)"
    content=make_content_without_vision(credit_text)
    caption_full=(f"{content['caption_full']}\n\n{content['hashtags']}\n\n📹 | {credit_text}\n\n"
        f"Start Every Detail with Awareness Now\n—\n내 외모의 최고 버전이 궁금하다면? @bodetail_official")
    (OUT/"caption.txt").write_text(caption_full,encoding="utf-8")
    ass_path=str(OUT/"subtitles.ass"); make_ass_simple(content["captions"],ass_path)
    outro_img=make_outro_image(); wordmark_img=make_wordmark_overlay()
    fp=OUT/"frame.jpg"
    subprocess.run(["ffmpeg","-y","-ss","3","-i",str(raw_video),"-frames:v","1",
        "-vf","scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440",str(fp)],
        capture_output=True,timeout=30)
    thumb=make_thumbnail(content["thumbnail_headline"],content.get("thumbnail_sub","DETAIL"),
                         fp if fp.exists() else None)
    final_reel=build_reel_A(raw_video,ass_path,outro_img,wordmark_img)

size_mb=final_reel.stat().st_size//1024//1024
print(f"  ✅ 완성: {final_reel.name} ({size_mb}MB)")
save_used_reels(used_ids)

latest=Path("reels/latest"); latest.mkdir(exist_ok=True)
shutil.copy(final_reel,latest/"reel_final.mp4")
shutil.copy(thumb,latest/"thumbnail_1080x1440.png")
(latest/"caption.txt").write_text(caption_full,encoding="utf-8")
# ★ 원본 이동 없음 — 재실행 가능

if IG_USER_ID and IG_TOKEN and GITHUB_TOKEN:
    print("\n📤 인스타그램 게시...")
    vp=upload_to_github_release(final_reel,f"reel_{DATE}.mp4")
    tp=upload_to_github_release(thumb,f"thumb_{DATE}.png")
    if vp: post_reel_to_instagram(vp,tp,caption_full)
    else: print("  ⚠️ 공개 URL 실패 → 수동 업로드")
else:
    print("\n💡 IG 미설정 → reels/latest/ 확인")

print(f"\n🎉 완료! reels/latest/")
print(f"📝 캡션: {OUT}/caption.txt")
