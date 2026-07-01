"""
generate_category_a.py — bodetail 카테고리 A v8 (20초 퐁크 하이브리드)
=====================================================
구조:
  훅(고긴스 영상+음성) → 한 방짜리 명대사(드롭) → 그 이후 BGM+박자싱크 이미지 몽타주

핵심 사양:
  - 기본 길이 20초 (REEL_DURATION 환경변수로 조절)
  - drop_at(가장 강렬한 한 줄이 끝나는 지점) 이후 이미지 몽타주로 전환
  - BGM_START_SEC(또는 자동탐지)로 'BGM 트랙의 어느 지점부터' 쓸지 순수 트림
    (영상 드롭 시점과 억지로 정렬 안 함 — 사용자가 원하는 구간을 그대로 사용)
  - BGM은 드롭 전엔 완전 무음, 드롭 순간 0.05초 만에 확 치고 들어옴(펀치)
  - 자막은 영어 원문 그대로, 단어별 실제 타이밍에 맞춰 한 단어씩 화면 중앙에 등장
    (핵심 단어=Anton 볼드 대문자 / 연결어=Playfair Display 이탤릭 소문자, 강조어=골드)
  - 대본 선택 시 "설명적인 구간"이 아니라 SNS에 캡션으로 박제될 만한
    한 방짜리 명대사가 포함된 구간을 우선 탐색 (자세한 기준은 generate_direction 참고)
  - reels/latest_a/assets/ 에 clip.mp4·bgm_used.mp3·images/·direction_edit.json을
    저장해서, bodetail_editor.html에서 이미지 교체 등 재편집 후
    rerender_category_a.py로 빠르게 재렌더 가능

입력: youtube_url / videos/inbox_a/url.txt / *.mp4 직접 업로드
"""

import os, json, re, time, requests, shutil, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

KST  = timezone(timedelta(hours=9))
DATE = datetime.now(KST).strftime("%Y-%m-%d")

ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_API_KEY","")   # rerender_category_a.py는 이 키가 없어도 import 가능해야 함
ANTHROPIC_KEY  = os.environ.get("ANTROPIC_API_KEY","")
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
BGM_START_ENV   = os.environ.get("BGM_START_SEC","").strip()

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
        print(f"  ⚠️ 1차 실패\n  {r.stderr[-500:]}\n  → 폴백(2차)")
        cmd2=["yt-dlp","-f","best[height<=720]/best","-o",out_tmpl,"--no-playlist",
              "--no-check-certificates","--extractor-retries","5","--remote-components","ejs:github"]
        if cookies_file: cmd2 += ["--cookies", str(cookies_file)]
        cmd2.append(url)
        r=subprocess.run(cmd2,capture_output=True,text=True)
    if r.returncode != 0:
        print(f"  ⚠️ 2차 실패\n  {r.stderr[-500:]}\n  → 폴백(3차: 플레이어 클라이언트 강제 지정)")
        cmd3=["yt-dlp","-f","best[height<=720]/best","-o",out_tmpl,"--no-playlist",
              "--no-check-certificates","--extractor-retries","5","--remote-components","ejs:github",
              "--extractor-args","youtube:player_client=default,tv,android"]
        if cookies_file: cmd3 += ["--cookies", str(cookies_file)]
        cmd3.append(url)
        r=subprocess.run(cmd3,capture_output=True,text=True)
        if r.returncode!=0:
            print(f"❌ yt-dlp (3차까지 모두 실패):\n{r.stderr[-2500:]}"); raise RuntimeError("유튜브 다운로드 실패")
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
        print(f"  ⚠️ 1차 실패\n  {r.stderr[-500:]}\n  → 폴백(플레이어 클라이언트 강제 지정)")
        cmd2=["yt-dlp","-f","bestaudio/best","-x","--audio-format","mp3","--audio-quality","0",
              "-o",out_tmpl,"--no-playlist","--no-check-certificates","--remote-components","ejs:github",
              "--extractor-args","youtube:player_client=default,tv,android"]
        if cookies_file: cmd2 += ["--cookies", str(cookies_file)]
        cmd2.append(url)
        r=subprocess.run(cmd2,capture_output=True,text=True)
    if r.returncode!=0:
        print(f"  ⚠️ 최종 실패:\n{r.stderr[-800:]}"); return None
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
    """대본을 문장 단위로 묶음. 문장부호/12단어뿐 아니라 '말 사이 공백(pause)'
    으로도 끊어서, "I don't give a fuck" 같은 짧고 강렬한 한 줄이 앞뒤 말에
    뭉개지지 않고 독립된 문장으로 Claude에게 보이도록 함(연설에서 임팩트 있는
    말 뒤엔 대개 숨 고르는 pause가 옴 — 그 지점을 문장 경계로 활용)."""
    s=[]; buf=[]; st=None; prev_end=None
    for w in words:
        t=w["text"]; ws=w["start"]/1000
        gap = (ws - prev_end) if prev_end is not None else 0
        if buf and gap>0.45:
            s.append({"start":round(st,2),"end":round(prev_end,2),"text":" ".join(buf)})
            buf=[]; st=None
        if st is None: st=ws
        buf.append(t)
        prev_end=w["end"]/1000
        if (t and t[-1] in "。！？!?.") or len(buf)>=12:
            s.append({"start":round(st,2),"end":round(prev_end,2),"text":" ".join(buf)})
            buf=[]; st=None
    if buf and st: s.append({"start":round(st,2),"end":round(words[-1]["end"]/1000,2),"text":" ".join(buf)})
    return s

def generate_direction(transcript, total_dur):
    print(f"\n🤖 STEP 2: 핵심구간+드롭+자막 (목표 {TARGET_DURATION}초)...")
    words=transcript.get("words",[])
    is_en=transcript.get("language_code","en")!="ko"
    sents=build_sents(words)
    # 예전엔 문장이 600개 넘으면 등간격으로 솎아내서(stride sampling) 대본 대부분을
    # 버렸음 — 이러면 정확히 원하는 임팩트 한 줄이 Claude 눈에 아예 안 보일 수 있음.
    # Sonnet 컨텍스트는 충분히 크므로(문장당 ~30~50토큰) 왠만한 인터뷰 전체를
    # 그대로 다 넣어도 안전함. 정말 극단적으로 긴 경우(3시간+)에만 안내만 출력.
    MAX_SENTS = 4000
    if len(sents) > MAX_SENTS:
        print(f"  ⚠️ 문장 {len(sents)}개 — 매우 긴 원본. 앞부분 {MAX_SENTS}개만 사용(전체를 넣기엔 너무 김)")
        sents = sents[:MAX_SENTS]
    print(f"  → 대본 문장 {len(sents)}개 (전체 그대로 Claude에 전달)")

    prompt=f"""bodetail 바이럴 퐁크 모티베이션 릴스 편집 감독.
원본 {total_dur:.0f}초 → 목표 {TARGET_DURATION}초.
구조: [훅] 화자 영상+음성 → [드롭] 마음 때리는 핵심구절 → 그 이후 이미지 몽타주.
자막은 화자의 '영어 원문 그대로' 단어별로 싱크됨(번역 안 함). 넌 강조할 영어 단어만 고르면 됨.
브랜드: bodetail (남성 그루밍, 잉크블랙+골드)

[전체 대본 — 반드시 끝까지 다 읽고 판단할 것]
{json.dumps(sents,ensure_ascii=False,indent=2)}

[가장 중요한 선택 기준 — 반드시 지킬 것]
이건 그냥 "요약이 잘 되는 구간"을 고르는 게 아니야. 듣는 순간 소름 돋고 그대로
캡션으로 박제하고 싶은 **한 방짜리 명대사(quotable one-liner)** 가 반드시 포함된
구간을 찾아야 해. 예를 들면 이런 톤:
  - 짧고 단정적인 자기선언 ("I don't give a fuck", "Nobody's coming to save you")
  - 욕설·거친 표현이 섞여도 괜찮음 — 오히려 그게 화자 본연의 날것 그대로의 힘임.
    검열하거나 순화된 문장으로 대체하지 말고 대본에 실제로 있는 표현 그대로 골라.
  - 설명하거나 예시 드는 문장, 잔잔한 서사/일화 구간은 절대 고르지 마.
  - "아 이 말은 SNS에 캡션으로 박제될 만하다" 싶은 문장이 구간 안에 최소 1개
    반드시 있어야 함. 없으면 그 구간은 탈락.
  - 그런 문장 앞뒤로 말 사이 공백(pause)이 있다면 화자가 임팩트를 위해 쉰
    지점일 가능성이 높음 — 대본의 timestamp 간격을 참고해서 그런 지점을 우선 탐색.
  - 원본 전체를 훑어서 이런 문장이 여러 개 있으면, 그중 가장 강력한 것 하나를
    중심으로 {TARGET_DURATION}초 구간을 잡아. 도입부만 보고 대충 고르지 말 것.

[길이 제약] clip_end - clip_start 는 {TARGET_DURATION}초 ±20% 이내의 하나의 연속 구간.

[drop_at — 중요]
구간 안에서 그 '한 방짜리 명대사'가 끝나는 지점의 원본 초를 drop_at 으로.
이 시점 이후부터 화면이 이미지 몽타주로 전환됨. (clip_start+4 ~ clip_end-3 사이)

[emphasis_words] 선택 구간에서 골드로 강조할 '영어 단어'들(핵심 임팩트어 5~12개,
특히 그 한 방짜리 문장 안의 단어들 우선). 대본에 실제로 등장하는 단어 그대로.

순수 JSON만:
{{"clip_start":시작초,"clip_end":끝초,"drop_at":드롭초,
"hook_reason":"고른 이유 — 어떤 한 줄이 왜 임팩트 있는지 구체적으로",
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

def resolve_bgm_start(bgm):
    """BGM 트랙에서 '어디서부터' 잘라 쓸지 결정.
    이 지점부터 릴스 길이만큼 그대로 트림해서 영상 처음(0초)부터 씀.
    (영상의 감정 피크와 정렬시키는 게 아니라, 순수하게 '이 구간을 쓴다'는 선택)"""
    if BGM_START_ENV:
        try:
            v=max(0.0,float(BGM_START_ENV))
            print(f"  🎯 BGM 시작 지점(수동 지정): {v:.1f}초"); return v
        except: pass
    try:
        import librosa, numpy as np
        y,sr=librosa.load(str(bgm),sr=22050,duration=60)
        rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=512)[0]
        times=librosa.frames_to_time(np.arange(len(rms)),sr=sr,hop_length=512)
        sm=np.convolve(rms,np.ones(8)/8,mode='same')
        best_t,best=0.0,0.0
        for i in range(int(1.5*sr/512),len(sm)):
            prev=sm[max(0,i-40):i].mean()
            if sm[i]-prev>best: best=sm[i]-prev; best_t=float(times[i])
        print(f"  🎯 BGM 시작 지점(자동탐지 — 가장 고조되는 구간): {best_t:.1f}초")
        return best_t
    except Exception as e:
        print(f"  ⚠️ 자동탐지 실패({e}) → 0초부터"); return 0.0

# ══════════════════════════════════════════════════
# STEP 6: 영어 원문 단어싱크 자막 (한 단어씩 화면 중앙에 크게)
# ══════════════════════════════════════════════════
# 화자가 그 단어를 말하는 '실제 타임스탬프'(AssemblyAI)에 맞춰
# 한 단어만 화면 정중앙에 크게 떴다가 다음 단어로 교체됨 (LOOKING → because 식).
# 핵심 단어는 Anton 볼드 대문자, 연결어(because/and/so 등)는 Playfair Display
# 이탤릭 소문자 — 바이럴 릴스 특유의 '폰트 교차' 스타일. 강조어는 골드.

CONNECTOR_WORDS = {
    "because","and","but","so","if","when","while","since","as","that",
    "which","who","the","of","to","is","was","are","were","be","been",
    "with","for","in","on","at","or","not","no","yet","then","than",
    "you","your","i","it","its","a","an"
}

def ts(s):
    h=int(s//3600);m=int((s%3600)//60);sec=int(s%60);cs=int((s%1)*100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

def words_to_relative(words, clip_start, clip_dur):
    """AssemblyAI 절대(ms) 단어 리스트를 클립 기준 상대(초)로 변환+필터링.
    build_ass()와 편집용 JSON 저장(render()) 양쪽에서 공용으로 씀."""
    W=[]
    for w in words:
        s=w.get("start",0)/1000-clip_start; e=w.get("end",0)/1000-clip_start
        if e<=0 or s>=clip_dur: continue
        txt=str(w.get("text","")).strip()
        if not txt: continue
        W.append({"t":round(max(0.0,s),3),"e":round(min(clip_dur,e),3),"w":txt})
    return W

def build_ass(words, clip_start, clip_dur, emphasis, out):
    print("\n📝 STEP 6: 한 단어씩 중앙 자막 (폰트 교차)...")
    GOLD="&H004A84B0&"; WHITE="&H00FFFFFF&"
    hdr=f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RW}
PlayResY: {RH}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Bold,Anton,150,{WHITE},&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,1,0,1,7,4,5,60,60,0,1
Style: Italic,Playfair Display,138,{WHITE},&H000000FF,&H00000000,&H90000000,0,-1,0,0,100,100,1,0,1,6,3,5,60,60,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    # clip 범위 안 단어만(초 단위, clip 기준 상대시간)
    W=words_to_relative(words, clip_start, clip_dur)
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
        clean = x["w"].lower().strip(".,!?")
        is_connector = clean in CONNECTOR_WORDS
        ie = clean in emph
        col = GOLD if ie else WHITE
        if is_connector:
            style="Italic"; wt=x["w"].lower()
        else:
            style="Bold"; wt=x["w"].upper()
        tag=("{\\an5\\1c"+col+
             "\\fscx70\\fscy70\\t(0,80,\\fscx100\\fscy100)\\fad(30,20)}")
        ev.append("Dialogue: 0,"+ts(es)+","+ts(ee)+","+style+",,0,0,0,,"+tag+wt)
    Path(out).write_text(hdr+"\n".join(ev)+"\n",encoding="utf-8")
    print(f"  ✅ {len(ev)}개 단어 (Anton/Playfair 폰트 교차)")
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

def finalize(video_only,clip,bgm,ass,out,drop_t,dur,bgm_start):
    ae=str(ass).replace("\\","/").replace(":","\\:")
    inputs=["-i",str(video_only),"-i",str(clip)]
    bidx=None
    if bgm:
        bidx=2
        # 순수 트림: bgm_start초 지점부터 릴스 길이(dur)만큼 그대로 사용.
        # -stream_loop -1 로 트랙이 짧아도 항상 dur만큼 채워짐.
        inputs+=["-stream_loop","-1","-ss",f"{max(0.0,bgm_start):.3f}","-i",str(bgm)]
    fc=[f"[0:v]ass='{ae}'[vout]"]
    if bidx is not None:
        # 드롭 전: BGM 완전 무음(0) → 고긴스 목소리 풀볼륨으로 또렷하게 들림.
        # 드롭 순간: 0.05초 만에 확 치고 들어옴(펀치), 그 이후 목소리는 살짝 덕킹.
        # eval=frame 필수: 없으면 ffmpeg가 표현식을 처음 한 번만 계산해서
        # 시간에 따라 값이 절대 안 바뀜(이게 이전 버전의 실제 버그였음).
        ramp_end = drop_t + 0.05
        fc.append(
            f"[1:a]volume='if(lt(t,{drop_t:.3f}),1.0,0.7)':eval=frame[oa];"
            f"[{bidx}:a]volume='if(lt(t,{drop_t:.3f}),0,"
            f"if(lt(t,{ramp_end:.3f}),(t-{drop_t:.3f})/0.05*0.34,0.34))':eval=frame[bl];"
            "[oa][bl]amix=inputs=2:duration=first:normalize=0[aout]")
        amap=["-map","[aout]"]
    else:
        amap=["-map","1:a"]
    run(["ffmpeg","-y"]+inputs+["-filter_complex",";".join(fc),
        "-map","[vout]"]+amap+["-c:v","libx264","-preset","medium","-crf","20",
        "-c:a","aac","-b:a","192k","-ar","48000","-r",str(FPS),
        "-pix_fmt","yuv420p","-t",f"{dur:.3f}",str(out)],"finalize")
    return out

def save_edit_bundle(clip,bgm,bgm_start,valid_images,words,emphasis,clip_start,dur,drop_t,cuts,montage):
    """에디터(bodetail_editor.html)에서 이미지 교체 등 재편집이 가능하도록
    소스 클립/BGM/이미지/자막데이터를 reels/latest_a/assets/ 에 통째로 남김.
    이걸로 rerender_category_a.py가 유튜브 재다운로드·AssemblyAI·Claude 호출 없이
    ffmpeg만으로 빠르게 재렌더할 수 있음."""
    assets=LATEST/"assets"; imgdir=assets/"images"
    assets.mkdir(parents=True,exist_ok=True); imgdir.mkdir(parents=True,exist_ok=True)
    for old in imgdir.glob("*"): old.unlink()
    shutil.copy(clip, assets/"clip.mp4")
    img_names=[]
    for i,p in enumerate(valid_images):
        name=f"img_{i:02d}.jpg"
        shutil.copy(p, imgdir/name)
        img_names.append(name)
    bgm_saved=False
    if bgm:
        shutil.copy(bgm, assets/"bgm_used.mp3"); bgm_saved=True
    edit=dict(
        reel_duration=round(dur,3),
        drop_at_rel=round(drop_t,3),
        bgm_start=round(bgm_start,3) if bgm else 0.0,
        bgm_present=bgm_saved,
        montage=montage,
        cuts=[round(c,3) for c in cuts] if cuts else [],
        images=img_names,
        emphasis_words=list(emphasis or []),
        words=words_to_relative(words, clip_start, dur),
    )
    (LATEST/"direction_edit.json").write_text(json.dumps(edit,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  📝 편집용 에셋 저장 완료 (assets/, direction_edit.json) — 이미지 {len(img_names)}장")

def render(clip,dur,clip_start,beats,imgs,words,emphasis,bgm,bgm_start,drop_at):
    print(f"\n🎬 STEP 7: 합성...")
    valid=[p for p in imgs if p and Path(p).exists()]
    drop_t=drop_at-clip_start
    montage=(len(valid)>=2 and bool(bgm))
    if montage: drop_t=max(4.0,min(drop_t,dur-3.0))
    else:       drop_t=dur
    print(f"  드롭(영상 전환) {drop_t:.1f}초 | 몽타주 {'ON' if montage else 'OFF(영상 풀)'} | B롤 {len(valid)}장")

    ass=build_ass(words,clip_start,dur,emphasis,ASSETS/"subs.ass")
    pA=make_vertical(clip,ASSETS/"partA.mp4",0,drop_t)
    cuts=[]
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
    out=OUT_DIR/"reel_final.mp4"
    finalize(vo,clip,(bgm if bgm else None),ass,out,min(drop_t,dur),dur,bgm_start)
    print(f"  ✅ {out.name} ({out.stat().st_size/1024/1024:.1f}MB)")
    save_edit_bundle(clip,bgm,bgm_start,valid,words,emphasis,clip_start,dur,drop_t,cuts,montage)
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
def main():
    print(f"\n{'='*60}\n🎬 bodetail Category A v8 (20초 퐁크) | {DATE}\n   목표 {TARGET_DURATION}초 / {BEATS_PER_CUT}박자마다\n{'='*60}")
    if not ASSEMBLYAI_KEY or not ANTHROPIC_KEY:
        missing=[n for n,v in [("ASSEMBLYAI_API_KEY",ASSEMBLYAI_KEY),("ANTROPIC_API_KEY",ANTHROPIC_KEY)] if not v]
        raise RuntimeError(f"❌ 필수 시크릿 없음: {', '.join(missing)} — GitHub Secrets 확인해줘 (ANTROPIC_API_KEY는 H 빠진 오타 그대로여야 함)")

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
        if not vids:
            print("❌ 입력 없음.")
            raise SystemExit(1)
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
    bgm_start=resolve_bgm_start(bgm) if bgm else 0.0
    final=render(clip,dur,cs,beats,imgs,transcript.get("words",[]),
                 direction.get("emphasis_words",[]),bgm,bgm_start,drop_at)
    save_cleanup(final,direction,source_info)
    print(f"\n🎉 완료! → reels/latest_a/reel_final.mp4")

if __name__=="__main__":
    main()
