"""
generate_daily_reel.py — bodetail 릴스 자동화 v6
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
REEL_DURATION_A = 28
OUTRO_DURATION  = 7

DARK=(8,6,4); GOLD=(176,132,74); GOLD_BRIGHT=(200,154,92)
CREAM=(237,230,216); WHITE=(245,244,240)

SANS_BLK  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_MED  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
SANS_LT   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"
SERIF_B   = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

# 자막 = 썸네일 제목과 동일 폰트 (Black) 로 통일
KO_SUB_FONT_FILE = SANS_BLK
KO_SUB_FONT_NAME = "Noto Sans CJK KR"
KO_SUB_SIZE      = 64           # 더 크게
KO_SUB_BOLD      = 1

# 흰 박스 크기 상한 (영상 안 가리게)
BOX_MAX_W = 760
BOX_MAX_H = 300
BOX_RADIUS = 28                 # 모서리 둥글게

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

def normalize_video(src: Path) -> Path:
    """원본 → 1080x1920, 30fps, 48kHz 오디오 통일 (concat 깨짐 방지)"""
    out = OUT / "normalized.mp4"
    subprocess.run([
        "ffmpeg","-y","-i",str(src),
        "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
        "-c:v","libx264","-crf","18","-preset","fast","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart", str(out)
    ], check=True, capture_output=True, timeout=300)
    return out

# ══════════════════════════════════════════════════════════════
# 4. Inbox
# ══════════════════════════════════════════════════════════════
def process_inbox():
    video = max(inbox_videos, key=lambda f: f.stat().st_mtime)
    cf = video.parent/"credit.txt"; hf = video.parent/"headline.txt"
    credit   = cf.read_text("utf-8").strip() if cf.exists() else ""
    headline = hf.read_text("utf-8").strip() if hf.exists() else ""
    print(f"  선택 영상: {video.name}")
    if headline: print(f"  📝 수동 헤드라인: {headline}")
    return video, credit, headline

# ══════════════════════════════════════════════════════════════
# 5. 타임라인 프레임 (1초 간격)
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
# 6. Vision STEP1 — 자막 감지 (위치 정확도 ↑)
# ══════════════════════════════════════════════════════════════
def detect_subtitles_timeline(frames: list) -> dict:
    print("  🔍 자막 위치·타이밍 분석 중...")
    content=[{
        "type":"text",
        "text":"""각 이미지는 한 영상을 1초 간격으로 캡처한 540x960(세로) 프레임이야.

프레임마다 '영상에 박혀있는 자막 텍스트'의 위치를 찾아줘.
- 영어든 한국어든 화면에 표시된 글자 전부
- 핵심 자막(가장 크고 메시지를 전달하는 자막) 하나의 박스만 잡아. 워터마크(@아이디), 작은 로고는 무시.
- box는 그 자막 글자들을 딱 맞게 감싸는 최소 사각형. 너무 크게 잡지 마. (글자 없는 여백 포함 금지)
- 같은 자막이 여러 프레임 연속이면 매 프레임 같은 text로

순수 JSON만 (코드블록 금지):
{"frames":[{"i":0,"has_text":true,"text":"글자","box":{"x":40,"y":130,"w":460,"h":60}},
{"i":1,"has_text":false,"text":"","box":null}]}"""
    }]
    for fr in frames:
        content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":fr["b64"]}})
        content.append({"type":"text","text":f"[i={fr['index']} / {fr['time']}초]"})

    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=4000,
        messages=[{"role":"user","content":content}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    data=json.loads(raw)

    detected={}
    for fr in data.get("frames",[]):
        if fr.get("has_text") and fr.get("box"):
            b=fr["box"]
            detected[fr["i"]]={
                "text":fr.get("text","").strip(),
                "box":{"x":int(b["x"]*2),"y":int(b["y"]*2),
                       "w":int(b["w"]*2),"h":int(b["h"]*2)}
            }
    print(f"  ✅ 텍스트 감지: {len(detected)}프레임")
    return detected

# ══════════════════════════════════════════════════════════════
# 7. 구간 묶기 (겹침 방지 핵심)
# ══════════════════════════════════════════════════════════════
def _norm(t): return re.sub(r'[^a-z0-9가-힣]','',t.lower())
def _similar(a,b):
    na,nb=_norm(a),_norm(b)
    if not na or not nb: return False
    if na==nb: return True
    s,l=(na,nb) if len(na)<=len(nb) else (nb,na)
    return s in l and len(s)>=max(3,len(l)*0.45)

def build_segments(detected: dict, frames: list) -> list:
    seq=[(fr["index"],fr["time"]) for fr in frames]
    step=frames[1]["time"]-frames[0]["time"] if len(frames)>1 else 1.0
    segments=[]; cur=None
    for idx,t in seq:
        d=detected.get(idx)
        if d is None or not d["text"]:
            if cur: segments.append(cur); cur=None
            continue
        if cur and _similar(cur["text_en"],d["text"]):
            cur["end"]=t+step*0.5
            cb,nb=cur["en_box"],d["box"]
            x1=min(cb["x"],nb["x"]); y1=min(cb["y"],nb["y"])
            x2=max(cb["x"]+cb["w"],nb["x"]+nb["w"]); y2=max(cb["y"]+cb["h"],nb["y"]+nb["h"])
            cur["en_box"]={"x":x1,"y":y1,"w":x2-x1,"h":y2-y1}
            if len(d["text"])>len(cur["text_en"]): cur["text_en"]=d["text"]
        else:
            if cur: segments.append(cur)
            cur={"text_en":d["text"],"en_box":dict(d["box"]),
                 "start":max(0,t-step*0.5),"end":t+step*0.5}
    if cur: segments.append(cur)

    # ★ 겹침 제거: 다음 구간 시작 = 이전 구간 끝 (gap도 overlap도 없게)
    segments.sort(key=lambda s:s["start"])
    for i in range(len(segments)-1):
        if segments[i]["end"] > segments[i+1]["start"]:
            mid=(segments[i]["end"]+segments[i+1]["start"])/2
            segments[i]["end"]=mid
            segments[i+1]["start"]=mid
    # 최소 길이 보장
    for s in segments:
        if s["end"]-s["start"]<1.0:
            s["end"]=s["start"]+1.0
    print(f"  ✅ 자막 구간: {len(segments)}개")
    return segments

# ══════════════════════════════════════════════════════════════
# 8. Vision STEP2 — 번역+캡션+썸네일
# ══════════════════════════════════════════════════════════════
def translate_and_generate(segments, frames, headline_override, credit_text):
    print("  🤖 번역·캡션 생성 중...")
    en_list="\n".join([f"{i+1}. {s['text_en']}" for i,s in enumerate(segments)])
    hint=f'\n★ thumbnail_headline 은 반드시 이대로: "{headline_override}"' if headline_override else ""
    content=[{
        "type":"text",
        "text":f"""너는 bodetail 한국 남성 그루밍·라이프스타일 릴스 편집자야.

시간순 감지 자막 {len(segments)}개:
{en_list}

각 자막을 자연스러운 한국어로 번역하고 캡션·썸네일을 만들어.

★ translations: 위와 같은 개수·순서. 직역 금지. 인스타 릴스 톤. 한 줄 12자 이내(길면 \\n으로 2줄). ~다/~하라/~된다 체.
★ thumbnail_headline: 부담스러운 큰 숫자 금지. 매력·결과 중심.{hint}
★ caption_full: 후킹 질문 첫줄 / (광고 아님 · 영상 저장 추천 🔖) / 도입 1~2문장 / 번호별 핵심(①②③ 소제목—설명) / 해시태그는 hashtags에 따로.

순수 JSON만 (코드블록 금지):
{{"video_topic":"주제","thumbnail_headline":"헤드라인","thumbnail_sub":"POSTURE",
"best_frame_time":5.0,"translations":["자막1","자막2"],
"caption_full":"캡션","hashtags":"#bodetail ..."}}

best_frame_time: 인물이 잘 보이고 자막이 적은 프레임 시점(초)."""
    }]
    pick=frames[::max(1,len(frames)//5)][:5]
    for fr in pick:
        content.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":fr["b64"]}})
        content.append({"type":"text","text":f"[{fr['time']}초]"})
    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=3000,
        messages=[{"role":"user","content":content}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    result=json.loads(raw)
    trans=result.get("translations",[])
    for i,s in enumerate(segments):
        s["text_ko"]=trans[i] if i<len(trans) else s["text_en"]
    if headline_override: result["thumbnail_headline"]=headline_override
    print(f"  ✅ 생성: {result.get('video_topic','')}")
    return result

# ══════════════════════════════════════════════════════════════
# 9. 자막 레이아웃 (박스 크기 상한 + 글자 기준 박스)
# ══════════════════════════════════════════════════════════════
def layout_segment(seg):
    ko=seg["text_ko"].replace("\\n","\n")
    font=fnt(KO_SUB_FONT_FILE,KO_SUB_SIZE)
    dd=ImageDraw.Draw(Image.new("RGB",(10,10)))

    if "\n" in ko:
        lines=ko.split("\n")
    elif len(ko)>12:
        mid=len(ko)//2; sp=ko.rfind(" ",0,mid+3)
        if sp==-1: sp=mid
        lines=[ko[:sp].strip(),ko[sp:].strip()]
    else:
        lines=[ko]
    lines=[l for l in lines if l]

    line_h=int(KO_SUB_SIZE*1.22)
    text_w=max(dd.textlength(l,font=font) for l in lines)
    text_h=line_h*len(lines)

    # ★ 박스는 '글자 크기' 기준 (영어박스 크기 무시) — 작은 여백만
    pad_x,pad_y=40,24
    box_w=int(min(text_w+pad_x*2, BOX_MAX_W))
    box_h=int(min(text_h+pad_y*2, BOX_MAX_H))

    # 위치 중심 = 영어 자막 중심
    eb=seg["en_box"]
    cx=eb["x"]+eb["w"]/2
    cy=eb["y"]+eb["h"]/2

    box_x=int(cx-box_w/2); box_y=int(cy-box_h/2)
    box_x=max(12,min(box_x,RW-box_w-12))
    box_y=max(12,min(box_y,RH-box_h-12))
    cx=box_x+box_w/2; cy=box_y+box_h/2

    seg["draw_box"]={"x":box_x,"y":box_y,"w":box_w,"h":box_h}
    seg["ko_pos"]=(int(cx),int(cy))
    seg["ko_lines"]=lines
    return seg

# ══════════════════════════════════════════════════════════════
# 10. 둥근 흰 박스 PNG 오버레이 (drawbox 대신)
#     → 각 구간마다 PNG 만들어서 enable 구간에 overlay
# ══════════════════════════════════════════════════════════════
def make_subtitle_png(seg, idx) -> Path:
    b=seg["draw_box"]
    img=Image.new("RGBA",(b["w"],b["h"]),(0,0,0,0))
    draw=ImageDraw.Draw(img)
    # 둥근 흰 박스
    draw.rounded_rectangle([(0,0),(b["w"]-1,b["h"]-1)],
        radius=BOX_RADIUS, fill=(255,255,255,255))
    # 한국어 검은 글씨
    font=fnt(KO_SUB_FONT_FILE,KO_SUB_SIZE)
    line_h=int(KO_SUB_SIZE*1.22)
    total_h=line_h*len(seg["ko_lines"])
    y=(b["h"]-total_h)//2
    for line in seg["ko_lines"]:
        w=draw.textlength(line,font=font)
        draw.text(((b["w"]-w)//2,y),line,font=font,fill=(15,15,15,255))
        y+=line_h
    p=OUT/f"sub_{idx:02d}.png"
    img.save(p,"PNG")
    return p

# ══════════════════════════════════════════════════════════════
# 11. A모드 콘텐츠 / 간단 자막 (생략 없이 유지)
# ══════════════════════════════════════════════════════════════
def make_content_without_vision(source_info):
    prompt=f"""너는 bodetail 릴스 편집자야.
주제: {topic['title_main'] if MODE=='A' else '남성 라이프스타일'}
섹션: {topic['section'] if MODE=='A' else 'LIFESTYLE'}
소스: {source_info}
★자막 5~7개 각3~5초 12자이내 선언형 ★썸네일 큰숫자금지 ★캡션 후킹/(광고 아님 · 영상 저장 추천 🔖)/번호별/해시태그
순수 JSON:
{{"video_topic":"주제","thumbnail_headline":"헤드라인","thumbnail_sub":"DETAIL",
"captions":[{{"text":"자막","duration":4}}],"caption_full":"캡션","hashtags":"#bodetail ..."}}"""
    msg=client.messages.create(model="claude-sonnet-4-6",max_tokens=2048,
        messages=[{"role":"user","content":prompt}])
    raw=msg.content[0].text.strip()
    raw=re.sub(r'^```json\s*','',raw); raw=re.sub(r'\s*```$','',raw)
    return json.loads(raw)

def make_ass_simple(captions,ass_path):
    header=("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,"
        "Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Main,{KO_SUB_FONT_NAME},58,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,"
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
# 12. Pexels (A모드)
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

# ══════════════════════════════════════════════════════════════
# 13. 아웃트로 (줄바꿈 X, 골드바 간격 동일)
# ══════════════════════════════════════════════════════════════
def make_outro_image() -> Path:
    img=Image.new("RGB",(RW,RH),DARK)
    arr=np.array(img,dtype=np.int16)
    img=Image.fromarray(np.clip(arr+np.random.randint(-6,6,arr.shape,dtype=np.int16),0,255).astype(np.uint8))
    draw=ImageDraw.Draw(img); cx=RW//2; cy=RH//2

    copy="남들이 놓치는 디테일이 궁금하다면"   # 한 줄
    cf=fnt(SANS_LT,40)
    bb=draw.textbbox((0,0),copy,font=cf); cw=bb[2]-bb[0]; ch=bb[3]-bb[1]

    gap=46                      # 바 ↔ 글자 간격 (위아래 동일)
    bar_w,bar_h=64,3
    copy_y=cy-ch//2             # 카피 세로 중앙
    # 상단 바
    top_bar_y=copy_y-gap-bar_h
    draw.rectangle([(cx-bar_w//2,top_bar_y),(cx+bar_w//2,top_bar_y+bar_h)],fill=GOLD)
    # 카피
    draw.text((cx-cw//2,copy_y),copy,font=cf,fill=(*CREAM,235))
    # 하단 바
    bot_bar_y=copy_y+ch+gap
    draw.rectangle([(cx-bar_w//2,bot_bar_y),(cx+bar_w//2,bot_bar_y+bar_h)],fill=GOLD)

    # CTA
    ctaf=fnt(SANS_MED,32); cta="@bodetail_official 팔로우"
    bb=draw.textbbox((0,0),cta,font=ctaf); w=bb[2]-bb[0]
    draw.text((cx-w//2,bot_bar_y+44),cta,font=ctaf,fill=(*GOLD_BRIGHT,255))

    # 워드마크
    wf=fnt(SERIF_B,108); wt="bodetail"
    bb=draw.textbbox((0,0),wt,font=wf); w=bb[2]-bb[0]
    draw.text((cx-w//2,bot_bar_y+110),wt,font=wf,fill=(*CREAM,225))

    p=OUT/"outro.png"; img.save(p,"PNG"); return p

def make_wordmark_overlay() -> Path:
    ov=Image.new("RGBA",(RW,80),(0,0,0,0));draw=ImageDraw.Draw(ov)
    sf=fnt(SANS_MED,34);t="bodetail"
    bb=draw.textbbox((0,0),t,font=sf);w=bb[2]-bb[0]
    draw.text(((RW-w)//2,22),t,font=sf,fill=(*CREAM,160))
    p=OUT/"wordmark.png";ov.save(p,"PNG");return p

# ══════════════════════════════════════════════════════════════
# 14. 썸네일 — 자막 없는 프레임 우선
# ══════════════════════════════════════════════════════════════
def extract_full_frame(video_path,t) -> Path:
    p=OUT/"thumb_src.jpg"
    subprocess.run(["ffmpeg","-y","-ss",f"{t:.2f}","-i",str(video_path),
        "-frames:v","1","-vf","scale=1080:1920",str(p)],check=True,capture_output=True,timeout=30)
    return p if p.exists() else None

def pick_clean_frame_time(segments, frames, fallback_t):
    """자막 구간에 안 걸치는 프레임 시점 찾기"""
    busy=[(s["start"],s["end"]) for s in segments]
    # 인물 잘 보이는 중후반 우선
    candidates=sorted(frames,key=lambda f:abs(f["time"]-fallback_t))
    for fr in candidates:
        t=fr["time"]
        if not any(a<=t<=b for a,b in busy):
            return t, True
    return fallback_t, False

def mask_boxes(frame_path,boxes) -> Path:
    img=Image.open(frame_path).convert("RGB");draw=ImageDraw.Draw(img)
    for b in boxes:
        x1=max(0,b["x"]-10);y1=max(0,b["y"]-10)
        x2=min(RW,b["x"]+b["w"]+10);y2=min(RH,b["y"]+b["h"]+10)
        draw.rectangle([(x1,y1),(x2,y2)],fill=DARK)
    p=OUT/"thumb_masked.jpg";img.save(p,"JPEG",quality=92);return p

def make_thumbnail(headline,sub_label,source_frame=None) -> Path:
    W_T,H_T=1080,1440
    Xg,Yg=np.meshgrid(np.arange(W_T),np.arange(H_T))
    if source_frame and Path(source_frame).exists():
        base=np.array(Image.open(source_frame).convert("RGB").resize((W_T,H_T),Image.LANCZOS),dtype=np.float32)
        gray=0.299*base[:,:,0]+0.587*base[:,:,1]+0.114*base[:,:,2]
        base=gray[:,:,None]*0.55+base*0.45;base*=0.82
    else:
        base=np.zeros((H_T,W_T,3),dtype=np.float32);base[:]=list(DARK)
        d=np.sqrt(((Xg-W_T*0.5)/350.)**2+((Yg-H_T*0.55)/400.)**2)
        g=np.clip(1-d,0,1)*0.32
        base[:,:,0]+=g*75;base[:,:,1]+=g*62;base[:,:,2]+=g*45
    ink=np.array(DARK,dtype=np.float32)[None,None,:]
    base=base*0.55+ink*0.45
    yv=np.linspace(0,1,H_T)[:,None]
    fade=np.clip((yv-0.38)/0.62,0,1)**1.4*0.78
    m=np.repeat(fade[:,:,None],W_T,axis=1);base=base*(1-m)+ink*m
    cx,cy=W_T/2,H_T/2
    dist=np.sqrt(((Xg-cx)/cx)**2+((Yg-cy)/cy)**2)
    vig=np.clip((dist-0.5)/0.7,0,1)**1.5*0.55
    base=base*(1-vig[:,:,None])
    img=Image.fromarray(np.clip(base,0,255).astype(np.uint8));draw=ImageDraw.Draw(img)

    lf=fnt(SANS_MED,28)
    draw.text((84,88),"오늘의 디테일",font=lf,fill=GOLD)
    lw=draw.textlength("오늘의 디테일",font=lf)
    draw.line([(84+lw+20,106),(W_T-84,106)],fill=(*GOLD,160),width=2)

    bf=fnt(SANS_MED,24);bb=draw.textbbox((0,0),sub_label,font=bf)
    bw,bh=bb[2]-bb[0],bb[3]-bb[1];bx,by=84,148
    draw.rectangle([(bx,by),(bx+bw+32,by+bh+20)],outline=(*CREAM,100),width=2)
    draw.text((bx+16-bb[0],by+10-bb[1]),sub_label,font=bf,fill=(*CREAM,145))

    max_w=W_T-84*2;fsize=92
    while fsize>56:
        mf=fnt(SANS_BLK,fsize);words=headline.split();lines=[];cur=""
        for w in words:
            tr=w if cur=="" else cur+" "+w
            if draw.textlength(tr,font=mf)<=max_w: cur=tr
            else: lines.append(cur);cur=w
        if cur: lines.append(cur)
        lh=int(fsize*1.18)
        if len(lines)*lh<=380: break
        fsize-=6
    y=H_T-88-len(lines)*lh-8
    for line in lines:
        draw.text((84,y),line,font=mf,fill=WHITE);y+=lh

    sf=fnt(SANS_MED,26);t="bodetail";sw=draw.textlength(t,font=sf)
    draw.text(((W_T-sw)//2,H_T-58),t,font=sf,fill=(*CREAM,190))
    p=OUT/"thumbnail_1080x1440.png";img.save(p,"PNG");return p

# ══════════════════════════════════════════════════════════════
# 15. FFmpeg 합성 (B) — 둥근 PNG overlay + concat 안정화
# ══════════════════════════════════════════════════════════════
def build_reel_B(normalized, segments, sub_pngs, ass_path_unused,
                 outro_img, wordmark_img) -> Path:
    processed=OUT/"processed.mp4";outro_vid=OUT/"outro.mp4";final=OUT/"reel_final.mp4"

    inputs=["-i",str(normalized),"-i",str(wordmark_img)]
    for png in sub_pngs:
        inputs+=["-i",str(png)]

    # 필터: 워드마크 먼저, 그다음 자막 PNG들 각자 enable 구간에 overlay
    fc=[]
    cur="[0:v]"
    fc.append(f"{cur}[1:v]overlay=(W-w)/2:H-100:format=auto[v1]")
    last="v1"
    for k,seg in enumerate(segments):
        inp=k+2   # 0=video,1=wordmark,2~=subs
        b=seg["draw_box"]
        nxt=f"v{k+2}"
        fc.append(
            f"[{last}][{inp}:v]overlay={b['x']}:{b['y']}:"
            f"enable='between(t,{seg['start']:.2f},{seg['end']:.2f})'[{nxt}]"
        )
        last=nxt
    filter_complex=";".join(fc)

    subprocess.run([
        "ffmpeg","-y",*inputs,
        "-filter_complex",filter_complex,
        "-map",f"[{last}]","-map","0:a?",
        "-c:v","libx264","-crf","20","-preset","fast","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(processed)
    ],check=True,capture_output=True,timeout=500)
    print("  ✅ 메인 처리 완료")

    # 아웃트로 (메인과 동일 30fps/48kHz 무음)
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",str(outro_img),
        "-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t",str(OUTRO_DURATION),"-c:v","libx264","-pix_fmt","yuv420p","-r","30",
        "-vf","scale=1080:1920","-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-shortest","-movflags","+faststart",str(outro_vid)
    ],check=True,capture_output=True,timeout=60)
    print("  ✅ 아웃트로 완료")

    # ★ concat을 filter 방식으로 (멈춤/버벅임 방지)
    subprocess.run([
        "ffmpeg","-y","-i",str(processed),"-i",str(outro_vid),
        "-filter_complex",
        "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map","[v]","-map","[a]",
        "-c:v","libx264","-crf","20","-preset","fast","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
        "-movflags","+faststart",str(final)
    ],check=True,capture_output=True,timeout=240)
    print("  ✅ 최종 합성 완료")
    return final

def build_reel_A(source_video,ass_path,outro_img,wordmark_img) -> Path:
    processed=OUT/"processed.mp4";outro_vid=OUT/"outro.mp4";final=OUT/"reel_final.mp4"
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
# 16. Instagram
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
# 17. 메인
# ══════════════════════════════════════════════════════════════
print("\n"+"="*60)
print(f"🎬 bodetail 릴스 자동화 v6 | {DATE} | 모드 {MODE}")
print("="*60)

used_ids=load_used_reels();content={};caption_full="";thumb=None;final_reel=None;credit_text=""

if MODE=="B":
    src,credit_text,headline_override=process_inbox()
    print("\n🎞️ 정규화(1080x1920/30fps/48kHz)...")
    normalized=normalize_video(src)
    dur=get_video_duration(normalized)
    print(f"  ✅ 길이 {dur:.1f}초")

    print("\n🔍 타임라인 프레임...")
    frames=extract_timeline_frames(normalized)
    print(f"  ✅ {len(frames)}프레임")

    detected=detect_subtitles_timeline(frames)
    segments=build_segments(detected,frames)
    content=translate_and_generate(segments,frames,headline_override,credit_text)

    for s in segments: layout_segment(s)
    sub_pngs=[make_subtitle_png(s,i) for i,s in enumerate(segments)]

    caption_full=(f"{content['caption_full']}\n\n{content['hashtags']}"
        f"{f'\n\n📹 | {credit_text}' if credit_text else ''}\n\n"
        f"Start Every Detail with Awareness Now\n—\n"
        f"내 외모의 최고 버전이 궁금하다면? @bodetail_official")
    (OUT/"caption.txt").write_text(caption_full,encoding="utf-8")
    print(f"  ✅ 자막 {len(segments)}개 / 캡션")

    print("\n🎨 이미지 에셋...")
    outro_img=make_outro_image();wordmark_img=make_wordmark_overlay()

    # 썸네일: 자막 없는 프레임 우선
    fb_t=float(content.get("best_frame_time",dur*0.45))
    fb_t=max(0.5,min(fb_t,dur-0.5))
    clean_t,is_clean=pick_clean_frame_time(segments,frames,fb_t)
    bf=extract_full_frame(normalized,clean_t)
    if is_clean:
        masked=bf
        print(f"  ✅ 깨끗한 프레임 {clean_t:.1f}초 사용")
    else:
        cover=[s["en_box"] for s in segments if s["start"]<=clean_t<=s["end"]]
        masked=mask_boxes(bf,cover) if cover else bf
        print(f"  ⚠️ 자막 없는 프레임 없음 → {clean_t:.1f}초 마스킹")
    thumb=make_thumbnail(content["thumbnail_headline"],content.get("thumbnail_sub","DETAIL"),masked)

    print("\n🎬 FFmpeg 합성...")
    final_reel=build_reel_B(normalized,segments,sub_pngs,None,outro_img,wordmark_img)

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
        "-vf","scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440",str(fp)],
        capture_output=True,timeout=30)
    thumb=make_thumbnail(content["thumbnail_headline"],content.get("thumbnail_sub","DETAIL"),
        fp if fp.exists() else None)
    final_reel=build_reel_A(raw_video,ass_path,outro_img,wordmark_img)

size_mb=final_reel.stat().st_size//1024//1024
print(f"  ✅ 완성: {final_reel.name} ({size_mb}MB)")
save_used_reels(used_ids)

latest=Path("reels/latest");latest.mkdir(exist_ok=True)
shutil.copy(final_reel,latest/"reel_final.mp4")
shutil.copy(thumb,latest/"thumbnail_1080x1440.png")
(latest/"caption.txt").write_text(caption_full,encoding="utf-8")

if IG_USER_ID and IG_TOKEN and GITHUB_TOKEN:
    print("\n📤 인스타그램 게시...")
    vp=upload_to_github_release(final_reel,f"reel_{DATE}.mp4")
    tp=upload_to_github_release(thumb,f"thumb_{DATE}.png")
    if vp: post_reel_to_instagram(vp,tp,caption_full)
    else: print("  ⚠️ 공개 URL 실패")
else:
    print("\n💡 IG 미설정 → reels/latest/ 확인")

print(f"\n🎉 완료! reels/latest/")
