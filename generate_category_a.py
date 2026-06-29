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
BEATS_PER_CUT   = int(os.environ.get("BEATS_PER_CUT","2"))
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
    # 720p 이하 mp4 우선 (용량/속도 균형)
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        "--no-playlist",
        url
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"❌ yt-dlp 오류:\n{r.stderr[-2000:]}")
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
    # 기존 유튜브 배경음악 제거 (새로 받은 걸로 교체)
    for old in BGM_DIR.glob("bgm_from_youtube.*"):
        old.unlink()
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out_tmpl,
        "--no-playlist",
        url
    ]
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
    url=up.json()["upload_url"]

    # 언어 자동 감지 옵션 사용
    body={"audio_url":url,"word_boost":["bodetail"]}
    if force_lang:
        body["language_code"]=force_lang
    else:
        body["language_detection"]=True

    tr=requests.post("https://api.assemblyai.com/v2/transcript",
        headers=hdrs,json=body,timeout=30)
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
    prompt=f"""bodetail 바이럴 릴스 편집 감독.
원본 {total_dur:.0f}초 → 목표 {TARGET_DURATION}초 추출
언어: {'영어→한국어 번역' if is_en else '한국어'}
브랜드: bodetail (남성 그루밍, 잉크블랙+골드)

[전체 대본]
{json.dumps(sents,ensure_ascii=False,indent=2)}

가장 바이럴 가능성 높은 {TARGET_DURATION}초 구간을 골라줘.
기준: 강한 훅 문장 + 핵심 통찰 + 임팩트 마무리.

순수 JSON만:
{{"clip_start":시작초,"clip_end":끝초,
"hook_reason":"이 구간 고른 이유 한줄",
"subtitles":[{{"start":원본초,"end":원본초,"subtitle_ko":"16자이내","emphasis_words":["강조어"]}}],
"broll_keywords":["man neck jawline dark cinematic","man hands dark moody","men cologne bottle dark","man face closeup moody","male suit dark editorial","man ear closeup dark","man mirror reflection dark"]}}

broll_keywords는 정확히 {N_IMGS}개, 모두 "man/male/men"+"dark/moody/cinematic" 포함."""
    res=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-6","max_tokens":2500,
              "messages":[{"role":"user","content":prompt}]},timeout=60)
    raw=res.json()["content"][0]["text"].strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    data=json.loads(raw)
    print(f"  ✅ 구간: {data['clip_start']:.1f}~{data['clip_end']:.1f}초")
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
                requests.get(res[0]["urls"]["regular"],timeout=20)
                Path(save).write_bytes(requests.get(res[0]["urls"]["regular"],timeout=20).content)
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
# STEP 7: 박자싱크 FFmpeg 합성
# ══════════════════════════════════════════════════
def render(clip,dur,cuts,imgs,ass,bgm):
    n=len(cuts)-1
    print(f"\n🎬 STEP 7: FFmpeg 합성 ({dur:.1f}초 {n}컷)...")
    valid=[p for p in imgs if p and Path(p).exists()]
    if not valid:
        blk=ASSETS/"black.jpg"
        subprocess.run(["ffmpeg","-y","-f","lavfi",
            f"-i","color=c=black:size={RW}x{RH}:rate=1","-frames:v","1",str(blk)],capture_output=True)
        valid=[str(blk)]
    out=OUT_DIR/"reel_final.mp4"
    cmd_in=["-i",str(clip)]
    ii={}
    for i,p in enumerate(valid):
        ii[i]=len(cmd_in)//2
        cmd_in+=["-loop","1","-t",str(dur+2),"-i",p]
    bi=None
    if bgm and bgm.exists():
        bi=len(cmd_in)//2; cmd_in+=["-i",str(bgm)]
    f=[]
    zes=[("min(zoom+0.0006,1.04)","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("if(eq(on,1),1.04,max(zoom-0.0006,1.0))","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("min(zoom+0.0008,1.05)","0","0"),
         ("if(eq(on,1),1.05,max(zoom-0.0008,1.0))","iw-(iw/zoom)","ih-(ih/zoom)")]
    for i,p in enumerate(valid):
        ze,xp,yp=zes[i%4]; fr=max(1,int((dur+2)*FPS))
        f.append(f"[{ii[i]}:v]scale={RW*2}:{RH*2}:force_original_aspect_ratio=increase,"
                 f"crop={RW}:{RH}:(iw-{RW})/2:(ih-{RH})/2,"
                 f"zoompan=z='{ze}':x='{xp}':y='{yp}':d={fr}:s={RW}x{RH}:fps={FPS},"
                 f"setpts=PTS-STARTPTS[kb{i}]")
    segs=[]
    for i in range(n):
        s=cuts[i];e=cuts[i+1];slot=i%len(valid);lb=f"s{i:05d}"
        f.append(f"[kb{slot}]trim={s:.4f}:{e:.4f},setpts=PTS-STARTPTS[{lb}]")
        segs.append(f"[{lb}]")
    f.append(f"{''.join(segs)}concat=n={n}:v=1:a=0[vcat]")
    ae=str(ass).replace("\\","/").replace(":","\\:")
    f.append(f"[vcat]ass='{ae}'[vout]")
    if bi is not None:
        f.append(f"[0:a]volume=1.0[oa];[{bi}:a]volume=0.25,aloop=loop=-1:size=2205000[ba];[oa][ba]amix=inputs=2:duration=first[aout]")
    fs=";\n".join(f)
    m=["-map","[vout]"]
    m+=["-map","[aout]"] if bi is not None else ["-map","0:a?"]
    cmd=["ffmpeg","-y"]+cmd_in+["-filter_complex",fs]+m+[
        "-c:v","libx264","-preset","fast","-crf","20",
        "-c:a","aac","-b:a","192k","-ar","48000",
        "-r",str(FPS),"-pix_fmt","yuv420p","-t",str(dur),str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"❌ FFmpeg:\n{r.stderr[-3000:]}"); raise RuntimeError("FFmpeg 실패")
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
    cuts       = analyze_beats(bgm,dur) if bgm else (
                 [0.0]+[round(t,3) for t in __import__("numpy").arange(0.5,dur,0.5)]+[dur]
                 if False else None)
    if cuts is None:
        cuts=[0.0]; t=0.5
        while t<dur: cuts.append(round(t,3)); t+=0.5
        cuts.append(dur)
    ass        = build_ass(direction.get("subtitles",[]),transcript.get("words",[]),cs)
    final      = render(clip,dur,cuts,imgs,ass,bgm)
    save_cleanup(final,direction,transcript,source_info)

    print(f"\n🎉 완료! 유튜브 URL → 완성 릴스")
    print(f"   → reels/latest_a/reel_final.mp4")
