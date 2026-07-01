"""
generate_category_a.py — bodetail 카테고리 A v8 (20초 퐁크 하이브리드)
=====================================================
구조:
  훅(고긴스 영상+음성) → 드롭 구절 → 그 이후 BGM 드롭 + 박자싱크 이미지 몽타주
  전 구간 한국어 단어단위 자막(팝+페이드), BGM 드롭을 영상 드롭에 정렬.

v7 → v8 변경:
  - 기본 길이 20초 (REEL_DURATION 기본값)
  - drop_at(마음 울리는 구절 끝) 이후 이미지 6~7장 박자싱크 교차편집으로 전환
  - BGM 드롭(detect 또는 BGM_DROP_SEC)을 영상 드롭 시점에 맞춰 -ss/adelay 정렬
  - 드롭에서 BGM 0.12→0.34, 보이스 1.0→0.7 덕킹
  - 줌(켄번즈) 세그먼트 정상화(정확한 프레임수), 폰트 'Noto Sans CJK KR'
  - 모든 ffmpeg 명령 사전 검증됨

입력: youtube_url / videos/inbox_a/url.txt / *.mp4 직접 업로드
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

RW, RH, FPS = 1080, 1920, 30
N_IMGS = 7
TARGET_DURATION = int(os.environ.get("REEL_DURATION","20"))
BEATS_PER_CUT   = max(1, int(os.environ.get("BEATS_PER_CUT","2")))
URL_INPUT       = os.environ.get("YOUTUBE_URL","").strip()
BGM_URL_INPUT   = os.environ.get("BGM_YOUTUBE_URL","").strip()
BGM_DROP_ENV    = os.environ.get("BGM_DROP_SEC","").strip()

def run(cmd, tag):
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"❌ {tag} 실패:\n{r.stderr[-2500:]}")
        raise RuntimeError(tag)
    return r

# ══════════════════════════════════════════════════
# STEP 0: 유튜브 다운로드
# ══════════════════════════════════════════════════
def download_youtube(url: str) -> Path:
    print(f"📥 STEP 0: 유튜브 다운로드\n  URL: {url}")
    out_tmpl = str(ASSETS/"yt_source.%(ext)s")
    cookies_content = os.environ.get("YOUTUBE_COOKIES","").strip()
    cookies_file = None
    if cookies_content:
        cookies_file = ASSETS/"yt_cookies.txt"
        cookies_file.write_text(cookies_content, encoding="utf-8")
        print("  → 쿠키 인증 사용")
    cmd = ["yt-dlp",
        "-f","bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format","mp4","-o",out_tmpl,"--no-playlist",
        "--no-check-certificates","--extractor-retries","3","--remote-components","ejs:github"]
    if cookies_file: cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️ 1차 실패\n  {r.stderr[-500:]}\n  → 폴백")
        cmd2=["yt-dlp","-f","best[height<=720]/best","-o",out_tmpl,"--no-playlist",
              "--no-check-certificates","--extractor-retries","5","--remote-components","ejs:github"]
        if cookies_file: cmd2 += ["--cookies", str(cookies_file)]
        cmd2.append(url)
        r=subprocess.run(cmd2,capture_output=True,text=True)
        if r.returncode!=0:
            print(f"❌ yt-dlp:\n{r.stderr[-2500:]}"); raise RuntimeError("유튜브 다운로드 실패")
    downloaded=list(ASSETS.glob("yt_source.*"))
    mp4s=[f for f in downloaded if f.suffix==".mp4"]
    if not mp4s:
        src=downloaded[0]; dst=ASSETS/"yt_source.mp4"
        subprocess.run(["ffmpeg","-y","-i",str(src),"-c:v","libx264","-c:a","aac",str(dst)],capture_output=True)
        mp4s=[dst]
    print(f"  ✅ {mp4s[0].name} ({mp4s[0].stat().st_size/1024/1024:.1f}MB)")
    return mp4s[0]

def download_youtube_audio(url: str) -> Path:
    print(f"🎵 배경음악 유튜브 다운로드\n  URL: {url}")
    out_tmpl=str(BGM_DIR/"bgm_from_youtube.%(ext)s")
    for old in BGM_DIR.glob("bgm_from_youtube.*"): old.unlink()
    cookies_content=os.environ.get("YOUTUBE_COOKIES","").strip()
    cookies_file=None
    if cookies_content:
        cookies_file=ASSETS/"yt_cookies.txt"
        if not cookies_file.exists(): cookies_file.write_text(cookies_content,encoding="utf-8")
    cmd=["yt-dlp","-f","bestaudio/best","-x","--audio-format","mp3","--audio-quality","0",
         "-o",out_tmpl,"--no-playlist","--no-check-certificates","--remote-components","ejs:github"]
    if cookies_file: cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"  ⚠️ 실패:\n{r.stderr[-800:]}"); return None
    mp3s=list(BGM_DIR.glob("bgm_from_youtube.mp3"))
    if mp3s:
        print(f"  ✅ {mp3s[0].name} ({mp3s[0].stat().st_size/1024/1024:.1f}MB)")
        return mp3s[0]
    return None

# ══════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════
def get_duration(p):
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","csv=p=0",str(p)],capture_output=True,text=True)
    return float(r.stdout.strip() or "30")

def has_audio(p):
    r=subprocess.run(["ffprobe","-v","error","-select_streams","a",
        "-show_entries","stream=index","-of","csv=p=0",str(p)],capture_output=True,text=True)
    return bool(r.stdout.strip())

# ══════════════════════════════════════════════════
# STEP 1: 대본
# ══════════════════════════════════════════════════
def transcribe(video_path, force_lang=None):
    print("\n🎙️ STEP 1: AssemblyAI 대본 추출...")
    hdrs={"authorization":ASSEMBLYAI_KEY,"content-type":"application/json"}
    audio=ASSETS/"audio.mp3"
    subprocess.run(["ffmpeg","-y","-i",str(video_path),"-vn","-ar","16000","-ac","1",
        "-b:a","64k",str(audio)],check=True,capture_output=True)
    with open(audio,"rb") as f:
        up=requests.post("https://api.assemblyai.com/v2/upload",
            headers={"authorization":ASSEMBLYAI_KEY},data=f,timeout=180)
    if up.status_code!=200 or "upload_url" not in up.json():
        raise RuntimeError(f"AssemblyAI 업로드 실패 ({up.status_code}): {up.text[:400]}")
    url=up.json()["upload_url"]
    body={"audio_url":url,"word_boost":["bodetail"]}
    if force_lang: body["language_code"]=force_lang
    else: body["language_detection"]=True
    tr=requests.post("https://api.assemblyai.com/v2/transcript",headers=hdrs,json=body,timeout=30)
    if tr.status_code!=200 or "id" not in tr.json():
        raise RuntimeError(f"AssemblyAI 요청 실패 ({tr.status_code}): {tr.text[:400]}")
    tid=tr.json()["id"]
    while True:
        poll=requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}",headers=hdrs,timeout=30).json()
        print(f"  → {poll['status']}")
        if poll["status"]=="completed": break
        if poll["status"]=="error": raise RuntimeError(poll.get("error"))
        time.sleep(3)
    print(f"  ✅ {len(poll.get('words',[]))}단어 | 언어: {poll.get('language_code','en')}")
    return poll

# ══════════════════════════════════════════════════
# STEP 2: 핵심구간 + 드롭시점 + 자막
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
    print(f"\n🤖 STEP 2: 핵심구간+드롭+자막 (목표 {TARGET_DURATION}초)...")
    words=transcript.get("words",[])
    is_en=transcript.get("language_code","en")!="ko"
    sents=build_sents(words)
    if len(sents)>600:
        step=len(sents)/600; sents=[sents[int(i*step)] for i in range(600)]
        print(f"  → 문장 {len(sents)}개로 다운샘플링")

    prompt=f"""bodetail 바이럴 퐁크 모티베이션 릴스 편집 감독.
원본 {total_dur:.0f}초 → 목표 {TARGET_DURATION}초.
구조: [훅] 화자 영상+음성 → [드롭] 마음 때리는 핵심구절 → 그 이후 이미지 몽타주.
자막은 화자의 '영어 원문 그대로' 단어별로 싱크됨(번역 안 함). 넌 강조할 영어 단어만 고르면 됨.
브랜드: bodetail (남성 그루밍, 잉크블랙+골드)

[전체 대본]
{json.dumps(sents,ensure_ascii=False,indent=2)}

가장 바이럴 가능성 높은 {TARGET_DURATION}초 '연속' 구간 하나를 골라줘.

[길이 제약] clip_end - clip_start 는 {TARGET_DURATION}초 ±20% 이내의 하나의 연속 구간.

[drop_at — 중요]
구간 안에서 '가장 가슴을 때리는 한 구절'이 끝나는 지점의 원본 초를 drop_at 으로.
이 시점 이후부터 화면이 이미지 몽타주로 전환됨. (clip_start+4 ~ clip_end-3 사이)

[emphasis_words] 선택 구간에서 골드로 강조할 '영어 단어'들(핵심 임팩트어 5~12개). 대본에 실제로 등장하는 단어 그대로.

순수 JSON만:
{{"clip_start":시작초,"clip_end":끝초,"drop_at":드롭초,
"hook_reason":"고른 이유",
"emphasis_words":["never","quit","pain","war","...대본 속 실제 영어단어"],
"broll_keywords":["man neck jawline dark cinematic","man hands dark moody","men cologne bottle dark","man face closeup moody","male suit dark editorial","man silhouette dark rim light","man mirror reflection dark"]}}

broll_keywords는 정확히 {N_IMGS}개, 모두 "man/male/men"+"dark/moody/cinematic" 포함."""
    res=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-6","max_tokens":4000,"messages":[{"role":"user","content":prompt}]},
        timeout=120)
    if res.status_code!=200: raise RuntimeError(f"Claude API {res.status_code}: {res.text[:400]}")
    body=res.json()
    if "content" not in body: raise RuntimeError(f"Claude 형식오류: {json.dumps(body)[:400]}")
    raw=body["content"][0]["text"].strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    data=json.loads(raw)
    def f(x,d):
        try: return float(x)
        except (TypeError,ValueError): return d
    cs=f(data.get("clip_start"),0.0); ce=f(data.get("clip_end"),cs+TARGET_DURATION)
    cs=max(0.0,min(cs,max(0.0,total_dur-1)))
    if ce<=cs or (ce-cs)>TARGET_DURATION*1.3:
        ce=min(cs+TARGET_DURATION,total_dur)
        print(f"  ⚠️ 구간 보정 → {cs:.1f}~{ce:.1f}")
    ce=min(ce,total_dur)
    da=f(data.get("drop_at"),cs+(ce-cs)*0.5)
    da=max(cs+4.0,min(da,ce-3.0)) if (ce-cs)>7 else cs+(ce-cs)*0.5
    data["clip_start"],data["clip_end"],data["drop_at"]=cs,ce,da
    if not isinstance(data.get("emphasis_words"),list): data["emphasis_words"]=[]
    print(f"  ✅ 구간 {cs:.1f}~{ce:.1f} ({ce-cs:.1f}s) | 드롭 {da:.1f} | 강조어 {len(data['emphasis_words'])}개")
    print(f"     이유: {data.get('hook_reason','')}")
    return data

# ══════════════════════════════════════════════════
# STEP 3: 클립 추출
# ══════════════════════════════════════════════════
def extract_clip(video,start,end):
    print(f"\n✂️ STEP 3: 클립 추출 ({start:.1f}~{end:.1f})...")
    clip=ASSETS/"clip.mp4"
    run(["ffmpeg","-y","-ss",str(start),"-to",str(end),"-i",str(video),
        "-c:v","libx264","-c:a","aac","-b:a","192k","-pix_fmt","yuv420p",str(clip)],"extract_clip")
    dur=get_duration(clip)
    print(f"  ✅ {dur:.1f}초 | 오디오: {'있음' if has_audio(clip) else '❌ 없음!'}")
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
                Path(save).write_bytes(requests.get(res[0]["urls"]["regular"],timeout=20).content); return True
        except: pass
    if PEXELS_KEY:
        try:
            r=requests.get("https://api.pexels.com/v1/search",headers={"Authorization":PEXELS_KEY},
                params={"query":q,"per_page":3,"orientation":"portrait","size":"large"},timeout=10)
            ph=r.json().get("photos",[])
            if ph:
                Path(save).write_bytes(requests.get(ph[0]["src"]["large2x"],timeout=20).content); return True
        except: pass
    return False

def download_images(keywords):
    print(f"\n🖼️ STEP 4: 몽타주 이미지...")
    kws=(keywords*3)[:N_IMGS]; paths=[]
    for i,kw in enumerate(kws):
        dst=ASSETS/f"img_{i:02d}.jpg"; ok=get_img(kw,dst)
        paths.append(str(dst) if ok else None)
        print(f"  [{i+1}/{N_IMGS}] {'✅' if ok else '⚠️'} {kw[:36]}")
    print(f"  → 성공 {len([p for p in paths if p])}/{N_IMGS}장")
    return paths

# ══════════════════════════════════════════════════
# STEP 5: 박자 + 드롭 탐지
# ══════════════════════════════════════════════════
def analyze_beats(bgm,dur):
    print(f"\n🥁 STEP 5: 박자 분석...")
    try:
        import librosa, numpy as np
        y,sr=librosa.load(str(bgm),sr=22050,duration=dur+5)
        tempo,bf=librosa.beat.beat_track(y=y,sr=sr,units='frames')
        bt=librosa.frames_to_time(bf,sr=sr)
        beats=[float(b) for b in bt if 0<float(b)<dur]
        print(f"  → BPM {float(np.atleast_1d(tempo)[0]):.1f} | {len(beats)}박자")
        return beats
    except Exception as e:
        print(f"  ⚠️ {e} → 0.45초 균등")
        return [round(i*0.45,3) for i in range(1,int(dur/0.45))]

def detect_bgm_drop(bgm):
    if BGM_DROP_ENV:
        try:
            v=float(BGM_DROP_ENV); print(f"  🎯 BGM 드롭(수동 지정): {v:.1f}초"); return v
        except: pass
    try:
        import librosa, numpy as np
        y,sr=librosa.load(str(bgm),sr=22050,duration=45)
        rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=512)[0]
        times=librosa.frames_to_time(np.arange(len(rms)),sr=sr,hop_length=512)
        sm=np.convolve(rms,np.ones(8)/8,mode='same')
        best_t,best=0.0,0.0
        for i in range(int(1.5*sr/512),len(sm)):
            prev=sm[max(0,i-40):i].mean()
            if sm[i]-prev>best: best=sm[i]-prev; best_t=float(times[i])
        print(f"  🎯 BGM 드롭(자동탐지): {best_t:.1f}초")
        return best_t
    except Exception as e:
        print(f"  ⚠️ 드롭탐지 실패({e}) → 0초"); return 0.0

# ══════════════════════════════════════════════════
# STEP 6: 영어 원문 단어싱크 자막 (한 단어씩 화면 중앙에 크게)
# ══════════════════════════════════════════════════
# 화자가 그 단어를 말하는 '실제 타임스탬프'(AssemblyAI)에 맞춰
# 한 단어만 화면 정중앙에 크게 떴다가 다음 단어로 교체됨 (LOOKING → because 식).
# 새 단어는 70→100 팝, 강조어는 골드.

def ts(s):
    h=int(s//3600);m=int((s%3600)//60);sec=int(s%60);cs=int((s%1)*100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

def build_ass(words, clip_start, clip_dur, emphasis, out):
    print("\n📝 STEP 6: 한 단어씩 중앙 자막...")
    GOLD="&H004A84B0&"; WHITE="&H00FFFFFF&"
    hdr=f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RW}
PlayResY: {RH}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,Noto Sans CJK KR,140,{WHITE},&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,1,0,1,7,4,5,60,60,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    # clip 범위 안 단어만(초 단위, clip 기준 상대시간)
    W=[]
    for w in words:
        s=w.get("start",0)/1000-clip_start; e=w.get("end",0)/1000-clip_start
        if e<=0 or s>=clip_dur: continue
        txt=str(w.get("text","")).strip()
        if not txt: continue
        W.append({"t":max(0.0,s),"e":min(clip_dur,e),"w":txt})
    emph={str(e).lower().strip(".,!?") for e in (emphasis or [])}
    ev=[]
    for i,x in enumerate(W):
        es=x["t"]
        nxt = W[i+1]["t"] if i+1<len(W) else None
        natural_end = x["e"]+0.30
        if nxt is not None:
            # 다음 단어까지 공백이 크면(쉼) 잠깐 사라지고, 아니면 다음 단어로 즉시 교체
            ee = min(nxt, natural_end) if (nxt-x["e"])>0.8 else nxt
        else:
            ee = natural_end
        ee=min(ee, clip_dur)
        if ee<=es: ee=es+0.10
        wt=x["w"].upper()
        L=len(wt)
        fs = 150 if L<=6 else (128 if L<=9 else 104)   # 긴 단어는 자동 축소
        ie = x["w"].lower().strip(".,!?") in emph
        col = GOLD if ie else WHITE
        tag=("{\\an5\\1c"+col+"\\fs"+str(fs)+
             "\\fscx70\\fscy70\\t(0,80,\\fscx100\\fscy100)\\fad(30,20)}")
        ev.append("Dialogue: 0,"+ts(es)+","+ts(ee)+",Main,,0,0,0,,"+tag+wt)
    Path(out).write_text(hdr+"\n".join(ev)+"\n",encoding="utf-8")
    print(f"  ✅ {len(ev)}개 단어 (한 단어씩 중앙)")
    return out

# ══════════════════════════════════════════════════
# STEP 7: 렌더 (검증된 명령들)
# ══════════════════════════════════════════════════
def make_vertical(clip,out,t_start,t_dur):
    vf=("[0:v]split=2[a][b];"
        f"[b]scale={RW}:{RH}:force_original_aspect_ratio=increase,crop={RW}:{RH},gblur=sigma=28,eq=brightness=-0.12:saturation=0.85[bg];"
        f"[a]scale={RW}:{RH}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    run(["ffmpeg","-y","-ss",f"{t_start}","-i",str(clip),"-filter_complex",vf,
        "-map","[v]","-an","-t",f"{t_dur}","-c:v","libx264","-preset","medium","-crf","20",
        "-r",str(FPS),"-pix_fmt","yuv420p",str(out)],"make_vertical")
    return out

def build_montage(images,cuts,out,seg_dir):
    Path(seg_dir).mkdir(parents=True,exist_ok=True)
    for old in Path(seg_dir).glob("*.mp4"): old.unlink()
    zes=[("min(zoom+0.0020,1.12)","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("if(eq(on,1),1.12,max(zoom-0.0020,1.0))","iw/2-(iw/zoom/2)","ih/2-(ih/zoom/2)"),
         ("min(zoom+0.0024,1.13)","0","0"),
         ("min(zoom+0.0024,1.13)","iw-(iw/zoom)","ih-(ih/zoom)")]
    segs=[]
    for i in range(len(cuts)-1):
        sd=max(0.12,cuts[i+1]-cuts[i]); fr=max(3,int(round(sd*FPS)))
        img=images[i%len(images)]; ze,xp,yp=zes[i%4]
        sp=Path(seg_dir)/f"s{i:04d}.mp4"
        run(["ffmpeg","-y","-loop","1","-i",str(img),"-vf",
            f"scale={RW}:{RH}:force_original_aspect_ratio=increase,crop={RW}:{RH},"
            f"zoompan=z='{ze}':d={fr}:x='{xp}':y='{yp}':s={RW}x{RH}:fps={FPS},"
            "eq=brightness=-0.04,format=yuv420p",
            "-frames:v",str(fr),"-r",str(FPS),"-c:v","libx264","-preset","ultrafast",
            "-crf","22","-an",str(sp)],f"seg{i}")
        segs.append(sp)
    lst=Path(seg_dir)/"list.txt"
    lst.write_text("\n".join(f"file '{s}'" for s in segs),encoding="utf-8")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
        "-c:v","libx264","-preset","fast","-crf","20","-r",str(FPS),
        "-pix_fmt","yuv420p",str(out)],"montage_concat")
    print(f"  ✅ 몽타주 {len(segs)}컷")
    return out

def concat_videos(parts,out):
    lst=Path(out).parent/"vlist.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts),encoding="utf-8")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
        "-c:v","libx264","-preset","fast","-crf","20","-r",str(FPS),
        "-pix_fmt","yuv420p",str(out)],"concat_AB")
    return out

def finalize(video_only,clip,bgm,ass,out,drop_t,dur,bgm_offset):
    ae=str(ass).replace("\\","/").replace(":","\\:")
    inputs=["-i",str(video_only),"-i",str(clip)]
    bidx=None
    if bgm:
        bidx=2
        if bgm_offset>=0: inputs+=["-ss",f"{bgm_offset:.3f}","-i",str(bgm)]
        else: inputs+=["-i",str(bgm)]
    fc=[f"[0:v]ass='{ae}'[vout]"]
    if bidx is not None:
        delay="" if bgm_offset>=0 else f"adelay={int(-bgm_offset*1000)}:all=1,"
        fc.append(
            f"[1:a]volume='if(lt(t,{drop_t:.3f}),1.0,0.7)'[oa];"
            f"[{bidx}:a]{delay}volume='if(lt(t,{drop_t:.3f}),0.12,0.34)'[bl];"
            "[oa][bl]amix=inputs=2:duration=first:normalize=0[aout]")
        amap=["-map","[aout]"]
    else:
        amap=["-map","1:a"]
    run(["ffmpeg","-y"]+inputs+["-filter_complex",";".join(fc),
        "-map","[vout]"]+amap+["-c:v","libx264","-preset","medium","-crf","20",
        "-c:a","aac","-b:a","192k","-ar","48000","-r",str(FPS),
        "-pix_fmt","yuv420p","-t",f"{dur:.3f}",str(out)],"finalize")
    return out

def render(clip,dur,clip_start,beats,imgs,words,emphasis,bgm,bgm_drop,drop_at):
    print(f"\n🎬 STEP 7: 합성...")
    valid=[p for p in imgs if p and Path(p).exists()]
    drop_t=drop_at-clip_start
    montage=(len(valid)>=2 and bool(bgm))
    if montage: drop_t=max(4.0,min(drop_t,dur-3.0))
    else:       drop_t=dur
    print(f"  드롭 {drop_t:.1f}초 | 몽타주 {'ON' if montage else 'OFF(영상 풀)'} | B롤 {len(valid)}장")

    ass=build_ass(words,clip_start,dur,emphasis,ASSETS/"subs.ass")
    pA=make_vertical(clip,ASSETS/"partA.mp4",0,drop_t)
    if montage:
        pb=[round(b-drop_t,3) for b in beats if b>drop_t]
        cuts=[0.0]+[pb[i] for i in range(len(pb)) if i%BEATS_PER_CUT==0]
        cuts=[c for c in cuts if 0<=c<(dur-drop_t)]
        cuts=sorted(set(cuts+[round(dur-drop_t,3)]))
        if len(cuts)-1>60:
            step=(len(cuts)-1)/60
            cuts=sorted(set([cuts[int(i*step)] for i in range(60)]+[round(dur-drop_t,3)]))
        pB=build_montage(valid,cuts,ASSETS/"partB.mp4",ASSETS/"segs")
        vo=concat_videos([pA,pB],ASSETS/"video_only.mp4")
    else:
        vo=pA
    bgm_offset=(bgm_drop-drop_t) if bgm else 0.0
    out=OUT_DIR/"reel_final.mp4"
    finalize(vo,clip,(bgm if bgm else None),ass,out,min(drop_t,dur),dur,bgm_offset)
    print(f"  ✅ {out.name} ({out.stat().st_size/1024/1024:.1f}MB)")
    return out

# ══════════════════════════════════════════════════
# STEP 8: 저장
# ══════════════════════════════════════════════════
def save_cleanup(final,direction,source_info):
    LATEST.mkdir(exist_ok=True)
    shutil.copy(final,LATEST/"reel_final.mp4")
    (LATEST/"direction.json").write_text(json.dumps(direction,ensure_ascii=False,indent=2),encoding="utf-8")
    (LATEST/"source.txt").write_text(source_info,encoding="utf-8")
    arch=Path(f"videos/archive_a/{DATE}");arch.mkdir(parents=True,exist_ok=True)
    for fp in INBOX.iterdir():
        if fp.is_file() and fp.name!=".gitkeep":
            shutil.move(str(fp),str(arch/fp.name))
    print(f"  📦 정리 완료 / ✅ reels/latest_a/reel_final.mp4")

# ══════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════
if __name__=="__main__":
    print(f"\n{'='*60}\n🎬 bodetail Category A v8 (20초 퐁크) | {DATE}\n   목표 {TARGET_DURATION}초 / {BEATS_PER_CUT}박자마다\n{'='*60}")
    source_info=""; force_lang=None; video=None
    url=URL_INPUT
    uf=INBOX/"url.txt"
    if not url and uf.exists(): url=uf.read_text().strip().splitlines()[0].strip()
    if url:
        print("\n🔗 입력: 유튜브 URL")
        video=download_youtube(url); source_info=f"YouTube: {url}\n생성: {DATE}"
        if uf.exists(): uf.unlink()
    else:
        vids=sorted(INBOX.glob("*.mp4"))
        if not vids: print("❌ 입력 없음."); exit(1)
        video=vids[0]
        if "_ko" in video.stem.lower(): force_lang="ko"
        source_info=f"파일: {video.name}\n생성: {DATE}"
        print(f"\n📹 입력: {video.name}")

    total_dur=get_duration(video)
    print(f"📏 원본 {total_dur:.0f}초")

    # BGM
    bgm_url=BGM_URL_INPUT
    buf=INBOX/"bgm_url.txt"
    if not bgm_url and buf.exists(): bgm_url=buf.read_text().strip().splitlines()[0].strip()
    bgm=None
    if bgm_url:
        bgm=download_youtube_audio(bgm_url)
        if buf.exists(): buf.unlink()
    if not bgm:
        bgm=next(BGM_DIR.glob("*.mp3"),None) or next(BGM_DIR.glob("*.m4a"),None)
    print(f"🎵 배경음악: {bgm.name if bgm else '없음'}")

    transcript=transcribe(video,force_lang)
    direction =generate_direction(transcript,total_dur)
    cs=direction["clip_start"]; ce=direction["clip_end"]; drop_at=direction["drop_at"]
    clip,dur=extract_clip(video,cs,ce)
    imgs=download_images(direction.get("broll_keywords",[]))
    beats=analyze_beats(bgm,dur) if bgm else []
    bgm_drop=detect_bgm_drop(bgm) if bgm else 0.0
    final=render(clip,dur,cs,beats,imgs,transcript.get("words",[]),
                 direction.get("emphasis_words",[]),bgm,bgm_drop,drop_at)
    save_cleanup(final,direction,source_info)
    print(f"\n🎉 완료! → reels/latest_a/reel_final.mp4")
