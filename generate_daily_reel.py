"""
generate_daily_reel.py — bodetail 릴스 자동화 v7
변경 핵심:
 - 자막을 PNG로 직접 렌더(둥근 흰박스+검은글씨), ASS 제거 → 위치/폰트 일관
 - 박스 위치 '상단(top) 고정' → 자막 길이 달라도 안 흔들림
 - 정규화 시 -shortest 로 비디오=오디오 길이 정렬 → 끝부분 버벅임/잡음 제거
 - subtitles.json 생성 → HTML 편집기로 위치/타이밍 미세조정 후 재렌더 가능
 - inbox 에 subtitles.json 있으면 그 좌표 그대로 사용(편집본 우선)
 - 아웃트로: bodetail(위 큰글씨) → 골드바2개 → @계정 팔로우(아래) 순서 고정
"""

import os, json, re, requests, subprocess, time, shutil, base64
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
REEL_DURATION_A = 28
OUTRO_DURATION  = 7

DARK=(8,6,4); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240)

SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

# 자막(=썸네일 제목과 동일 Black 폰트로 통일)
KO_SUB_FONT_FILE = SANS_BLK
KO_SUB_SIZE      = 60
BOX_RADIUS       = 30
BOX_PAD_X        = 38
BOX_PAD_Y        = 22
BOX_MAX_TEXT_W   = 600          # 박스 내부 텍스트 최대 폭(넘으면 줄바꿈)
LINE_SPACING     = 1.22

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
    list(INBOX.glob("*.mp4")) + list(INBOX.glob("*.mov")) +
    list(INBOX.glob("*.MP4")) + list(INBOX.glob("*.MOV"))
)
MODE = "B" if inbox_videos else "A"
print(f"📱 모드: {'B (inbox 영상)' if MODE=='B' else 'A (Pexels)'}")

if MODE == "A":
    day_override = os.environ.get("DAY_OVERRIDE", "").strip()
    with open("content/topics_30.json","r",encoding="utf-8") as f:
        schedule = json.load(f)
    if day_override:
        day_num = int(day_override)
    else:
        start_date = datetime(2026,9,15,tzinfo=KST)
        day_num = (max(0,(TODAY-start_date).days) % 30) + 1
    topic = next((t for t in schedule["topics"] if t["day"]==day_num), schedule["topics"][0])
    print(f"📅 DAY {day_num} | {topic['title_main']}")

# ══════════════════════════════════════════════════════════════
# 3. FFmpeg 유틸
# ══════════════════════════════════════════════════════════════
def get_video_duration(video_path) -> float:
    r = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
        "-show_streams",str(video_path)], capture_output=True,text=True,timeout=30)
    info = json.loads(r.stdout)
    for s in info.get("streams",[]):
        if s.get("codec_type")=="video":
            d=s.get("duration")
            if d: return float(d)
    r2 = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
        "-show_format",str(video_path)], capture_output=True,text=True,timeout=30)
    return float(json.loads(r2.stdout).get("format",{}).get("duration",20.0))

def has_audio(video_path) -> bool:
    r = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
        "-show_streams",str(video_path)], capture_output=True,text=True,timeout=30)
    for s in json.loads(r.stdout).get("streams",[]):
        if s.get("codec_type")=="audio": return True
    return False

def normalize_video(src: Path) -> Path:
    """원본 → 1080x1920 / 30fps / 48kHz, ★-shortest 로 v=a 길이 정렬(버벅임 제거)"""
    out = OUT / "normalized.mp4"
    audio = has_audio(src)
    cmd = ["ffmpeg","-y","-i",str(src),
        "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
        "-c:v","libx264","-crf","18","-preset","fast","-pix_fmt","yuv420p"]
    if audio:
        cmd += ["-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest"]
    else:
        # 무음 트랙 추가(이후 concat 일관성)
        cmd = ["ffmpeg","-y","-i",str(src),
            "-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
            "-c:v","libx264","-crf","18","-preset","fast","-pix_fmt","yuv420p",
            "-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest"]
    cmd += ["-movflags","+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    return out

# ══════════════════════════════════════════════════════════════
# 4. Inbox 처리 (편집본 subtitles.json 우선)
# ══════════════════════════════════════════════════════════════
def process_inbox():
    video = max(inbox_videos, key=lambda f: f.stat().st_mtime)
    cf = video.parent/"credit.txt"
    hf = video.parent/"headline.txt"
    sf = video.parent/"subtitles.json"      # 편집본
    credit   = cf.read_text("utf-8").strip() if cf.exists() else ""
    headline = hf.read_text("utf-8").strip() if hf.exists() else ""
    edited   = None
    if sf.exists():
        try:
            edited = json.loads(sf.read_text("utf-8"))
            print("  📝 편집본 subtitles.json 발견 → 그 좌표/타이밍 사용")
        except Exception as e:
            print(f"  ⚠️ subtitles.json 파싱 실패: {e}")
    print(f"  선택 영상: {video.name}")
    if headline: print(f"  📝 수동 헤드라인: {headline}")
    return video, credit, headline, edited

# ══════════════════════════════════════════════════════════════
# 5. 타임라인 프레임 추출
# ══════════════════════════════════════════════════════════════
def extract_timeline_frames(video_path: Path) -> list:
    duration = get_video_duration(video_path)
    n = max(8, min(int(duration), 40))
    step = duration / n
    frames=[]
    for i in range(n):
        t = step*i + step*0.5
        fp = OUT/f"tl_{i:02d}.jpg"
        try:
            subprocess.run(["ffmpeg","-y","-ss",f"{t:.2f}","-i",str(video_path),
                "-frames:v","1","-vf","scale=540:960",str(fp)],
                check=True,capture_output=True,timeout=15)
            if fp.exists():
                with open(fp,"rb") as f:
                    b64=base64.standard_b64encode(f.read()).decode("utf-8")
                frames.append({"index":i,"path":fp,"b64":b64,"time":round(t,2)})
        except Exception as e:
            print(f"  ⚠️ 프레임{i} 실패: {e}")
    return frames

# ══════════════════════════════════════════════════════════════
# 6. Vision — 자막 내용 + 시간대 + 대략 위치(상단/중단/하단)만
#    ※ 픽셀좌표는 신뢰 안함. position 영역만 받아서 일관 배치
# ══════════════════════════════════════════════════════════════
def detect_subtitles(frames: list) -> dict:
    print("  🔍 자막 내용·시간·영역 분석 중...")
    content=[{
        "type":"text",
        "text":"""이미지들은 한 영상을 1초 간격으로 캡처한 540x960(세로) 프레임이야. 순서대로다.

영상에 '박혀있는 자막'(영어/한국어 자막, 노란박스 텍스트 등)을 읽어서,
같은 자막이 연속되는 구간을 하나로 묶어줘.

각 자막 구간마다:
- text_en: 그 자막 원문(영어면 영어 그대로)
- start_i, end_i: 시작/끝 프레임 인덱스(i)
- region: 자막이 화면에서 위치한 세로 영역. "top"(상단 1/3) / "middle"(중앙) / "bottom"(하단 1/3) 중 하나

워터마크(@아이디), 작은 인스타 로고는 자막이 아니야. 무시.
화면에 진짜 자막이 하나도 없으면 빈 배열.

순수 JSON만 (코드블록 금지):
{"segments":[
 {"text_en":"You will solve imbalance and scoliosis","start_i":3,"end_i":6,"region":"top"},
 {"text_en":"If you can complete this 100 times daily","start_i":7,"end_i":11,"region":"middle"}
]}"""
    }]
    for fr in frames:
        content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":fr["b64"]}})
        content.append({"type":"text","text":f"[i={fr['index']} / {fr['time']}초]"})

    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=3000,
        messages=[{"role":"user","content":content}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    data=json.loads(raw)
    segs=data.get("segments",[])
    print(f"  ✅ 자막 구간 {len(segs)}개 감지")
    return segs

# ══════════════════════════════════════════════════════════════
# 7. 구간 → 시간/위치 변환 (region별 고정 Y → 위치 일관)
# ══════════════════════════════════════════════════════════════
REGION_TOP_Y = {       # 박스 '상단' 기준 Y (1080x1920 기준). 상단 고정 → 안 흔들림
    "top":    330,
    "middle": 820,
    "bottom": 1380,
}

def segments_to_timed(segs, frames):
    if not frames: return []
    step = frames[1]["time"]-frames[0]["time"] if len(frames)>1 else 1.0
    t_of = {fr["index"]:fr["time"] for fr in frames}
    out=[]
    for s in segs:
        si=int(s.get("start_i",0)); ei=int(s.get("end_i",si))
        st = t_of.get(si, si*step) - step*0.5
        en = t_of.get(ei, ei*step) + step*0.5
        st = max(0.0, round(st,2)); en = round(en,2)
        if en-st < 1.0: en = st+1.0
        region = s.get("region","top")
        if region not in REGION_TOP_Y: region="top"
        out.append({
            "text_en": s.get("text_en","").strip(),
            "start": st, "end": en,
            "region": region,
            "top_y": REGION_TOP_Y[region],   # 박스 상단 Y(고정)
        })
    # 겹침 제거: 다음 시작=이전 끝
    out.sort(key=lambda x:x["start"])
    for i in range(len(out)-1):
        if out[i]["end"] > out[i+1]["start"]:
            mid=(out[i]["end"]+out[i+1]["start"])/2
            out[i]["end"]=round(mid,2); out[i+1]["start"]=round(mid,2)
    return out

# ══════════════════════════════════════════════════════════════
# 8. Vision STEP2 — 번역 + 캡션 + 썸네일
# ══════════════════════════════════════════════════════════════
def translate_and_generate(timed, frames, headline_override, credit_text):
    print("  🤖 번역·캡션 생성 중...")
    en_list="\n".join([f"{i+1}. {s['text_en']}" for i,s in enumerate(timed)]) or "(자막 없음)"
    hint=f'\n★ thumbnail_headline 은 반드시 이대로: "{headline_override}"' if headline_override else ""
    content=[{
        "type":"text",
        "text":f"""너는 bodetail 한국 남성 그루밍·라이프스타일 릴스 편집자야.

시간순 감지 자막 {len(timed)}개:
{en_list}

각 자막을 자연스러운 한국어로 번역하고 캡션·썸네일을 만들어.

★ translations: 위와 같은 개수·순서. 직역 금지. 인스타 릴스 톤. ~다/~하라/~된다 체.
  한 줄에 다 들어가게 짧고 임팩트 있게. 굳이 길게 늘리지 마.
★ thumbnail_headline: 부담스러운 큰 숫자(100번 등) 금지. 매력·결과 중심.{hint}
★ caption_full: 후킹 질문 첫줄 / (광고 아님 · 영상 저장 추천 🔖) / 도입 1~2문장 /
  번호별 핵심(①②③ 소제목—설명) / 해시태그는 hashtags 필드에 따로.

순수 JSON만 (코드블록 금지):
{{"video_topic":"주제","thumbnail_headline":"헤드라인","thumbnail_sub":"POSTURE",
"best_frame_time":5.0,"translations":["자막1","자막2"],
"caption_full":"캡션","hashtags":"#bodetail ..."}}

best_frame_time: 인물이 잘 보이고 자막이 적은 프레임 시점(초)."""
    }]
    pick=frames[::max(1,len(frames)//5)][:5] if frames else []
    for fr in pick:
        content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":fr["b64"]}})
        content.append({"type":"text","text":f"[{fr['time']}초]"})
    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=3000,
        messages=[{"role":"user","content":content}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    result=json.loads(raw)
    trans=result.get("translations",[])
    for i,s in enumerate(timed):
        s["text_ko"]=trans[i] if i<len(trans) else s["text_en"]
    if headline_override: result["thumbnail_headline"]=headline_override
    print(f"  ✅ 생성: {result.get('video_topic','')}")
    return result

# ══════════════════════════════════════════════════════════════
# 9. 자막 줄바꿈 계산 (박스 폭 기준 단어→글자 순)
# ══════════════════════════════════════════════════════════════
def wrap_ko(text, font, max_w):
    dd=ImageDraw.Draw(Image.new("RGB",(10,10)))
    text=text.replace("\\n"," ").strip()
    # 1차: 공백 단위
    if " " in text:
        words=text.split(); lines=[]; cur=""
        for w in words:
            trial=w if cur=="" else cur+" "+w
            if dd.textlength(trial,font=font)<=max_w: cur=trial
            else:
                if cur: lines.append(cur)
                cur=w
        if cur: lines.append(cur)
    else:
        lines=[text]
    # 2차: 한 줄이 여전히 너무 길면 글자 단위로 쪼갬
    final=[]
    for line in lines:
        if dd.textlength(line,font=font)<=max_w:
            final.append(line); continue
        cur=""
        for ch in line:
            if dd.textlength(cur+ch,font=font)<=max_w: cur+=ch
            else: final.append(cur); cur=ch
        if cur: final.append(cur)
    return final or [text]

# ══════════════════════════════════════════════════════════════
# 10. 자막 레이아웃 (상단 고정 + 박스크기 자동)
# ══════════════════════════════════════════════════════════════
def layout_subtitle(seg):
    font=fnt(KO_SUB_FONT_FILE,KO_SUB_SIZE)
    dd=ImageDraw.Draw(Image.new("RGB",(10,10)))
    ko=seg.get("text_ko") or seg.get("text_en","")
    lines=wrap_ko(ko,font,BOX_MAX_TEXT_W)
    line_h=int(KO_SUB_SIZE*LINE_SPACING)
    text_w=max(dd.textlength(l,font=font) for l in lines)
    text_h=line_h*len(lines)
    box_w=int(text_w+BOX_PAD_X*2)
    box_h=int(text_h+BOX_PAD_Y*2)
    # 편집본이 좌표를 줬으면 그걸 우선
    if "box_x" in seg and "box_y" in seg:
        box_x=int(seg["box_x"]); box_y=int(seg["box_y"])
    else:
        box_x=int(RW/2 - box_w/2)          # 가로 중앙
        box_y=int(seg.get("top_y", 330))   # 세로 상단 고정
    box_x=max(8,min(box_x,RW-box_w-8))
    box_y=max(8,min(box_y,RH-box_h-8))
    seg["box"]={"x":box_x,"y":box_y,"w":box_w,"h":box_h}
    seg["lines"]=lines
    return seg

# ══════════════════════════════════════════════════════════════
# 11. 자막 PNG 렌더 (둥근 흰박스 + 검은글씨)
# ══════════════════════════════════════════════════════════════
def render_subtitle_png(seg, idx) -> Path:
    b=seg["box"]; font=fnt(KO_SUB_FONT_FILE,KO_SUB_SIZE)
    img=Image.new("RGBA",(b["w"],b["h"]),(0,0,0,0))
    d=ImageDraw.Draw(img)
    d.rounded_rectangle([(0,0),(b["w"]-1,b["h"]-1)],radius=BOX_RADIUS,fill=(255,255,255,255))
    line_h=int(KO_SUB_SIZE*LINE_SPACING)
    y=BOX_PAD_Y
    for line in seg["lines"]:
        w=d.textlength(line,font=font)
        d.text(((b["w"]-w)//2,y),line,font=font,fill=(15,15,15,255))
        y+=line_h
    p=OUT/f"sub_{idx:02d}.png"; img.save(p,"PNG")
    return p

# ══════════════════════════════════════════════════════════════
# 12. subtitles.json 저장 (HTML 편집기 입출력 포맷)
# ══════════════════════════════════════════════════════════════
def save_subtitles_json(timed, dur, video_rel):
    data={
        "video": video_rel,
        "duration": round(dur,2),
        "canvas": {"w": RW, "h": RH},
        "font_size": KO_SUB_SIZE,
        "subtitles": []
    }
    for s in timed:
        b=s["box"]
        data["subtitles"].append({
            "text_en": s.get("text_en",""),
            "text_ko": s.get("text_ko",""),
            "start": s["start"], "end": s["end"],
            "box_x": b["x"], "box_y": b["y"], "box_w": b["w"], "box_h": b["h"],
        })
    (OUT/"subtitles.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return data

# ══════════════════════════════════════════════════════════════
# 13. A모드 콘텐츠 / 간단 자막
# ══════════════════════════════════════════════════════════════
def make_content_without_vision(source_info):
    prompt=f"""너는 bodetail 릴스 편집자야.
주제: {topic['title_main'] if MODE=='A' else '남성 라이프스타일'}
섹션: {topic['section'] if MODE=='A' else 'LIFESTYLE'}
소스: {source_info}
★자막 5~7개 각3~5초 18자이내 선언형 ★썸네일 큰숫자금지 ★캡션 후킹/(광고 아님 · 영상 저장 추천 🔖)/번호별/해시태그
순수 JSON:
{{"video_topic":"주제","thumbnail_headline":"헤드라인","thumbnail_sub":"DETAIL",
"captions":[{{"text":"자막","duration":4}}],"caption_full":"캡션","hashtags":"#bodetail ..."}}"""
    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=2048,
        messages=[{"role":"user","content":prompt}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    return json.loads(raw)

# ══════════════════════════════════════════════════════════════
# 14. Pexels (A모드)
# ══════════════════════════════════════════════════════════════
def load_used_reels():
    if USED_F.exists():
        try: return set(json.loads(USED_F.read_text("utf-8")))
        except: return set()
    return set()
def save_used_reels(ids):
    USED_F.parent.mkdir(parents=True,exist_ok=True)
    USED_F.write_text(json.dumps(list(ids)[-300:],ensure_ascii=False),encoding="utf-8")
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
            params={"query":sanitize_q(query),"per_page":15,"orientation":"portrait","size":"large"},timeout=15)
        vids=r.json().get("videos",[]);used=load_used_reels();fb=None
        for v in vids:
            vid=str(v["id"])
            files=sorted(v.get("video_files",[]),key=lambda f:f.get("width",0)*f.get("height",0),reverse=True)
            if not files: continue
            url=files[0]["link"]
            if fb is None: fb=(vid,url)
            if vid not in used: return vid,url
        return fb if fb else (None,None)
    except Exception as e:
        print(f"⚠️ Pexels: {e}");return None,None
def download_video(url,out):
    try:
        r=requests.get(url,stream=True,timeout=60)
        with open(out,"wb") as f:
            for ch in r.iter_content(chunk_size=1024*1024): f.write(ch)
        return True
    except Exception as e:
        print(f"⚠️ 다운로드 실패: {e}");return False
VIDEO_QUERIES={"손톱":["man hands nails closeup dark moody"],"핸드크림":["man applying hand cream dark"],
    "면도":["man shaving dark cinematic"],"향수":["men cologne bottle dark cinematic"],
    "피부":["man skincare dark editorial"],"헤어":["man hair grooming dark"],
    "슈트":["man suit dark cinematic"],"운동":["man gym workout dark"]}
def get_video_queries():
    title=topic.get("title_main","")
    for kw,q in VIDEO_QUERIES.items():
        if kw in title: return q+["man grooming dark moody"]
    return [f"man {topic.get('image_search','grooming')} dark cinematic","male dark editorial moody"]

def make_ass_simple(captions,ass_path):
    header=("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,"
        "Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Main,Noto Sans CJK KR,58,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,"
        "100,100,0,0,1,3,2,2,40,40,170,1\n\n[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    def fmt(t):
        h=int(t//3600);m=int((t%3600)//60);s=t%60;return f"{h}:{m:02d}:{s:05.2f}"
    ev=[];cur=0.0
    for c in captions:
        dur=float(c.get("duration",4));txt=c["text"].replace("\n","\\N")
        ev.append(f"Dialogue: 0,{fmt(cur)},{fmt(cur+dur)},Main,,0,0,0,,{txt}");cur+=dur
    Path(ass_path).write_text(header+"\n".join(ev),encoding="utf-8");return cur

# ══════════════════════════════════════════════════════════════
# 15. 아웃트로 — bodetail(위) → 골드바2개 → @팔로우(아래) 순서 고정
#     골드바 위아래 간격 동일
# ══════════════════════════════════════════════════════════════
def make_outro_image() -> Path:
    img=Image.new("RGB",(RW,RH),DARK)
    arr=np.array(img,dtype=np.int16)
    img=Image.fromarray(np.clip(arr+np.random.randint(-6,6,arr.shape,dtype=np.int16),0,255).astype(np.uint8))
    draw=ImageDraw.Draw(img); cx=RW//2; cy=RH//2

    # 1) bodetail 워드마크 (제일 위, 큰 글씨)
    wf=fnt(SERIF_B,112); wt="bodetail"
    bb=draw.textbbox((0,0),wt,font=wf); ww=bb[2]-bb[0]
    wm_y = cy-220
    draw.text((cx-ww//2, wm_y), wt, font=wf, fill=(*CREAM,230))
    wm_bottom = wm_y + 138   # 폰트 실제 하강 고려(112보다 여유)

    # 2) 카피 (한 줄)
    cf=fnt(SANS_LT,40); copy="남들이 놓치는 디테일이 궁금하다면"
    bb=draw.textbbox((0,0),copy,font=cf); cw=bb[2]-bb[0]
    copy_y = wm_bottom + 60
    draw.text((cx-cw//2, copy_y), copy, font=cf, fill=(*CREAM,225))

    # 3) 골드바 2개 — 카피만 위/아래 동일 간격(gap)으로 감쌈
    bar_w,bar_h=64,3; gap=22
    draw.rectangle([(cx-bar_w//2, copy_y-gap-bar_h),(cx+bar_w//2, copy_y-gap)], fill=GOLD)
    draw.rectangle([(cx-bar_w//2, copy_y+50+gap),(cx+bar_w//2, copy_y+50+gap+bar_h)], fill=GOLD)

    # 4) @계정 팔로우 (제일 아래, 골드)
    ctaf=fnt(SANS_MED,34); cta="@bodetail_official 팔로우"
    bb=draw.textbbox((0,0),cta,font=ctaf); w=bb[2]-bb[0]
    draw.text((cx-w//2, copy_y+50+gap+bar_h+44), cta, font=ctaf, fill=(*GOLD_BRIGHT,255))

    p=OUT/"outro.png"; img.save(p,"PNG"); return p

def make_wordmark_overlay() -> Path:
    ov=Image.new("RGBA",(RW,80),(0,0,0,0));draw=ImageDraw.Draw(ov)
    sf=fnt(SANS_MED,34);t="bodetail"
    bb=draw.textbbox((0,0),t,font=sf);w=bb[2]-bb[0]
    draw.text(((RW-w)//2,22),t,font=sf,fill=(*CREAM,160))
    p=OUT/"wordmark.png";ov.save(p,"PNG");return p

# ══════════════════════════════════════════════════════════════
# 16. 썸네일 — 자막 없는 프레임 우선, 없으면 자막영역만 살짝 가림
# ══════════════════════════════════════════════════════════════
def extract_full_frame(video_path,t) -> Path:
    p=OUT/"thumb_src.jpg"
    subprocess.run(["ffmpeg","-y","-ss",f"{t:.2f}","-i",str(video_path),
        "-frames:v","1","-vf","scale=1080:1920",str(p)],check=True,capture_output=True,timeout=30)
    return p if p.exists() else None

def pick_clean_frame_time(timed, frames, fallback_t):
    busy=[(s["start"],s["end"]) for s in timed]
    cands=sorted(frames,key=lambda f:abs(f["time"]-fallback_t))
    for fr in cands:
        t=fr["time"]
        if not any(a<=t<=b for a,b in busy):
            return t, True
    return fallback_t, False

def make_thumbnail(headline,sub_label,source_frame=None) -> Path:
    W_T,H_T=1080,1440
    Xg,Yg=np.meshgrid(np.arange(W_T),np.arange(H_T))
    if source_frame and Path(source_frame).exists():
        # 1920 프레임을 1440에 center-crop (위/아래 살짝 잘라 인물 중심 유지)
        src=Image.open(source_frame).convert("RGB")
        if src.size!=(W_T,1920):
            src=src.resize((W_T,1920),Image.LANCZOS)
        top=(1920-H_T)//2
        src=src.crop((0,top,W_T,top+H_T))
        base=np.array(src,dtype=np.float32)
        gray=0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base=gray[:,:,None]*0.5+base*0.5; base*=0.86
    else:
        base=np.zeros((H_T,W_T,3),dtype=np.float32);base[:]=list(DARK)
        d=np.sqrt(((Xg-W_T*0.5)/350.)**2+((Yg-H_T*0.55)/400.)**2)
        g=np.clip(1-d,0,1)*0.32
        base[:,:,0]+=g*75;base[:,:,1]+=g*62;base[:,:,2]+=g*45
    ink=np.array(DARK,dtype=np.float32)[None,None,:]
    base=base*0.62+ink*0.38
    # 하단만 어둡게(텍스트 가독성) — 상단 인물은 보존
    yv=np.linspace(0,1,H_T)[:,None]
    fade=np.clip((yv-0.50)/0.50,0,1)**1.5*0.82
    m=np.repeat(fade[:,:,None],W_T,axis=1);base=base*(1-m)+ink*m
    img=Image.fromarray(np.clip(base,0,255).astype(np.uint8));draw=ImageDraw.Draw(img)

    lf=fnt(SANS_MED,28)
    draw.text((84,84),"오늘의 디테일",font=lf,fill=GOLD)
    lw=draw.textlength("오늘의 디테일",font=lf)
    draw.line([(84+lw+20,102),(W_T-84,102)],fill=(*GOLD,160),width=2)

    bf=fnt(SANS_MED,24);bb=draw.textbbox((0,0),sub_label,font=bf)
    bw,bh=bb[2]-bb[0],bb[3]-bb[1];bx,by=84,142
    draw.rectangle([(bx,by),(bx+bw+32,by+bh+20)],outline=(*CREAM,110),width=2)
    draw.text((bx+16-bb[0],by+10-bb[1]),sub_label,font=bf,fill=(*CREAM,150))

    max_w=W_T-84*2;fsize=96
    while fsize>54:
        mf=fnt(SANS_BLK,fsize)
        lines=wrap_ko(headline,mf,max_w)
        lh=int(fsize*1.16)
        if len(lines)*lh<=360: break
        fsize-=6
    y=H_T-92-len(lines)*lh
    for line in lines:
        draw.text((84,y),line,font=mf,fill=WHITE);y+=lh

    sf=fnt(SANS_MED,26);t="bodetail";sw=draw.textlength(t,font=sf)
    draw.text(((W_T-sw)//2,H_T-56),t,font=sf,fill=(*CREAM,190))
    p=OUT/"thumbnail_1080x1440.png";img.save(p,"PNG");return p

# ══════════════════════════════════════════════════════════════
# 17. FFmpeg 합성 (B) — 자막 PNG overlay + 안전 concat
# ══════════════════════════════════════════════════════════════
def build_reel_B(normalized, timed, sub_pngs, outro_img, wordmark_img) -> Path:
    processed=OUT/"processed.mp4"; outro_vid=OUT/"outro.mp4"; final=OUT/"reel_final.mp4"

    inputs=["-i",str(normalized),"-i",str(wordmark_img)]
    for png in sub_pngs: inputs+=["-i",str(png)]

    fc=[]
    fc.append("[0:v][1:v]overlay=(W-w)/2:H-100:format=auto[v1]")
    last="v1"
    for k,seg in enumerate(timed):
        inp=k+2
        b=seg["box"]; nxt=f"v{k+2}"
        fc.append(f"[{last}][{inp}:v]overlay={b['x']}:{b['y']}:"
                  f"enable='between(t,{seg['start']:.2f},{seg['end']:.2f})'[{nxt}]")
        last=nxt
    filter_complex=";".join(fc)

    subprocess.run(["ffmpeg","-y",*inputs,
        "-filter_complex",filter_complex,"-map",f"[{last}]","-map","0:a?",
        "-c:v","libx264","-crf","20","-preset","fast","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(processed)],check=True,capture_output=True,timeout=500)
    print("  ✅ 메인 처리 완료")

    # 아웃트로 (정확히 7초, 무음 48kHz, -shortest)
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(outro_img),
        "-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t",str(OUTRO_DURATION),"-c:v","libx264","-pix_fmt","yuv420p","-r","30",
        "-vf","scale=1080:1920","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-shortest","-movflags","+faststart",str(outro_vid)],check=True,capture_output=True,timeout=60)
    print("  ✅ 아웃트로 완료")

    # filter concat (멈춤/잡음 방지)
    subprocess.run(["ffmpeg","-y","-i",str(processed),"-i",str(outro_vid),
        "-filter_complex","[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map","[v]","-map","[a]","-c:v","libx264","-crf","20","-preset","fast",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(final)],check=True,capture_output=True,timeout=240)
    print("  ✅ 최종 합성 완료")
    return final

def build_reel_A(source_video,ass_path,outro_img,wordmark_img) -> Path:
    processed=OUT/"processed.mp4"; outro_vid=OUT/"outro.mp4"; final=OUT/"reel_final.mp4"
    subprocess.run(["ffmpeg","-y","-stream_loop","-1","-i",str(source_video),"-i",str(wordmark_img),
        "-t",str(REEL_DURATION_A),"-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[base];"
        f"[base]ass={ass_path}[sub];[sub][1:v]overlay=(W-w)/2:H-100:format=auto[out]",
        "-map","[out]","-map","0:a?","-c:v","libx264","-crf","20","-preset","fast",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(processed)],check=True,capture_output=True,timeout=300)
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(outro_img),
        "-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t",str(OUTRO_DURATION),"-c:v","libx264","-pix_fmt","yuv420p","-r","30",
        "-vf","scale=1080:1920","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-shortest","-movflags","+faststart",str(outro_vid)],check=True,capture_output=True,timeout=60)
    subprocess.run(["ffmpeg","-y","-i",str(processed),"-i",str(outro_vid),
        "-filter_complex","[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map","[v]","-map","[a]","-c:v","libx264","-crf","20","-preset","fast",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(final)],check=True,capture_output=True,timeout=180)
    return final

# ══════════════════════════════════════════════════════════════
# 18. Instagram
# ══════════════════════════════════════════════════════════════
def upload_to_github_release(filepath,filename):
    if not GITHUB_TOKEN or not REPO: return None
    h={"Authorization":f"token {GITHUB_TOKEN}","Accept":"application/vnd.github.v3+json"}
    rs=requests.get(f"https://api.github.com/repos/{REPO}/releases",headers=h,timeout=15).json()
    tr=next((r for r in rs if r.get("tag_name")=="temp-reels"),None)
    if not tr:
        tr=requests.post(f"https://api.github.com/repos/{REPO}/releases",headers=h,timeout=15,
            json={"tag_name":"temp-reels","name":"Temp","body":"auto","draft":False,"prerelease":True}).json()
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
    if r.status_code!=200: print(f"⚠️ 컨테이너 실패: {r.text[:200]}");return False
    cid=r.json().get("id")
    for i in range(60):
        time.sleep(10)
        code=requests.get(f"{B}/{cid}",params={"fields":"status_code","access_token":IG_TOKEN},timeout=30).json().get("status_code","")
        print(f"    [{i+1}/60] {code}")
        if code=="FINISHED": break
        if code in ("ERROR","EXPIRED"): return False
    else: return False
    pub=requests.post(f"{B}/{IG_USER_ID}/media_publish",params={"creation_id":cid,"access_token":IG_TOKEN},timeout=30)
    if pub.status_code==200: print("  ✅ 게시 완료!");return True
    return False

# ══════════════════════════════════════════════════════════════
# 19. 메인
# ══════════════════════════════════════════════════════════════
print("\n"+"="*60)
print(f"🎬 bodetail 릴스 자동화 v7 | {DATE} | 모드 {MODE}")
print("="*60)

used_ids=load_used_reels();content={};caption_full="";thumb=None;final_reel=None;credit_text=""
timed=[]; dur=0.0; normalized=None

if MODE=="B":
    src,credit_text,headline_override,edited=process_inbox()
    print("\n🎞️ 정규화(1080x1920/30fps/48kHz, v=a 정렬)...")
    normalized=normalize_video(src)
    dur=get_video_duration(normalized)
    print(f"  ✅ 길이 {dur:.1f}초")
    frames=[]   # 썸네일/번역에서 공용으로 쓰는 프레임 캐시

    if edited and edited.get("subtitles"):
        # ── 편집본 경로: HTML에서 다듬은 좌표/타이밍/텍스트 그대로 ──
        print("  ✏️ 편집본 좌표/타이밍 사용 (Vision 건너뜀)")
        for s in edited["subtitles"]:
            timed.append({
                "text_en": s.get("text_en",""), "text_ko": s.get("text_ko",""),
                "start": float(s["start"]), "end": float(s["end"]),
                "box_x": int(s["box_x"]), "box_y": int(s["box_y"]),
            })
        # 캡션/썸네일은 편집본에 있으면 쓰고 없으면 생성
        content = edited.get("content") or {}
        if not content:
            frames=extract_timeline_frames(normalized)
            content=translate_and_generate(timed,frames,headline_override,credit_text)
    else:
        # ── 자동 경로 ──
        print("\n🔍 타임라인 프레임...")
        frames=extract_timeline_frames(normalized)
        print(f"  ✅ {len(frames)}프레임")
        segs=detect_subtitles(frames)
        timed=segments_to_timed(segs,frames)
        content=translate_and_generate(timed,frames,headline_override,credit_text)

    # 레이아웃 + PNG
    for s in timed: layout_subtitle(s)
    sub_pngs=[render_subtitle_png(s,i) for i,s in enumerate(timed)]

    # subtitles.json 저장 (편집기 입력용)
    save_subtitles_json(timed,dur,"normalized.mp4")

    credit_line = f"\n\n📹 | {credit_text}" if credit_text else ""
    caption_full=(f"{content.get('caption_full','')}\n\n{content.get('hashtags','')}"
        f"{credit_line}\n\n"
        f"Start Every Detail with Awareness Now\n—\n"
        f"내 외모의 최고 버전이 궁금하다면? @bodetail_official")
    (OUT/"caption.txt").write_text(caption_full,encoding="utf-8")
    print(f"  ✅ 자막 {len(timed)}개 / 캡션")

    print("\n🎨 이미지 에셋...")
    outro_img=make_outro_image(); wordmark_img=make_wordmark_overlay()

    # 썸네일: 자막 없는 프레임 우선
    if not frames:
        frames=extract_timeline_frames(normalized)
    fb_t=float(content.get("best_frame_time",dur*0.45))
    fb_t=max(0.5,min(fb_t,dur-0.5))
    clean_t,is_clean=pick_clean_frame_time(timed,frames,fb_t)
    bf=extract_full_frame(normalized,clean_t)
    print(f"  ✅ 썸네일 프레임 {clean_t:.1f}초 ({'자막없음' if is_clean else '자막구간'})")
    thumb=make_thumbnail(content.get("thumbnail_headline","오늘의 디테일"),
        content.get("thumbnail_sub","DETAIL"),bf)

    print("\n🎬 FFmpeg 합성...")
    final_reel=build_reel_B(normalized,timed,sub_pngs,outro_img,wordmark_img)

else:
    raw_video=OUT/"source.mp4"
    queries=get_video_queries();vid_id=vid_url=None
    for q in queries:
        vid_id,vid_url=search_pexels_video(q)
        if vid_id: break
    if not vid_id:
        subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=c=black:size=1080x1920:r=30",
            "-t",str(REEL_DURATION_A),"-c:v","libx264","-pix_fmt","yuv420p",str(raw_video)],
            capture_output=True,timeout=60)
    else:
        used_ids.add(str(vid_id));download_video(vid_url,raw_video)
    credit_text="Pexels (상업적 무료)"
    content=make_content_without_vision(credit_text)
    caption_full=(f"{content['caption_full']}\n\n{content['hashtags']}\n\n📹 | {credit_text}\n\n"
        f"Start Every Detail with Awareness Now\n—\n내 외모의 최고 버전이 궁금하다면? @bodetail_official")
    (OUT/"caption.txt").write_text(caption_full,encoding="utf-8")
    ass_path=str(OUT/"subtitles.ass");make_ass_simple(content["captions"],ass_path)
    outro_img=make_outro_image();wordmark_img=make_wordmark_overlay()
    fp=OUT/"frame.jpg"
    subprocess.run(["ffmpeg","-y","-ss","3","-i",str(raw_video),"-frames:v","1",
        "-vf","scale=1080:1920",str(fp)],capture_output=True,timeout=30)
    thumb=make_thumbnail(content["thumbnail_headline"],content.get("thumbnail_sub","DETAIL"),
        fp if fp.exists() else None)
    final_reel=build_reel_A(raw_video,ass_path,outro_img,wordmark_img)

size_mb=final_reel.stat().st_size//1024//1024
print(f"  ✅ 완성: {final_reel.name} ({size_mb}MB)")
save_used_reels(used_ids)

# latest 복사 (+ 편집용 파일들)
latest=Path("reels/latest");latest.mkdir(exist_ok=True)
shutil.copy(final_reel,latest/"reel_final.mp4")
shutil.copy(thumb,latest/"thumbnail_1080x1440.png")
(latest/"caption.txt").write_text(caption_full,encoding="utf-8")
if MODE=="B":
    if (OUT/"subtitles.json").exists():
        shutil.copy(OUT/"subtitles.json",latest/"subtitles.json")
    if normalized and normalized.exists():
        shutil.copy(normalized,latest/"normalized.mp4")
    print("  ✅ latest/ 에 subtitles.json + normalized.mp4 복사(편집용)")

if IG_USER_ID and IG_TOKEN and GITHUB_TOKEN:
    print("\n📤 인스타그램 게시...")
    vp=upload_to_github_release(final_reel,f"reel_{DATE}.mp4")
    tp=upload_to_github_release(thumb,f"thumb_{DATE}.png")
    if vp: post_reel_to_instagram(vp,tp,caption_full)
    else: print("  ⚠️ 공개 URL 실패")
else:
    print("\n💡 IG 미설정 → reels/latest/ 확인")

print(f"\n🎉 완료! reels/latest/")
