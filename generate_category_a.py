"""
generate_category_a.py — bodetail 카테고리 A 자동화 v2
=====================================================
개선사항:
  - 자막 후발생 효과 (단어별 순차 팝업)
  - 강조 단어 골드색 + 크기 업
  - B롤 영상 없을 때 원본 영상 클립 사용 (검정 화면 방지)
  - FFmpeg 필터 안정화 (장면 수 관계없이 동작)
  - 영어/한국어 자동 감지
  - 처리 완료 후 inbox_a 자동 정리
"""

import os, json, re, time, requests, shutil, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════
KST  = timezone(timedelta(hours=9))
DATE = datetime.now(KST).strftime("%Y-%m-%d")

ASSEMBLYAI_KEY = os.environ["ASSEMBLYAI_API_KEY"]
ANTHROPIC_KEY  = os.environ["ANTROPIC_API_KEY"]
PEXELS_KEY     = os.environ.get("PEXELS_API_KEY","")
UNSPLASH_KEY   = os.environ.get("UNSPLASH_ACCESS_KEY","")

INBOX   = Path("videos/inbox_a")
OUT_DIR = Path(f"reels/category_a/{DATE}")
LATEST  = Path("reels/latest_a")
ASSETS  = Path("/tmp/assets_a")
SFX_DIR = Path("reels/sfx")

for d in [INBOX, OUT_DIR, LATEST, ASSETS, SFX_DIR]:
    d.mkdir(parents=True, exist_ok=True)

RW, RH = 1080, 1920
FPS    = 25

# ══════════════════════════════════════════════════════════════
# STEP 1: AssemblyAI 대본 추출
# ══════════════════════════════════════════════════════════════
def transcribe(video_path: Path) -> dict:
    print("🎙️ STEP 1: AssemblyAI 대본 추출 중...")
    headers = {"authorization": ASSEMBLYAI_KEY, "content-type": "application/json"}

    # 오디오 추출
    audio_path = ASSETS / "audio.mp3"
    subprocess.run([
        "ffmpeg","-y","-i",str(video_path),
        "-vn","-ar","16000","-ac","1","-b:a","64k",
        str(audio_path)
    ], check=True, capture_output=True)
    print("  → 오디오 추출 완료")

    # 업로드
    with open(audio_path,"rb") as f:
        up = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": ASSEMBLYAI_KEY},
            data=f, timeout=60
        )
    upload_url = up.json()["upload_url"]

    # 언어 감지 (영어 기본, 한국어 감지)
    # 파일명에 _ko 있으면 한국어
    lang = "ko" if "_ko" in video_path.stem.lower() else "en"
    print(f"  → 언어: {'한국어' if lang=='ko' else '영어 (자동번역 적용)'}")

    # 트랜스크립션 요청
    tr = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=headers,
        json={
            "audio_url": upload_url,
            "language_code": lang,
            "word_boost": ["bodetail"],
        }, timeout=30
    )
    tid = tr.json()["id"]

    # 완료 대기
    while True:
        poll = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{tid}",
            headers=headers, timeout=30
        ).json()
        st = poll["status"]
        print(f"  → 상태: {st}")
        if st == "completed": break
        if st == "error": raise RuntimeError(f"AssemblyAI 오류: {poll.get('error')}")
        time.sleep(3)

    words = poll.get("words",[])
    print(f"  ✅ 완료 ({len(words)}단어 / {len(poll.get('text',''))}자)")
    return poll

# ══════════════════════════════════════════════════════════════
# STEP 2: Claude 연출 JSON
# ══════════════════════════════════════════════════════════════
def build_sentences(words: list) -> list:
    """단어 목록 → 문장 단위 묶기"""
    sentences = []
    buf = []; start = None
    END_CHARS = set("。！？!?.")

    for w in words:
        t = w["text"]
        if start is None: start = w["start"] / 1000
        buf.append(t)
        is_end = t[-1] in END_CHARS if t else False
        if is_end or len(buf) >= 10:
            sentences.append({
                "start": round(start, 2),
                "end":   round(w["end"]/1000, 2),
                "text":  " ".join(buf)
            })
            buf=[]; start=None
    if buf and start is not None:
        sentences.append({
            "start": round(start,2),
            "end":   round(words[-1]["end"]/1000,2),
            "text":  " ".join(buf)
        })
    return sentences

def generate_direction(transcript: dict) -> dict:
    print("\n🤖 STEP 2: Claude 연출 JSON 생성 중...")
    words    = transcript.get("words",[])
    duration = words[-1]["end"]/1000 if words else 30
    sentences= build_sentences(words)
    is_en    = transcript.get("language_code","en") == "en"

    prompt = f"""너는 bodetail 바이럴 릴스 연출 감독이야.
브랜드: bodetail (남성 그루밍 라이프스타일 — 잉크블랙+크림+골드 톤)
영상 길이: {duration:.1f}초
원본 언어: {'영어 → 한국어로 번역 필요' if is_en else '한국어'}

아래 대본 문장들마다 연출 데이터를 만들어줘.

[대본]
{json.dumps(sentences, ensure_ascii=False, indent=2)}

각 문장마다:
- start, end, text: 그대로 유지
- subtitle_ko: {'영어를 자연스러운 한국어로 번역' if is_en else '그대로'}. 임팩트 있게. 20자 이내.
- emphasis_words: 강조할 핵심 단어 1~2개 (골드색+크게 표시됨). 빈 배열도 OK.
- broll_keyword: B롤 이미지 검색어 (영어). 반드시 "man"/"male"/"men" + "dark"/"moody"/"cinematic" 포함. 문장 내용과 일치.
- sfx: "whoosh"(새 주제 시작) / "bass_drop"(강렬한 단어) / "tick"(숫자/통계) / "none"
- transition: "cut" / "zoom_in" / "fade"
- broll_opacity: B롤 불투명도 0.0~1.0 (기본 0.85)

규칙:
1. bodetail 관련 키워드: 귀→"man ear closeup dark", 손→"man hands dark moody", 향수→"men cologne bottle dark cinematic"
2. 첫 장면은 반드시 강렬한 후킹 (bass_drop or whoosh)
3. 전체의 30%는 zoom_in 전환으로 긴장감 유지

순수 JSON 배열만 출력 (코드블록 금지):
[{{"start":0,"end":2.5,"text":"...","subtitle_ko":"...","emphasis_words":["단어"],"broll_keyword":"man dark moody cinematic","sfx":"bass_drop","transition":"zoom_in","broll_opacity":0.85}}]"""

    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "messages": [{"role":"user","content": prompt}]
        }, timeout=60
    )
    raw = res.json()["content"][0]["text"].strip()
    raw = re.sub(r'^```json\s*','',raw)
    raw = re.sub(r'\s*```$','',raw)
    scenes = json.loads(raw)
    print(f"  ✅ 연출 JSON 완료 ({len(scenes)}장면)")
    return {"scenes": scenes, "duration": duration}

# ══════════════════════════════════════════════════════════════
# STEP 3: B롤 이미지 다운로드
# ══════════════════════════════════════════════════════════════
FEMALE_BLOCK = {"woman","women","female","girl","flower","ring","makeup","nail","nails"}

def sanitize(q: str) -> str:
    w = q.lower().split()
    w = [x for x in w if x not in FEMALE_BLOCK]
    if not any(x in {"man","male","men"} for x in w): w=["man"]+w
    if not any(x in {"dark","moody","cinematic","editorial"} for x in w): w+=["dark"]
    return " ".join(w[:6])

def get_broll(keyword: str, save: Path) -> bool:
    q = sanitize(keyword)

    # Unsplash 먼저
    if UNSPLASH_KEY:
        try:
            r=requests.get(
                "https://api.unsplash.com/search/photos",
                headers={"Authorization":f"Client-ID {UNSPLASH_KEY}"},
                params={"query":q,"per_page":5,"orientation":"portrait","content_filter":"high"},
                timeout=10
            )
            results=r.json().get("results",[])
            if results:
                img=requests.get(results[0]["urls"]["regular"],timeout=20)
                save.write_bytes(img.content); return True
        except: pass

    # Pexels 폴백
    if PEXELS_KEY:
        try:
            r=requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization":PEXELS_KEY},
                params={"query":q,"per_page":5,"orientation":"portrait","size":"large"},
                timeout=10
            )
            photos=r.json().get("photos",[])
            if photos:
                img=requests.get(photos[0]["src"]["large2x"],timeout=20)
                save.write_bytes(img.content); return True
        except: pass

    return False

def download_all_broll(direction: dict) -> dict:
    print("\n🖼️ STEP 3: B롤 이미지 다운로드 중...")
    assets={}
    for i,sc in enumerate(direction["scenes"]):
        kw=sc.get("broll_keyword","man dark moody cinematic")
        dst=ASSETS/f"broll_{i:02d}.jpg"
        ok=get_broll(kw,dst)
        assets[i]=str(dst) if ok else None
        status="✅" if ok else "⚠️ 없음(원본사용)"
        print(f"  [{i+1:02d}] {status} {kw[:35]}")
    return assets

# ══════════════════════════════════════════════════════════════
# STEP 4a: ASS 자막 (후발생 효과)
# ══════════════════════════════════════════════════════════════
def ts(sec: float) -> str:
    h=int(sec//3600); m=int((sec%3600)//60)
    s=int(sec%60);    cs=int((sec%1)*100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def build_ass(direction: dict, words_raw: list) -> Path:
    print("\n📝 STEP 4a: ASS 자막 생성 중...")

    # 골드색 ASS 코드: &H004AB0B0 (BGR)
    GOLD = "&H004AB0B0&"
    WHITE= "&H00FFFFFF&"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RW}
PlayResY: {RH}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,NotoSansCJK-Black,68,{WHITE},&H000000FF,&H00000000,&HAA000000,1,0,0,0,100,100,0,0,1,5,0,2,80,80,80,1
Style: Big,NotoSansCJK-Black,90,{GOLD},&H000000FF,&H00000000,&HAA000000,1,0,0,0,100,100,0,0,1,5,0,2,80,80,80,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []

    for sc in direction["scenes"]:
        sub   = sc.get("subtitle_ko", sc.get("text",""))
        emph  = sc.get("emphasis_words",[])
        s_sec = sc["start"]
        e_sec = sc["end"]
        dur   = e_sec - s_sec
        words_in_scene = [w for w in words_raw
                          if w["start"]/1000 >= s_sec and w["end"]/1000 <= e_sec+0.1]

        if not words_in_scene:
            # 단어 없으면 통자막
            display = sub
            for ew in emph:
                display = display.replace(
                    ew, f"{{\\c{GOLD}}}{ew}{{\\c{WHITE}}}"
                )
            events.append(
                f"Dialogue: 0,{ts(s_sec)},{ts(e_sec)},Main,,0,0,0,,{display}"
            )
            continue

        # ★ 후발생 효과: 자막을 단어/청크 단위로 순차 팝업
        # subtitle_ko를 공백으로 분리해서 단어 수 맞추기
        ko_words = sub.split()
        n_ko = len(ko_words)
        n_en = len(words_in_scene)
        ratio= n_ko / max(n_en,1)

        # 각 영어 단어의 타임스탬프에 한국어 단어 매핑
        for j, en_w in enumerate(words_in_scene):
            ko_idx = min(int(j*ratio), n_ko-1)
            # 이 시점까지 나온 한국어 단어들 누적 표시
            shown = ko_words[:ko_idx+1]
            display_text = " ".join(shown)

            # 강조 단어 골드색 처리
            for ew in emph:
                display_text = display_text.replace(
                    ew, f"{{\\c{GOLD}\\fs90}}{ew}{{\\c{WHITE}\\fs68}}"
                )

            word_start = en_w["start"]/1000
            # 다음 단어 시작 전까지 또는 장면 끝까지
            if j+1 < len(words_in_scene):
                word_end = words_in_scene[j+1]["start"]/1000
            else:
                word_end = e_sec

            # 팝업 애니메이션: {\an2\fad(80,0)} — 하단 중앙, 80ms 페이드인
            events.append(
                f"Dialogue: 0,{ts(word_start)},{ts(word_end)},"
                f"Main,,0,0,0,,{{\\an2\\fad(80,0)}}{display_text}"
            )

    ass_path = ASSETS/"subtitles.ass"
    ass_path.write_text(header+"\n".join(events), encoding="utf-8")
    print(f"  ✅ ASS 자막 완료 ({len(events)}개 이벤트)")
    return ass_path

# ══════════════════════════════════════════════════════════════
# STEP 4b: FFmpeg 최종 합성
# ══════════════════════════════════════════════════════════════
def render(video_path: Path, direction: dict,
           assets: dict, ass_path: Path) -> Path:
    print("\n🎬 STEP 4b: FFmpeg 합성 중...")

    scenes   = direction["scenes"]
    duration = direction["duration"]
    out      = OUT_DIR/"reel_final.mp4"
    n        = len(scenes)

    # ── 입력 파일 목록 ──
    cmd_inputs = ["-i", str(video_path)]  # [0] 원본
    broll_map  = {}   # scene_idx → input_idx

    for i,sc in enumerate(scenes):
        img = assets.get(i)
        if img and Path(img).exists():
            broll_map[i] = len(cmd_inputs)//2
            dur_i = sc["end"] - sc["start"]
            cmd_inputs += ["-loop","1","-t",f"{dur_i:.3f}","-i",img]

    # ── 필터 그래프 ──
    filters   = []
    seg_labels= []

    # 원본 비디오 9:16 준비
    filters.append(
        f"[0:v]scale='if(gt(iw/ih,{RW}/{RH}),{RH}*iw/ih,{RW})':"
        f"'if(gt(iw/ih,{RW}/{RH}),{RH},{RW}*ih/iw)',"
        f"pad={RW}:{RH}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1[base_v]"
    )

    for i,sc in enumerate(scenes):
        s   = sc["start"]
        e   = sc["end"]
        dur = e - s
        op  = sc.get("broll_opacity", 0.85)
        idx = broll_map.get(i)
        tr  = sc.get("transition","cut")
        label = f"seg{i:02d}"

        if idx is not None:
            # Ken Burns (줌인/아웃 교대)
            zm = "in" if i%2==0 else "out"
            frames = max(1, int(dur*FPS))
            if zm=="in":
                zoom_expr = f"min(zoom+0.0008,1.05)"
                xy="iw/2-(iw/zoom/2):ih/2-(ih/zoom/2)"
            else:
                zoom_expr = f"if(eq(on,1),1.05,max(zoom-0.0008,1.0))"
                xy="iw/2-(iw/zoom/2):ih/2-(ih/zoom/2)"

            filters.append(
                f"[{idx}:v]"
                f"scale={RW*2}:{RH*2},"
                f"crop={RW}:{RH}:(iw-{RW})/2:(ih-{RH})/2,"
                f"zoompan=z='{zoom_expr}':x='{xy.split(':')[0]}':y='{xy.split(':')[1]}':"
                f"d={frames}:s={RW}x{RH}:fps={FPS}[kb{i:02d}]"
            )
            # 원본 위에 B롤 블렌드
            filters.append(
                f"[base_v]trim={s}:{e},setpts=PTS-STARTPTS[base_{i:02d}]"
            )
            filters.append(
                f"[base_{i:02d}][kb{i:02d}]blend=all_expr='A*(1-{op})+B*{op}'[{label}]"
            )
        else:
            # B롤 없으면 원본 클립 그대로
            filters.append(
                f"[base_v]trim={s}:{e},setpts=PTS-STARTPTS[{label}]"
            )
        seg_labels.append(f"[{label}]")

    # concat
    concat_str = "".join(seg_labels)
    filters.append(f"{concat_str}concat=n={n}:v=1:a=0[vcat]")

    # 자막 오버레이
    # ASS 경로 이스케이프 (콜론 처리)
    ass_escaped = str(ass_path).replace("\\","/").replace(":","\\:")
    filters.append(f"[vcat]ass='{ass_escaped}'[vfinal]")

    filter_str = ";\n".join(filters)

    # ── FFmpeg 실행 ──
    cmd = (
        ["ffmpeg","-y"]
        + cmd_inputs
        + ["-filter_complex", filter_str]
        + ["-map","[vfinal]","-map","0:a?"]
        + ["-c:v","libx264","-preset","fast","-crf","20"]
        + ["-c:a","aac","-b:a","192k","-ar","48000"]
        + ["-r",str(FPS),"-pix_fmt","yuv420p"]
        + ["-t",str(duration),str(out)]
    )

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg 오류:\n{result.stderr[-3000:]}")
        raise RuntimeError("FFmpeg 실패")

    size_mb = out.stat().st_size/1024/1024
    print(f"  ✅ 완성: {out} ({size_mb:.1f}MB)")
    return out

# ══════════════════════════════════════════════════════════════
# STEP 5: 저장 + 정리
# ══════════════════════════════════════════════════════════════
def save_and_cleanup(final: Path, direction: dict, transcript: dict):
    LATEST.mkdir(exist_ok=True)
    shutil.copy(final, LATEST/"reel_final.mp4")
    (LATEST/"direction.json").write_text(
        json.dumps(direction, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (LATEST/"transcript.json").write_text(
        json.dumps({"text":transcript.get("text",""),
                    "words":transcript.get("words",[])},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # inbox_a 정리
    archive = Path(f"videos/archive_a/{DATE}")
    archive.mkdir(parents=True, exist_ok=True)
    for f in INBOX.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            shutil.move(str(f), str(archive/f.name))
    print(f"  📦 inbox_a 정리 → videos/archive_a/{DATE}/")
    print(f"  ✅ reels/latest_a/reel_final.mp4 저장 완료")

# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"🎬 bodetail 카테고리 A v2 | {DATE}")
    print(f"{'='*60}\n")

    videos = sorted(INBOX.glob("*.mp4"))
    if not videos:
        print("❌ videos/inbox_a/ 에 영상 없음")
        exit(1)

    video = videos[0]
    print(f"📹 처리 영상: {video.name}\n")

    transcript   = transcribe(video)
    direction    = generate_direction(transcript)
    assets       = download_all_broll(direction)
    ass_path     = build_ass(direction, transcript.get("words",[]))
    final        = render(video, direction, assets, ass_path)
    save_and_cleanup(final, direction, transcript)

    print(f"\n🎉 완료! reels/latest_a/reel_final.mp4")
