"""
generate_category_a.py — bodetail 카테고리 A v6 (완전 자동화)
=====================================================
유튜브 URL만 주면 끝:
  URL → yt-dlp 다운로드 → AssemblyAI 대본 → Claude 핵심구간 탐지
  → 클립 추출 → B롤 이미지 → 배경음악 박자분석 → 박자싱크 교차
  → 후발생 자막 → FFmpeg 합성 → reels/latest_a/ 출력

입력 방법 2가지:
  1. videos/inbox_a/url.txt 에 유튜브 URL 한 줄 적기
  2. videos/inbox_a/*.mp4 직접 업로드 (기존 방식도 유지)
"""

import os, json, re, time, requests, shutil, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

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
BGM_DIR = Path("reels/bgm")

for d in [INBOX, OUT_DIR, LATEST, ASSETS, BGM_DIR]:
    d.mkdir(parents=True, exist_ok=True)

RW, RH = 1080, 1920
FPS    = 30
N_IMGS = 7
TARGET_DURATION = int(os.environ.get("REEL_DURATION","45"))
BEATS_PER_CUT   = max(1, int(os.environ.get("BEATS_PER_CUT","2")))
# Actions 입력으로 URL 직접 전달도 가능
URL_INPUT = os.environ.get("YOUTUBE_URL","").strip()
# 배경음악 유튜브 URL (선택)
BGM_URL_INPUT = os.environ.get("BGM_YOUTUBE_URL","").strip()

# ══════════════════════════════════════════════════
# STEP 0: 유튜브 다운로드 (yt-dlp)
# ══════════════════════════════════════════════════
def download_youtube(url: str) -> Path:
    print(f"📥 STEP 0: 유튜브 다운로드 중...\n  URL: {url}")
    out_tmpl = str(ASSETS/"yt_source.%(ext)s")

    # 쿠키 파일 생성 (GitHub Secret에서)
    cookies_content = os.environ.get("YOUTUBE_COOKIES","").strip()
    cookies_file = None
    if cookies_content:
        cookies_file = ASSETS/"yt_cookies.txt"
        cookies_file.write_text(cookies_content, encoding="utf-8")
        print("  → 쿠키 인증 사용")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        "--no-playlist",
        "--no-check-certificates",
        "--extractor-retries", "3",
        "--remote-components", "ejs:github",
    ]
    if cookies_file:
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)
    print(f"  → 실행: {' '.join(cmd[:6])} ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️ 1차 시도 실패 (코드 {r.returncode})")
        print(f"  stderr 일부: {r.stderr[-500:]}")
        # 폴백: 포맷 제한 없이 재시도
        print("  → 폴백 포맷으로 재시도...")
        cmd2 = [
            "yt-dlp",
            "-f", "best[height<=720]/best",
            "-o", out_tmpl,
            "--no-playlist",
            "--no-check-certificates",
            "--extractor-retries", "5",
            "--remote-components", "ejs:github",
        ]
        if cookies_file:
            cmd2 += ["--cookies", str(cookies_file)]
        cmd2.append(url)
        r = subprocess.run(cmd2, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ yt-dlp 오류 (코드 {r.returncode}):\n{r.stderr[-2500:]}")
            raise RuntimeError("유튜브 다운로드 실패")

    downloaded = list(ASSETS.glob("yt_source.*"))
    mp4s = [f for f in downloaded if f.suffix == ".mp4"]
    if not mp4s:
        # 확장자 다르면 변환
        src = downloaded[0]
        dst = ASSETS/"yt_source.mp4"
        subprocess.run(["ffmpeg","-y","-i",str(src),
            "-c:v","libx264","-c:a","aac",str(dst)],
            capture_output=True)
        mp4s=[dst]
    video = mp4s[0]
    size = video.stat().st_size/1024/1024
    print(f"  ✅ 다운로드 완료: {video.name} ({size:.1f}MB)")
    return video

# ══════════════════════════════════════════════════
# STEP 0b: 유튜브 오디오만 다운로드 (배경음악용)
# ══════════════════════════════════════════════════
def download_youtube_audio(url: str) -> Path:
    """유튜브 URL에서 오디오만 추출해서 배경음악으로 사용"""
    print(f"🎵 배경음악 유튜브 다운로드 중...\n  URL: {url}")
    out_tmpl = str(BGM_DIR/"bgm_from_youtube.%(ext)s")
    for old in BGM_DIR.glob("bgm_from_youtube.*"):
        old.unlink()

    cookies_content = os.environ.get("YOUTUBE_COOKIES","").strip()
    cookies_file = None
    if cookies_content:
        cookies_file = ASSETS/"yt_cookies.txt"
        if not cookies_file.exists():
            cookies_file.write_text(cookies_content, encoding="utf-8")

    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out_tmpl,
        "--no-playlist",
        "--no-check-certificates",
        "--remote-components", "ejs:github",
    ]
    if cookies_file:
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️ 배경음악 다운로드 실패:\n{r.stderr[-1000:]}")
        return None
    mp3s = list(BGM_DIR.glob("bgm_from_youtube.mp3"))
    if mp3s:
        size = mp3s[0].stat().st_size/1024/1024
        print(f"  ✅ 배경음악 다운로드 완료: {mp3s[0].name} ({size:.1f}MB)")
        return mp3s[0]
    return None

# ══════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════
def get_duration(p: Path) -> float:
    r=subprocess.run(["ffprobe","-v","error","-show_entries",
        "format=duration","-of","csv=p=0",str(p)],
        capture_output=True,text=True)
    return float(r.stdout.strip() or "30")

# ══════════════════════════════════════════════════
# STEP 1: AssemblyAI 대본
# ══════════════════════════════════════════════════
def transcribe(video_path: Path, force_lang=None) -> dict:
    print("\n🎙️ STEP 1: AssemblyAI 대본 추출...")
    hdrs={"authorization":ASSEMBLYAI_KEY,"content-type":"application/json"}
    audio=ASSETS/"audio.mp3"
    subprocess.run(["ffmpeg","-y","-i",str(video_path),
        "-vn","-ar","16000","-ac","1","-b:a","64k",str(audio)],
        check=True,capture_output=True)
    with open(audio,"rb") as f:
        up=requests.post("https://api.assemblyai.com/v2/upload",
            headers={"authorization":ASSEMBLYAI_KEY},data=f,timeout=180)
    if up.status_code != 200 or "upload_url" not in up.json():
        raise RuntimeError(f"AssemblyAI 업로드 실패 ({up.status_code}): {up.text[:500]}")
    url=up.json()["upload_url"]

    # 언어 자동 감지 옵션 사용
    body={"audio_url":url,"word_boost":["bodetail"]}
    if force_lang:
        body["language_code"]=force_lang
    else:
        body["language_detection"]=True

    tr=requests.post("https://api.assemblyai.com/v2/transcript",
        headers=hdrs,json=body,timeout=30)
    if tr.status_code != 200 or "id" not in tr.json():
        raise RuntimeError(f"AssemblyAI 요청 실패 ({tr.status_code}): {tr.text[:500]}")
    tid=tr.json()["id"]
    while True:
        poll=requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}",
            headers=hdrs,timeout=30).json()
        print(f"  → {poll['status']}")
        if poll["status"]=="completed": break
        if poll["status"]=="error": raise RuntimeError(poll.get("error"))
        time.sleep(3)
    detected=poll.get("language_code","en")
    print(f"  ✅ {len(poll.get('words',[]))}단어 | 언어: {detected}")
    return poll

# ══════════════════════════════════════════════════
# STEP 2: Claude 핵심구간 + 연출
# ══════════════════════════════════════════════════
def build_sents(words):
    s=[]; buf=[]; st=None
    for w in words:
        t=w["text"]
        if st is None: st=w["start"]/1000
        buf.append(t)
        if (t and t[-1] in "。！？!?.") or len(buf)>=12:
            s.append({"start":round(st,2),"end":round(w["end"]/1000,2),"text":" ".join(buf)})
            buf=[]; st=None
    if buf and st: s.append({"start":round(st,2),"end":round(words[-1]["end"]/1000,2),"text":" ".join(buf)})
    return s

def generate_direction(transcript, total_dur):
    print(f"\n🤖 STEP 2: Claude 핵심구간 탐지 + 연출 (목표 {TARGET_DURATION}초)...")
    words=transcript.get("words",[])
    is_en=transcript.get("language_code","en")!="ko"
    sents=build_sents(words)

    # 아주 긴 원본(문장 600개 초과)은 프롬프트 비대화 방지를 위해 균등 샘플링
    if len(sents) > 600:
        step = len(sents)/600
        sents = [sents[int(i*step)] for i in range(600)]
        print(f"  → 문장 {len(sents)}개로 다운샘플링 (원본이 너무 긺)")

    prompt=f"""bodetail 바이럴 릴스 편집 감독.
원본 {total_dur:.0f}초 → 목표 {TARGET_DURATION}초 추출
언어: {'영어→한국어 번역' if is_en else '한국어'}
브랜드: bodetail (남성 그루밍, 잉크블랙+골드)

[전체 대본]
{json.dumps(sents,ensure_ascii=False,indent=2)}

가장 바이럴 가능성 높은 {TARGET_DURATION}초 구간을 골라줘.

[중요 — 길이 제약]
clip_end - clip_start는 반드시 {TARGET_DURATION}초 근처(±20% 이내)여야 해.
즉 clip_start ~ clip_end는 하나의 연속된 짧은 구간이어야 하고,
원본 영상 전체를 다 가져오면 절대 안 돼.

[선택 기준 — 중요]
1. 그 {TARGET_DURATION}초 구간 안에 가슴이 뜨거워지고 동기부여가 되는
   핵심 구절이 반드시 포함되어야 해.
   (예: 강한 선언, 인생을 바꾸는 통찰, 듣고 나면 행동하고 싶어지는 말)
2. 자막은 구간 전체의 모든 말을 다 띄울 필요 없어.
   {TARGET_DURATION}초 구간 안에서도 가장 임팩트 있는 한두 문장만
   subtitles에 넣고, 나머지 시간은 자막 없이 배경음악+이미지 교차로
   채워도 돼. (subtitles 배열이 짧아도 됨)
3. 말이 적은 구간이라도 그 한마디가 강력하면 그 구간을 선택해.

[자막 규칙]
- 핵심 문장만 subtitle로. 모든 말을 자막으로 넣을 필요 없어.
- emphasis_words로 가장 강력한 단어를 골드색 강조.

순수 JSON만:
{{"clip_start":시작초,"clip_end":끝초,
"hook_reason":"이 구간 고른 이유 (어떤 동기부여 포인트인지)",
"subtitles":[{{"start":원본초,"end":원본초,"subtitle_ko":"16자이내","emphasis_words":["강조어"]}}],
"broll_keywords":["man neck jawline dark cinematic","man hands dark moody","men cologne bottle dark","man face closeup moody","male suit dark editorial","man ear closeup dark","man mirror reflection dark"]}}

broll_keywords는 정확히 {N_IMGS}개, 모두 "man/male/men"+"dark/moody/cinematic" 포함."""
    res=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-6","max_tokens":3000,
              "messages":[{"role":"user","content":prompt}]},timeout=90)
    if res.status_code != 200:
        raise RuntimeError(f"Claude API 오류 {res.status_code}: {res.text[:500]}")
    body = res.json()
    if "content" not in body:
        raise RuntimeError(f"Claude 응답 형식 오류: {json.dumps(body)[:500]}")
    raw=body["content"][0]["text"].strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    data=json.loads(raw)

    # ── 안전 클램프: clip_start/end가 비정상(문자열·범위폭주)이어도 강제 보정 ──
    try:
        cs = float(data.get("clip_start", 0))
    except (TypeError, ValueError):
        cs = 0.0
    try:
        ce = float(data.get("clip_end", cs + TARGET_DURATION))
    except (TypeError, ValueError):
        ce = cs + TARGET_DURATION

    cs = max(0.0, min(cs, max(0.0, total_dur - 1)))
    max_allowed = TARGET_DURATION * 1.3
    if ce <= cs or (ce - cs) > max_allowed:
        print(f"  ⚠️ Claude가 비정상 구간({cs:.1f}~{ce:.1f}) 반환 → {TARGET_DURATION}초로 강제 보정")
        ce = min(cs + TARGET_DURATION, total_dur)
    ce = min(ce, total_dur)
    data["clip_start"], data["clip_end"] = cs, ce

    print(f"  ✅ 구간: {cs:.1f}~{ce:.1f}초 ({ce-cs:.1f}초)")
    print(f"     이유: {data.get('hook_reason','')}")
    return data

# ══════════════════════════════════════════════════
# STEP 3: 클립 추출
# ══════════════════════════════════════════════════
def extract_clip(video, start, end):
    print(f"\n✂️ STEP 3: 클립 추출 ({start:.1f}~{end:.1f}초)...")
    clip=ASSETS/"clip.mp4"
    subprocess.run(["ffmpeg","-y","-ss",str(start),"-to",str(end),
        "-i",str(video),"-c:v","libx264","-c:a","aac","-b:a","192k",str(clip)],
        check=True,capture_output=True)
    dur=get_duration(clip)
    print(f"  ✅ {dur:.1f}초")
    return clip,dur

# ══════════════════════════════════════════════════
# STEP 4: B롤 이미지
# ══════════════════════════════════════════════════
FEMALE={"woman","women","female","girl","flower","ring","makeup","nail","nails"}
def get_img(kw,save):
    w=[x for x in kw.lower().split() if x not in FEMALE]
    if not any(x in {"man","male","men"} for x in w): w=["man"]+w
    if not any(x in {"dark","moody","cinematic","editorial"} for x in w): w+=["dark"]
    q=" ".join(w[:6])
    if UNSPLASH_KEY:
        try:
            r=requests.get("https://api.unsplash.com/search/photos",
                headers={"Authorization":f"Client-ID {UNSPLASH_KEY}"},
                params={"query":q,"per_page":3,"orientation":"portrait","content_filter":"high"},timeout=10)
            res=r.json().get("results",[])
            if res:
                img_resp=requests.get(res[0]["urls"]["regular"],timeout=20)
                Path(save).write_bytes(img_resp.content)
                return True
        except: pass
    if PEXELS_KEY:
        try:
            r=requests.get("https://api.pexels.com/v1/search",
                headers={"Authorization":PEXELS_KEY},
                params={"query":q,"per_page":3,"orientation":"portrait","size":"large"},timeout=10)
            ph=r.json().get("photos",[])
            if ph:
                Path(save).write_bytes(requests.get(ph[0]["src"]["large2x"],timeout=20).content)
                return True
        except: pass
    return False

def download_images(keywords):
    print(f"\n🖼️ STEP 4: 이미지 {N_IMGS}장 다운로드...")
    kws=(keywords*3)[:N_IMGS]; paths=[]
    for i,kw in enumerate(kws):
        dst=ASSETS/f"img_{i:02d}.jpg"
        ok=get_img(kw,dst)
        paths.append(str(dst) if ok else None)
        print(f"  [{i+1}/{N_IMGS}] {'✅' if ok else '⚠️'} {kw[:38]}")
    return paths

# ══════════════════════════════════════════════════
# STEP 5: 배경음악 박자 분석
# ══════════════════════════════════════════════════
def analyze_beats(bgm, dur):
    print(f"\n🥁 STEP 5: 배경음악 박자 분석...")
    MAX_CUTS = 150  # 너무 잦은 컷으로 렌더링 시간 폭주 방지
    try:
        import librosa, numpy as np
        y,sr=librosa.load(str(bgm),sr=22050,duration=dur+5)
        tempo,bf=librosa.beat.beat_track(y=y,sr=sr,units='frames')
        bt=librosa.frames_to_time(bf,sr=sr)
        tv=float(np.atleast_1d(tempo)[0])
        print(f"  → BPM {tv:.1f} | {len(bt)}박자")
        cuts=[float(b) for i,b in enumerate(bt) if i%BEATS_PER_CUT==0 and float(b)<dur]
        if not cuts or cuts[0]>0.1: cuts=[0.0]+cuts
        cuts.append(dur)
        if len(cuts)-1 > MAX_CUTS:
            print(f"  ⚠️ 컷 수 {len(cuts)-1}개 → {MAX_CUTS}개로 제한 (균등 샘플링)")
            step=(len(cuts)-1)/MAX_CUTS
            cuts=[cuts[int(i*step)] for i in range(MAX_CUTS)]+[dur]
        print(f"  → {len(cuts)-1}컷 ({BEATS_PER_CUT}박자마다)")
        return cuts
    except Exception as e:
        print(f"  ⚠️ {e} → 0.5초 고정")
        cuts=[0.0]; t=0.5
        while t<dur: cuts.append(round(t,3)); t+=0.5
        cuts.append(dur); return cuts

# ══════════════════════════════════════════════════
# STEP 6: 후발생 ASS 자막
# ══════════════════════════════════════════════════
def ts(s):
    h=int(s//3600);m=int((s%3600)//60);sec=int(s%60);cs=int((s%1)*100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

def build_ass(subs,words,clip_start):
    print("\n📝 STEP 6: 후발생 자막 생성...")
    G="&H004AB0B0&";W="&H00FFFFFF&"
    hdr=f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RW}
PlayResY: {RH}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,NotoSansCJK-Black,72,{W},&H000000FF,&H00000000,&HAA000000,1,0,0,0,100,100,0,0,1,5,0,2,80,80,100,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ev=[]
    for sc in subs:
        s0=max(0,sc["start"]-clip_start); e0=sc["end"]-clip_start
        if e0<=0: continue
        sub=sc.get("subtitle_ko","");emph=sc.get("emphasis_words",[])
        ws=[w for w in words if w["start"]/1000>=sc["start"] and w["end"]/1000<=sc["end"]+0.1]
        if not ws:
            d=sub
            for ew in emph: d=d.replace(ew,f"{{\\c{G}\\fs90}}{ew}{{\\c{W}\\fs72}}")
            ev.append(f"Dialogue: 0,{ts(s0)},{ts(e0)},Main,,0,0,0,,{{\\an2\\fad(60,0)}}{d}")
            continue
        ko=sub.split();nk=len(ko);ratio=nk/max(len(ws),1)
        for j,w in enumerate(ws):
            ki=min(int(j*ratio),nk-1)
            sh=" ".join(ko[:ki+1])
            for ew in emph: sh=sh.replace(ew,f"{{\\c{G}\\fs90}}{ew}{{\\c{W}\\fs72}}")
            ws0=max(0,w["start"]/1000-clip_start)
            we0=(ws[j+1]["start"]/1000-clip_start) if j+1<len(ws) else e0
            if ws0<0: continue
            ev.append(f"Dialogue: 0,{ts(ws0)},{ts(we0)},Main,,0,0,0,,{{\\an2\\fad(60,0)}}{sh}")
    ass=ASSETS/"subs.ass"
    ass.write_text(hdr+"\n".join(ev),encoding="utf-8")
    print(f"  ✅ {len(ev)}개 이벤트")
    return ass

# ══════════════════════════════════════════════════
# STEP 7: 박자싱크 FFmpeg 합성 (2단계 방식)
# ══════════════════════════════════════════════════
def render(clip,dur,cuts,imgs,ass,bgm):
    n=len(cuts)-1
    print(f"\n🎬 STEP 7: FFmpeg 합성 ({dur:.1f}초 {n}컷)...")
    valid=[p for p in imgs if p and Path(p).exists()]
    if not valid:
        print("  ⚠️ 다운로드된 이미지가 하나도 없음 → 검정 폴백 이미지 생성")
        blk=ASSETS/"black.jpg"
        r_blk=subprocess.run(["ffmpeg","-y","-f","lavfi",
            "-i", f"color=c=black:size={RW}x{RH}:rate=1",
            "-frames:v","1",str(blk)],capture_output=True,text=True)
        if r_blk.returncode!=0 or not blk.exists():
            raise RuntimeError(f"검정 폴백 이미지 생성 실패: {r_blk.stderr[-500:]}")
        valid=[str(blk)]
    out=OUT_DIR/"reel_final.mp4"

    # ── 1단계: 각 박자 컷을 개별 영상 세그먼트로 생성 ──
    seg_dir=ASSETS/"segs"; seg_dir.mkdir(exist_ok=True)
    for old in seg_dir.glob("*.mp4"): old.unlink()

    zes=[("min(zoom+0.0012,1.08)","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("if(eq(on,1),1.08,max(zoom-0.0012,1.0))","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("min(zoom+0.0015,1.09)","0","0"),
         ("if(eq(on,1),1.09,max(zoom-0.0015,1.0))","iw-(iw/zoom)","ih-(ih/zoom)")]

    print(f"  → {n}개 세그먼트 생성 중...")
    seg_files=[]
    for i in range(n):
        seg_dur=cuts[i+1]-cuts[i]
        if seg_dur<0.05: seg_dur=0.05
        img=valid[i%len(valid)]
        ze,xp,yp=zes[i%4]
        fr=max(2,int(seg_dur*FPS))
        seg_path=seg_dir/f"seg_{i:05d}.mp4"
        cmd=["ffmpeg","-y","-loop","1","-t",f"{seg_dur:.4f}","-i",str(img),
            "-vf",
            f"scale={RW*2}:{RH*2}:force_original_aspect_ratio=increase,"
            f"crop={RW}:{RH}:(iw-{RW})/2:(ih-{RH})/2,"
            f"zoompan=z='{ze}':x='{xp}':y='{yp}':d={fr}:s={RW}x{RH}:fps={FPS},"
            f"format=yuv420p",
            "-r",str(FPS),"-c:v","libx264","-preset","ultrafast","-crf","22",
            "-an",str(seg_path)]
        r=subprocess.run(cmd,capture_output=True,text=True)
        if r.returncode!=0:
            print(f"  ⚠️ 세그먼트 {i} 실패: {r.stderr[-300:]}")
            continue
        seg_files.append(seg_path)

    if not seg_files:
        raise RuntimeError("세그먼트 생성 전부 실패")
    print(f"  ✅ {len(seg_files)}개 세그먼트 생성 완료")

    # ── 2단계: 세그먼트 concat ──
    concat_list=ASSETS/"concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{s}'" for s in seg_files), encoding="utf-8")
    video_only=ASSETS/"video_only.mp4"
    cmd_concat=["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_list),
        "-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p",
        "-r",str(FPS),str(video_only)]
    r=subprocess.run(cmd_concat,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"❌ concat 실패:\n{r.stderr[-2000:]}"); raise RuntimeError("concat 실패")
    print(f"  ✅ 영상 이어붙이기 완료")

    # ── 3단계: 자막 + 오디오 합성 ──
    ae=str(ass).replace("\\","/").replace(":","\\:")
    cmd_in=["-i",str(video_only),"-i",str(clip)]  # [0]영상 [1]원본(오디오용)
    bi=None
    if bgm and bgm.exists():
        bi=2; cmd_in+=["-i",str(bgm)]

    filters=[f"[0:v]ass='{ae}'[vout]"]
    if bi is not None:
        filters.append(
            f"[1:a]volume=1.0[oa];"
            f"[{bi}:a]volume=0.25,aloop=loop=-1:size=2205000[ba];"
            f"[oa][ba]amix=inputs=2:duration=first[aout]")
        amap=["-map","[aout]"]
    else:
        amap=["-map","1:a?"]

    cmd=["ffmpeg","-y"]+cmd_in+["-filter_complex",";".join(filters),
        "-map","[vout]"]+amap+[
        "-c:v","libx264","-preset","fast","-crf","20",
        "-c:a","aac","-b:a","192k","-ar","48000",
        "-r",str(FPS),"-pix_fmt","yuv420p","-t",str(dur),str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"❌ 최종합성 실패:\n{r.stderr[-2500:]}"); raise RuntimeError("FFmpeg 실패")
    print(f"  ✅ {out.name} ({out.stat().st_size/1024/1024:.1f}MB)")
    return out

# ══════════════════════════════════════════════════
# STEP 8: 저장 + 정리
# ══════════════════════════════════════════════════
def save_cleanup(final,direction,transcript,source_info):
    LATEST.mkdir(exist_ok=True)
    shutil.copy(final,LATEST/"reel_final.mp4")
    (LATEST/"direction.json").write_text(json.dumps(direction,ensure_ascii=False,indent=2),encoding="utf-8")
    (LATEST/"source.txt").write_text(source_info,encoding="utf-8")
    arch=Path(f"videos/archive_a/{DATE}");arch.mkdir(parents=True,exist_ok=True)
    for fp in INBOX.iterdir():
        if fp.is_file() and fp.name!=".gitkeep":
            shutil.move(str(fp),str(arch/fp.name))
    print(f"  📦 inbox_a 정리 / ✅ reels/latest_a/reel_final.mp4")

# ══════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════
if __name__=="__main__":
    print(f"\n{'='*60}")
    print(f"🎬 bodetail Category A v6 완전자동화 | {DATE}")
    print(f"   목표 {TARGET_DURATION}초 / {BEATS_PER_CUT}박자마다 교체")
    print(f"{'='*60}")

    # ── 입력 소스 결정 ──
    source_info=""
    force_lang=None
    video=None

    # 1순위: Actions에서 직접 전달한 URL
    url=URL_INPUT
    # 2순위: inbox_a/url.txt
    url_file=INBOX/"url.txt"
    if not url and url_file.exists():
        url=url_file.read_text().strip().splitlines()[0].strip()

    if url:
        print(f"\n🔗 입력: 유튜브 URL")
        video=download_youtube(url)
        source_info=f"YouTube: {url}\n생성: {DATE}"
        # URL 파일 정리
        if url_file.exists(): url_file.unlink()
    else:
        # 3순위: 직접 업로드된 mp4
        vids=sorted(INBOX.glob("*.mp4"))
        if not vids:
            print("❌ 입력 없음. videos/inbox_a/url.txt 에 유튜브 URL을 넣거나 mp4를 업로드하세요.")
            exit(1)
        video=vids[0]
        if "_ko" in video.stem.lower(): force_lang="ko"
        source_info=f"파일: {video.name}\n생성: {DATE}"
        print(f"\n📹 입력: {video.name}")

    total_dur=get_duration(video)
    print(f"📏 원본 길이: {total_dur:.0f}초")

    # 배경음악 결정
    # 1순위: 유튜브 BGM URL / inbox_a/bgm_url.txt
    bgm_url = BGM_URL_INPUT
    bgm_url_file = INBOX/"bgm_url.txt"
    if not bgm_url and bgm_url_file.exists():
        bgm_url = bgm_url_file.read_text().strip().splitlines()[0].strip()

    bgm = None
    if bgm_url:
        bgm = download_youtube_audio(bgm_url)
        if bgm_url_file.exists(): bgm_url_file.unlink()
    # 2순위: reels/bgm/ 폴더의 기존 음악
    if not bgm:
        bgm = next(BGM_DIR.glob("*.mp3"),None) or next(BGM_DIR.glob("*.m4a"),None)
    print(f"🎵 배경음악: {bgm.name if bgm else '없음'}")

    # 파이프라인
    transcript = transcribe(video, force_lang)
    direction  = generate_direction(transcript, total_dur)
    cs=direction.get("clip_start",0); ce=direction.get("clip_end",min(TARGET_DURATION,total_dur))
    clip,dur   = extract_clip(video, cs, ce)
    imgs       = download_images(direction.get("broll_keywords",[]))
    if bgm:
        cuts = analyze_beats(bgm, dur)
    else:
        # 배경음악 없으면 0.5초 고정 간격 폴백
        cuts=[0.0]; t=0.5
        while t<dur: cuts.append(round(t,3)); t+=0.5
        cuts.append(dur)
        print("\n⚠️ 배경음악 없음 → 0.5초 고정 간격으로 이미지 교차")
    ass        = build_ass(direction.get("subtitles",[]),transcript.get("words",[]),cs)
    final      = render(clip,dur,cuts,imgs,ass,bgm)
    save_cleanup(final,direction,transcript,source_info)

    print(f"\n🎉 완료! 유튜브 URL → 완성 릴스")
    print(f"   → reels/latest_a/reel_final.mp4")
