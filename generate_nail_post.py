# -*- coding: utf-8 -*-
"""
리버니 네일룸(@libunny.nailroom) 데일리 게시물 생성기 v2
─ 레퍼런스(DRAW NAIL 감성) 기반 전면 재설계 ─

무드: 얇은 라인 아트(아치 프레임·점선 박스·손그림 하트/리본/안개꽃),
      자간 넓은 세리프 영문, 여백 많은 중앙 정렬, 웜 브라운 단색 + 파스텔.
컨셉: 마스코트 토끼 '리버니'가 오늘의 네일 소식을 알려주는 형식.

기능:
 · 30일 주제 스케줄(topics_nail.json) — 소진되면 Claude가 다음 30일치 자동 생성
 · 슬라이드 타입 3종: info(사진+정보) / tier(티어리스트) / product(제품 소개+참고가)
 · 슬라이드별 어울리는 밝은 네일 사진 자동 검색(Pexels/Unsplash) + 파스텔 보정
 · 마지막 장: 강한 CTA + 리버니 브랜드 카드로 마무리
 · RERENDER=true → Claude 호출 없이 posts_nail/latest/content.json으로 재렌더
   (HTML 에디터로 content.json 수정 후 재실행하는 워크플로)
 · 완성본 이메일 발송(08:30 KST cron)
"""
import os, sys, json, shutil, smtplib, datetime, random, re, math, time
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps

W, H = 1080, 1440
OUT = Path("posts_nail/latest")
ARCH = Path("posts_nail")/datetime.datetime.now().strftime("%Y-%m-%d")
TOPICS_FILE = Path("topics_nail.json")
ANCHOR = datetime.date(2026,7,1)   # 주제 배치 기준일 (30일마다 새 배치)

# ── 팔레트 (DRAW NAIL 계열: 크림 + 웜브라운 단색 + 파스텔 포인트) ──
CREAM  = (248, 244, 238)
PINKBG = (247, 236, 233)
SAGEBG = (238, 241, 233)
LINE   = (176, 156, 130)    # 라인 아트 브라운
BROWN  = (94, 79, 65)       # 진한 텍스트
SOFT   = (150, 132, 112)    # 보조 텍스트
ROSE   = (191, 141, 141)
GOLD   = (196, 168, 130)
BUNNY  = (199, 189, 181)
EAR    = (236, 213, 210)
WHITE  = (255, 255, 255)

ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY","").strip()
TOPIC_OVERRIDE = os.environ.get("TOPIC_OVERRIDE","").strip()
RERENDER   = os.environ.get("RERENDER","").strip().lower() in ("1","true","yes")
SKIP_EMAIL = os.environ.get("SKIP_EMAIL","").strip().lower() in ("1","true","yes")
GMAIL_ADDR = os.environ.get("GMAIL_ADDRESS","").strip()
GMAIL_PW   = os.environ.get("GMAIL_APP_PASSWORD","").strip()
MAIL_TO    = os.environ.get("MAIL_TO","").strip() or GMAIL_ADDR
PEXELS_KEY   = os.environ.get("PEXELS_API_KEY","").strip()
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY","").strip()

def run_ok(fn,*a,**k):
    try: return fn(*a,**k)
    except Exception as e:
        print(f"  ⚠️ {fn.__name__} 실패: {e}"); return None

# ══════════════════════════════════════════════
# 폰트 (세련된 조합: 세리프 한글 + Playfair 영문 + 나눔펜 손글씨)
# ══════════════════════════════════════════════
FONT_DIRS=[str(Path.home()/".fonts"),"/usr/share/fonts/opentype/noto","/usr/share/fonts/truetype/nanum"]
def _find(names):
    for d in FONT_DIRS:
        for n in names:
            p=Path(d)/n
            if p.exists(): return str(p)
    return None
F_SERIF_B=_find(["NotoSerifCJK-Bold.ttc","NotoSerifCJKkr-Bold.otf"]) or _find(["NotoSansCJK-Bold.ttc"])
F_SERIF_R=_find(["NotoSerifCJK-Regular.ttc","NotoSerifCJKkr-Regular.otf"]) or _find(["NotoSansCJK-Regular.ttc"])
F_PLAY   =_find(["PlayfairDisplay-Regular.ttf","PlayfairDisplay-Italic.ttf"])
F_PEN    =_find(["NanumPenScript-Regular.ttf","NanumPen.ttf"])

def F(kind,size):
    path={"kb":F_SERIF_B,"kr":F_SERIF_R,"en":F_PLAY or F_SERIF_R,"pen":F_PEN or F_SERIF_R}[kind]
    try: return ImageFont.truetype(path,size)
    except: return ImageFont.load_default()

EMOJI_RE=re.compile("["+"\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D"+"]+")
def clean(t): return EMOJI_RE.sub("",str(t)).strip()

# ══════════════════════════════════════════════
# 주제별 필수 피사체 규칙 (bodetail의 generate_daily_post.py SUBJECT_RULES를
# 네일 도메인에 맞게 이식) — Claude가 만든 img_query가 부정확하거나 너무 일반적일 때
# (예: "product flatlay"만 검색하면 책상 모서리·머그컵 같은 무관한 사진이 나옴)
# 헤딩/본문에 등장하는 한국어 키워드를 감지해 훨씬 구체적인 영어 검색어로 강제 교체.
# 리스트 위쪽일수록 우선순위 높음 — 먼저 매치되는 규칙을 사용.
# ══════════════════════════════════════════════
NAIL_SUBJECT_RULES = [
    ({"큐티클오일","큐티클 오일","cuticle oil"},
     ["cuticle oil bottle nail care closeup","cuticle oil pen nail treatment","hands cuticle care oil closeup"]),
    ({"큐티클","cuticle"},
     ["cuticle care hands closeup pastel","nail cuticle pusher tool","manicure cuticle care closeup"]),
    ({"네일파일","줄","파일","file","buffer","광내기"},
     ["nail file tool manicure","glass nail file closeup pastel","nail buffer manicure tool"]),
    ({"핸드크림","hand cream","로션","moisturizer","보습"},
     ["hand cream tube pastel","woman applying hand cream","hand lotion bottle skincare"]),
    ({"탑코트","topcoat","top coat","광택","코팅"},
     ["clear top coat nail polish bottle","nail polish top coat closeup","glossy nail polish bottle"]),
    ({"글루","네일글루","glue","접착"},
     ["nail glue bottle small","nail repair glue closeup"]),
    ({"영양제","비오틴","콜라겐","케라틴","biotin","collagen","keratin","vitamin"},
     ["vitamin supplement bottle pastel","biotin capsules bottle closeup","collagen powder jar pastel"]),
    ({"큐티클니퍼","니퍼","가위","cutter","nipper"},
     ["nail cuticle nipper tool","manicure scissor tool closeup"]),
    ({"젤네일","gel nail","젤","gel polish"},
     ["gel nail polish bottle pastel","glossy gel manicure hands"]),
    ({"패디","페디","pedicure","발톱","foot"},
     ["pedicure feet care pastel","foot cream closeup pastel"]),
    ({"네일아트","디자인","design","포인트"},
     ["pastel manicure nail art closeup","soft pink gel nails hands"]),
    ({"손톱","nail","nails","매니큐어","manicure"},
     ["soft pastel manicure hands closeup","pastel gel nails hand closeup"]),
]

def subject_override(text: str):
    """텍스트 안 키워드를 규칙과 매칭해 강제 검색어 반환. 매치 없으면 None(=Claude img_query 그대로 사용)."""
    low = text.lower()
    for keywords, queries in NAIL_SUBJECT_RULES:
        if any(k.lower() in low for k in keywords):
            return queries
    return None


def tw(d,t,f):
    b=d.textbbox((0,0),t,font=f); return b[2]-b[0], b[3]-b[1]

def wrap_kr(d,text,f,max_w):
    lines=[]
    for raw in str(text).split("\n"):
        cur=""
        for ch in raw:
            if tw(d,cur+ch,f)[0]>max_w and cur and ch not in ".,!?~…)”'":
                lines.append(cur); cur=ch
            else: cur+=ch
        lines.append(cur)
    # 2자 이하 고아 줄("요." 등)은 앞 줄에 흡수
    merged=[]
    for l in lines:
        if merged and 0<len(l.strip())<=2:
            merged[-1]+=l
        else:
            merged.append(l)
    return merged

def tracked(d,x,y,text,f,fill,track=14,center_w=None):
    """자간 넓은 영문 (DRAW NAIL 로고 감성). center_w 주면 그 폭 기준 중앙정렬."""
    total=sum(tw(d,ch,f)[0]+track for ch in text)-track
    cx = x if center_w is None else x+(center_w-total)/2
    for ch in text:
        d.text((cx,y),ch,font=f,fill=fill)
        cx+=tw(d,ch,f)[0]+track
    return total

# ══════════════════════════════════════════════
# 라인 아트 요소 (레퍼런스 손그림 감성)
# ══════════════════════════════════════════════
def dashed_line(d,x1,y1,x2,y2,dash=14,gap=10,fill=LINE,width=2):
    L=math.hypot(x2-x1,y2-y1)
    if L==0: return
    ux,uy=(x2-x1)/L,(y2-y1)/L; t=0
    while t<L:
        e=min(t+dash,L)
        d.line([x1+ux*t,y1+uy*t,x1+ux*e,y1+uy*e],fill=fill,width=width)
        t=e+gap

def dashed_round_box(d,box,r=56,fill=LINE,width=2,dash=14,gap=10):
    """점선 라운드 사각형 (레퍼런스 이미지2의 그 박스)."""
    x1,y1,x2,y2=box
    dashed_line(d,x1+r,y1,x2-r,y1,dash,gap,fill,width)
    dashed_line(d,x1+r,y2,x2-r,y2,dash,gap,fill,width)
    dashed_line(d,x1,y1+r,x1,y2-r,dash,gap,fill,width)
    dashed_line(d,x2,y1+r,x2,y2-r,dash,gap,fill,width)
    for (cx,cy,a0,a1) in [(x1+r,y1+r,180,270),(x2-r,y1+r,270,360),(x2-r,y2-r,0,90),(x1+r,y2-r,90,180)]:
        steps=7
        for i in range(steps):
            if i%2==0:
                d.arc([cx-r,cy-r,cx+r,cy+r],a0+(a1-a0)*i/steps,a0+(a1-a0)*(i+0.7)/steps,fill=fill,width=width)

def divider_dot(d,cx,y,half=120,fill=LINE):
    d.line([cx-half,y,cx-14,y],fill=fill,width=2)
    d.ellipse([cx-5,y-5,cx+5,y+5],fill=fill)
    d.line([cx+14,y,cx+half,y],fill=fill,width=2)

def heart_line(d,cx,cy,s,fill=LINE,width=3):
    """손그림 하트(라인)."""
    pts=[]
    for i in range(0,201):
        t=math.pi*i/100
        x=16*math.sin(t)**3
        y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
        pts.append((cx+x*s/16,cy-y*s/16))
    d.line(pts,fill=fill,width=width,joint="curve")

def ribbon_bow(d,cx,cy,s=1.0,fill=LINE,width=3):
    """리본 매듭(라인) — 레퍼런스 이미지2 상단 그 리본."""
    r=int(34*s)
    d.ellipse([cx-2*r,cy-r,cx-2,cy+r],outline=fill,width=width)
    d.ellipse([cx+2,cy-r,cx+2*r,cy+r],outline=fill,width=width)
    d.line([cx-2,cy,cx-r*1.1,cy+r*1.7],fill=fill,width=width)
    d.line([cx+2,cy,cx+r*1.1,cy+r*1.7],fill=fill,width=width)
    d.ellipse([cx-7,cy-7,cx+7,cy+7],fill=CREAM,outline=fill,width=width)

def babys_breath(d,x0,y0,s=1.0,fill=(196,182,160)):
    """안개꽃 가지 라인아트 (레퍼런스 이미지1 좌하단)."""
    random.seed(7)
    for stem in range(3):
        pts=[(x0+stem*26*s, y0)]
        for i in range(1,9):
            pts.append((x0+stem*26*s+math.sin(i*0.9+stem)*22*s, y0-i*38*s))
        d.line(pts,fill=fill,width=2,joint="curve")
        for (px,py) in pts[2:]:
            for _ in range(2):
                fx=px+random.randint(-16,16); fy=py+random.randint(-12,12)
                d.ellipse([fx-4,fy-4,fx+4,fy+4],outline=fill,width=2)

def sparkle(d,x,y,s,fill=GOLD):
    d.line([x-s,y,x+s,y],fill=fill,width=2); d.line([x,y-s,x,y+s],fill=fill,width=2)
    d.line([x-s*0.5,y-s*0.5,x+s*0.5,y+s*0.5],fill=fill,width=1)
    d.line([x-s*0.5,y+s*0.5,x+s*0.5,y-s*0.5],fill=fill,width=1)

FACE_WHITE = (253, 251, 247)   # 흰색 얼굴/몸
EAR_PINK   = (240, 200, 199)   # 귀(바깥) — 분홍
EAR_INNER  = (222, 163, 161)   # 귀 안쪽 — 진한 분홍
NOSE_PINK  = (224, 140, 138)   # 코 — 분홍
OUTLINE    = (176, 156, 130)   # 라인아트 브라운(LINE과 동일 톤) — 흰 얼굴이 배경에 묻히지 않도록 얇은 윤곽선

def _bunny_raw(dd, cx, cy, r):
    """리버니 원본 드로잉 (4배 해상도 캔버스에 그려질 좌표 기준).
    흰색 얼굴 + 분홍 귀·코 + 검은 눈동자. 흰 얼굴이 크림/핑크 배경에 묻히지 않도록
    얇은 라인아트 톤 윤곽선을 둘러 시인성을 확보(브랜드의 손그림 라인아트와도 통일감)."""
    ow = max(2, int(r*0.045))  # 윤곽선 두께(슈퍼샘플 좌표 기준)
    # 귀 (바깥 분홍 + 안쪽 진분홍 + 윤곽선)
    for sx in (-1, 1):
        ex = cx + sx*r*0.56
        dd.ellipse([ex-r*0.30, cy-r*2.18, ex+r*0.30, cy-r*0.30], fill=EAR_PINK, outline=OUTLINE, width=ow)
        dd.ellipse([ex-r*0.16, cy-r*1.92, ex+r*0.16, cy-r*0.52], fill=EAR_INNER)
    # 머리 (흰색 + 윤곽선)
    dd.ellipse([cx-r, cy-r*0.98, cx+r, cy+r*1.02], fill=FACE_WHITE, outline=OUTLINE, width=ow)
    # 볼터치
    for sx in (-1, 1):
        bx, by = cx+sx*r*0.60, cy+r*0.30
        dd.ellipse([bx-r*0.17, by-r*0.11, bx+r*0.17, by+r*0.11], fill=(245, 210, 206))
    # 눈 (동그랗고 큼직 + 캐치라이트로 생기, 검은색)
    er = r*0.125
    for sx in (-1, 1):
        ex, ey = cx+sx*r*0.35, cy-r*0.02
        dd.ellipse([ex-er, ey-er*1.2, ex+er, ey+er*1.2], fill=(30, 28, 26))
        dd.ellipse([ex-er*0.15, ey-er*1.0, ex+er*0.55, ey-er*0.35], fill=(255, 255, 255))
    # 코 (작은 하트, 분홍)
    nr = r*0.075; ny = cy+r*0.24
    dd.ellipse([cx-nr*1.5, ny-nr*0.5, cx, ny+nr*0.6], fill=NOSE_PINK)
    dd.ellipse([cx, ny-nr*0.5, cx+nr*1.5, ny+nr*0.6], fill=NOSE_PINK)
    dd.polygon([(cx-nr*1.4, ny+nr*0.15), (cx+nr*1.4, ny+nr*0.15), (cx, ny+nr*1.7)], fill=NOSE_PINK)
    # 입 (부드러운 w자 곡선)
    mw = r*0.15
    dd.arc([cx-mw, ny+nr, cx, ny+nr+mw*0.85], 15, 165, fill=(190, 168, 156), width=max(2, int(r*0.028)))
    dd.arc([cx, ny+nr, cx+mw, ny+nr+mw*0.85], 15, 165, fill=(190, 168, 156), width=max(2, int(r*0.028)))

_MASCOT_CACHE={}
MASCOT_PATH=Path("assets_brand/mascot_libunny.png")  # repo에 올려둘 마스코트 이미지

def bunny(img, cx, cy, s=1.0):
    """리버니 마스코트 — repo에 올려둔 실제 캐릭터 이미지(assets_brand/mascot_libunny.png)를
    불러와 배치. 파일이 없으면 조용히 생략(로그만). s=1.0 기준 지름 약 120px."""
    if not MASCOT_PATH.exists():
        if "warned" not in _MASCOT_CACHE:
            print(f"  ⚠️ 마스코트 이미지 없음({MASCOT_PATH}) — 토끼 생략. repo에 파일을 올려주세요.")
            _MASCOT_CACHE["warned"]=True
        return
    diam=max(40,int(150*s))
    key=diam
    if key not in _MASCOT_CACHE:
        try:
            m=Image.open(MASCOT_PATH).convert("RGBA")
            m=m.resize((diam,diam),Image.LANCZOS)
            _MASCOT_CACHE[key]=m
        except Exception as e:
            print(f"  ⚠️ 마스코트 로드 실패: {e}"); return
    m=_MASCOT_CACHE[key]
    img.paste(m,(int(cx-diam/2),int(cy-diam/2)),m)

def speech_bubble(d,cx,y,text,f,pad=26):
    """리버니 말풍선 — '오늘도 리버니가 알려줄게요' 컨셉."""
    t=clean(text); w,h=tw(d,t,f)
    x1,y1,x2,y2=cx-w/2-pad,y,cx+w/2+pad,y+h+pad*1.4
    d.rounded_rectangle([x1,y1,x2,y2],radius=int((y2-y1)/2),fill=WHITE,outline=LINE,width=2)
    d.polygon([(cx-10,y1+2),(cx+10,y1+2),(cx,y1-14)],fill=WHITE)
    d.line([(cx-10,y1),(cx,y1-14)],fill=LINE,width=2); d.line([(cx+10,y1),(cx,y1-14)],fill=LINE,width=2)
    d.text((cx-w/2,y+pad*0.62),t,font=f,fill=BROWN)
    return y2

# ══════════════════════════════════════════════
# 사진: 밝고 화사한 후보 선택 + 파스텔 보정 + 라운드 패널
# ══════════════════════════════════════════════
def _brightness(p):
    try:
        import numpy as np
        a=__import__("numpy").array(Image.open(p).convert("L").resize((64,64)),dtype=float)
        return float(a.mean())
    except Exception: return 150.0

def _search_once(q):
    """한 검색어로 Unsplash+Pexels 후보 URL 수집. 실패 이유를 반드시 로그로 남김
    (예전엔 except: pass로 조용히 삼켜져서 '사진이 하나도 안 붙는' 원인을 알 수 없었음).
    orientation=portrait, content_filter 등은 bodetail의 검증된 사진 파이프라인
    (generate_daily_post.py)에서 가져온 설정 — 실전에서 사진이 잘 붙는 것으로 확인된 조합.
    per_page는 카테고리 A/B 릴스와 같은 API 키를 공유하는 걸 감안해 절제된 수치로 유지."""
    cand=[]
    if UNSPLASH_KEY:
        try:
            r=requests.get("https://api.unsplash.com/search/photos",
                headers={"Authorization":f"Client-ID {UNSPLASH_KEY}"},
                params={"query":q,"per_page":8,"orientation":"portrait","content_filter":"high"},timeout=12)
            if r.status_code==200:
                res=r.json().get("results",[])
                cand+=[x["urls"]["regular"] for x in res[:8] if x.get("urls",{}).get("regular")]
                print(f"    · Unsplash '{q}' → {len(res)}건")
            elif r.status_code in (403,429):
                print(f"    ⚠️ Unsplash 요청 한도 초과({r.status_code}) — 릴스(카테고리 A/B)와 키를 공유 중이면 "
                      f"시간당 한도가 이미 소진됐을 수 있음")
            else:
                print(f"    ⚠️ Unsplash 응답 {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"    ⚠️ Unsplash 요청 실패: {e}")
    if PEXELS_KEY:
        try:
            r=requests.get("https://api.pexels.com/v1/search",
                headers={"Authorization":PEXELS_KEY},
                params={"query":q,"per_page":10,"orientation":"portrait","size":"large"},timeout=12)
            if r.status_code==200:
                res=r.json().get("photos",[])
                cand+=[x["src"]["large2x"] for x in res[:10] if x.get("src",{}).get("large2x")]
                print(f"    · Pexels '{q}' → {len(res)}건")
            elif r.status_code in (403,429):
                print(f"    ⚠️ Pexels 요청 한도 초과({r.status_code}) — 릴스(카테고리 A/B)와 키를 공유 중이면 "
                      f"시간당 한도가 이미 소진됐을 수 있음")
            else:
                print(f"    ⚠️ Pexels 응답 {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"    ⚠️ Pexels 요청 실패: {e}")
    return cand

def fetch_photo(queries, save):
    """queries: 검색어 리스트(우선순위 순). 앞에서부터 시도해 결과 있는 첫 검색어를 사용
    (bodetail의 image_queries 순차 시도 패턴과 동일) — subject_override로 강제된 구체적
    검색어를 최우선으로 넣고, 그 다음 Claude의 img_query, 마지막에 범용 폴백 순으로 전달됨."""
    if not UNSPLASH_KEY and not PEXELS_KEY:
        print("  ⚠️ PEXELS_API_KEY / UNSPLASH_ACCESS_KEY 둘 다 없음 — 사진 생략")
        return False
    if isinstance(queries,str): queries=[queries]
    queries=[clean(q) for q in queries if clean(q)] or ["pastel manicure nails"]
    cand=[]; used_q=None
    for q in queries:
        cand=_search_once(q)
        if cand: used_q=q; break
    if not cand:
        print("  ⚠️ 모든 검색어에서 후보 0건 — 사진 없이 진행(레이트리밋이면 위 경고 참고)")
        return False
    import io
    best_im=None; best_score=-1
    for j,u in enumerate(cand[:8]):   # 다운로드 수를 줄여 API 다운로드 부담/시간 절약
        try:
            resp=requests.get(u,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
            if resp.status_code!=200 or len(resp.content)<3000:
                continue
            try:
                im=Image.open(io.BytesIO(resp.content)).convert("RGB")
            except Exception:
                continue
            import numpy as np
            b=float(np.array(im.resize((48,48)).convert("L")).mean())
            score=-abs(b-185)
            if score>best_score: best_score=score; best_im=im
        except Exception as e:
            print(f"    ⚠️ 다운로드 실패({j}): {e}")
    if best_im is None:
        print("  ⚠️ 후보는 있었으나 전부 다운로드/검증 실패 — 사진 없이 진행")
        return False
    try:
        im=ImageEnhance.Brightness(best_im).enhance(1.05)
        im=ImageEnhance.Color(im).enhance(0.88)
        overlay=Image.new("RGB",im.size,(255,244,238))
        im=Image.blend(im,overlay,0.07)
        im.save(save,quality=92)
    except Exception as e:
        print(f"  ⚠️ 보정 생략: {e}"); best_im.save(save,quality=92)
    print(f"  🖼️ 사진 확보 완료 (검색어: '{used_q}')")
    return True

def paste_photo_panel(img, d, photo_path, box, r=36):
    x1,y1,x2,y2=box; bw,bh=int(x2-x1),int(y2-y1)
    ph=ImageOps.fit(Image.open(photo_path).convert("RGB"),(bw,bh))
    mask=Image.new("L",(bw,bh),0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,bw,bh],radius=r,fill=255)
    img.paste(ph,(int(x1),int(y1)),mask)
    d.rounded_rectangle(box,radius=r,outline=LINE,width=2)

# ══════════════════════════════════════════════
# 30일 주제: 자동 순환 + 소진 시 Claude가 다음 배치 생성
# ══════════════════════════════════════════════
FALLBACK_TOPICS=[
 "모르면 손해보는 손톱 영양제 티어리스트 — S부터 B까지 솔직 정리|tier",
 "이번 달 띠별 행운 네일 컬러 — 좋은 기운을 부르는 조합|info",
 "아는 사람만 아는 젤네일 2주 더 오래가는 습관|info",
 "네일 아티스트가 진짜 쓰는 큐티클 오일 소개 — 참고가 포함|product",
 "손톱 세로줄·갈라짐 원인과 집에서 하는 해결 루틴|info",
 "퍼스널컬러 여름쿨이 하면 손이 하얘 보이는 컬러 5|info",
 "물어뜯은 손톱 교정 전후 — 어떻게 달라질까|info",
 "여름 물놀이에도 안 지워지는 컬러·디자인 추천|info",
 "핸드크림 티어리스트 — 흡수력·향·가성비로 나눈 솔직 등급|tier",
 "직장인 오피스 네일 — 단정한데 밋밋하지 않게|info",
 "젤네일 휴식기 팩트체크 — 꼭 필요할까|info",
 "이번 주 별자리별 행운 네일 컬러|info",
 "손이 예뻐 보이는 네일 모양 고르는 법|info",
 "짧은 손톱에 더 예쁜 숏네일 디자인 모음|info",
 "네일샵 처음 가는 사람을 위한 예약→시술 안내|info",
 "손 나이 -5살 만드는 핸드크림 바르는 순서|info",
 "웨딩·상견례를 위한 온화한 네일 추천|info",
 "젤 제거 후 얇아진 손톱 회복시키는 법|info",
 "가을 뉴트럴 컬러 미리보기 — 올해 유행 예측|info",
 "네일 오래가는 사람들의 공통 습관 5|info",
 "손톱에 좋은 음식 티어리스트 — 영양소 기준 등급|tier",
 "퍼스널컬러 봄웜 필수 네일 컬러 5|info",
 "탑코트 하나로 달라지는 광 — 추천 제품과 참고가|product",
 "이달의 탄생석 컬러 네일과 그 의미|info",
 "패디 시즌 — 발 관리 순서와 꿀팁|info",
 "민감한 손톱을 위한 저자극 케어 가이드|info",
 "피부톤별 피해야 할 네일 컬러|info",
 "미니멀 원컬러를 고급스럽게 하는 법|info",
 "손톱 물어뜯는 습관 끊는 현실적인 방법|info",
 "젤네일 첫 24시간이 중요한 이유 — 시술 후 관리|info",
]

def load_or_make_topics():
    today=datetime.date.today()
    idx=(today-ANCHOR).days
    batch=idx//30; within=idx%30
    data=None
    if TOPICS_FILE.exists():
        try: data=json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
        except: data=None
    if data is None or int(data.get("batch",-1))!=batch:
        prev=(data or {}).get("topics",[])
        topics=run_ok(generate_topic_batch,batch,prev) or FALLBACK_TOPICS
        data={"batch":batch,"generated":str(today),"topics":topics}
        TOPICS_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=1),encoding="utf-8")
        print(f"  🗓️ 새 30일 주제 배치 #{batch} 생성·저장")
    t=data["topics"][within%len(data["topics"])]
    if "|" in t: topic,ttype=t.rsplit("|",1)
    else: topic,ttype=t,"info"
    return topic.strip(), ttype.strip()

def generate_topic_batch(batch, prev):
    prompt=f"""서울 송파/문정 1인 네일샵 '리버니 네일룸' 인스타 카드뉴스의 다음 30일 주제를 만들어.
직전 배치와 겹치지 않게: {json.dumps(prev[:30],ensure_ascii=False)}

규칙:
- 잠재고객(네일에 관심 있는 20~40대 여성)이 저장/팔로우하게 만드는 주제만.
- 제목은 후킹형으로 — '모르면 손해보는', '아는 사람만 아는', '~하면 큰일나는' 같은 클릭 유도 어법을 30개 중 8개 이상에 섞어.
- 구성 비율: 티어리스트/순위(한국인 취향 저격) 4개 이상, 제품 소개(참고가 포함) 3개 이상,
  띠별/별자리/탄생석 운세 네일 3개 이상, 관리/케어 팁, 디자인 추천, 네일 상식 골고루.
- 각 줄 형식: "주제문|타입"  (타입은 info / tier / product 중 하나)
순수 JSON 배열만 출력: ["주제|info", "주제|tier", ...] 정확히 30개."""
    r=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-5","max_tokens":2200,"messages":[{"role":"user","content":prompt}]},timeout=120)
    txt=r.json()["content"][0]["text"]
    arr=json.loads(txt[txt.find("["):txt.rfind("]")+1])
    return arr[:30] if len(arr)>=25 else None

# ══════════════════════════════════════════════
# 콘텐츠 생성
# ══════════════════════════════════════════════
def generate_content(topic, ttype):
    today=datetime.date.today()
    type_rule={
     "info":"""slides 3개, 각각 {"type":"info","heading":"소제목(9자 내)","body":"1~2문장, 한 문장당 18자 내외로 짧게 끊어써(줄바꿈 \\n으로 문장 구분)","tip":"리버니 한 줄 팁(16자 내)","img_query":"이 슬라이드에 어울리는 밝고 화사한 사진 영어 검색어 3~5단어 (예: 'soft pink gel nails manicure')"}""",
     "tier":"""slides는 [1] {"type":"tier","heading":"티어 정리(8자 내)","tiers":[{"grade":"S","items":"항목들(쉼표구분 2개, 짧게)","note":"이유 한 줄(14자 내)"},{"grade":"A",...},{"grade":"B",...}],"img_query":"..."} 와
[2],[3] {"type":"info",...} (S티어 상세/고르는 기준 등, body는 1~2문장 짧게)로 구성. 등급은 솔직하고 근거 있게.""",
     "product":"""slides는 [1] {"type":"product","heading":"제품명(10자 내)","product":{"name":"제품명","price":"참고가 (예: 1만원대 중반)","pros":"장점 한 줄(16자 내)","cons":"아쉬운 점 한 줄(16자 내, 솔직하게)"},"body":"어떤 사람에게 맞는지 1문장(20자 내)","img_query":"제품/사용 장면 영어 검색어 3~5단어"} 와
[2],[3] {"type":"info",...} (사용법/궁합 팁, body는 1~2문장 짧게)으로 구성. 가격은 '참고가'로 대략 범위만 — 단정 금지."""}
    prompt=f"""너는 송파/문정 프라이빗 1인 네일샵 '리버니 네일룸'(@libunny.nailroom)의 콘텐츠 에디터.
마스코트 토끼 '리버니'가 팔로워에게 오늘의 네일 정보를 다정하게 알려주는 카드뉴스야.
오늘({today.month}월 {today.day}일) 주제: "{topic}"

[톤] 다정+화사, 호들갑 금지, 이모지 금지(디자인에서 처리함).
[글자 수 — 반드시 지킬 것] 이 카드뉴스는 모바일 세로 카드라 글자가 많으면 안 읽혀.
모든 문장은 최대한 짧게. 위에 명시된 글자 수 제한을 절대 넘기지 마.
1문장 = 1의미 단위로 끊고, 접속사·수식어를 과감히 생략해.
[원칙] 카드마다 '저장할 가치'가 있는 구체 정보 1개 이상. 뻔한 말 금지, 아티스트만 아는 디테일을
아주 짧은 문장으로. 길게 설명하지 말고 핵심만.
[표지 훅] title은 후킹형 — 주제가 이미 후킹형이면 살리고, 아니면 '모르면 손해보는/아는 사람만 아는/
저장 필수' 류의 어법으로 강화. 단, 과장 광고 금지(팩트 기반).

{type_rule.get(ttype,type_rule["info"])}

순수 JSON만:
{{"cover":{{"kicker":"티저 한 줄(예: 모르면 손해보는) 8자 내","title1":"제목 윗줄(7자 내)","title2":"제목 아랫줄(8자 내)","sub":"부제(14자 내, 뭘 얻어가는지)","bubble":"리버니 말풍선(12자 내, 예: 오늘은 이거 알려줄게요)"}},
"slides":[...위 규칙대로 3개...],
"last":{{"next_tease":"다음 콘텐츠 예고(16자 내)"}},
"caption":"인스타 캡션 — 첫 줄 훅 / 요약 2줄 / '저장해두고 네일 고를 때 꺼내보세요' 류 CTA / 해시태그 15개(#송파네일 #문정동네일 #문정네일 #리버니네일룸 필수 포함)"}}"""
    r=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-5","max_tokens":2800,"messages":[{"role":"user","content":prompt}]},timeout=120)
    if r.status_code!=200: raise RuntimeError(f"Claude API {r.status_code}: {r.text[:200]}")
    txt=r.json()["content"][0]["text"]
    data=json.loads(txt[txt.find("{"):txt.rfind("}")+1])
    print(f"  ✅ 콘텐츠: {data['cover']['title1']} {data['cover']['title2']}")
    return data

# ══════════════════════════════════════════════
# 렌더 — 표지
# ══════════════════════════════════════════════
def render_cover(data, path, date):
    img=Image.new("RGB",(W,H),CREAM); d=ImageDraw.Draw(img)
    c=data["cover"]
    # 아치 프레임 (레퍼런스 이미지1)
    m=64
    d.arc([m,m,W-m,m+640],180,360,fill=LINE,width=3)
    d.line([m,m+320,m,H-m],fill=LINE,width=3)
    d.line([W-m,m+320,W-m,H-m],fill=LINE,width=3)
    d.line([m,H-m,W-m,H-m],fill=LINE,width=3)
    # 로고 (자간 세리프)
    tracked(d,0,150,"LIBUNNY NAIL",F("en",46),BROWN,track=16,center_w=W)
    divider_dot(d,W/2,236,60)
    # 킥커(후킹 티저)
    f_k=F("pen",58)
    kick=clean(c.get("kicker",""))
    if kick:
        kw,_=tw(d,kick,f_k); d.text((W/2-kw/2,300),kick,font=f_k,fill=ROSE)
    # 제목 (세리프 볼드, 뒤에 스와시 하이라이트)
    f_t=F("kb",112)
    lines=[clean(c.get("title1","")),clean(c.get("title2",""))]
    y=396
    for i,ln in enumerate(lines):
        if not ln: continue
        lw,lh=tw(d,ln,f_t)
        if i==len([x for x in lines if x])-1:
            d.rounded_rectangle([W/2-lw/2-14,y+66,W/2+lw/2+14,y+118],radius=24,fill=(233,222,206))
        d.text((W/2-lw/2,y),ln,font=f_t,fill=BROWN)
        y+=150
    heart_line(d,W/2+tw(d,lines[0] or " ",f_t)[0]/2+70,410,42,fill=LINE,width=3)
    # 부제
    divider_dot(d,W/2,y+40,150)
    f_s=F("kr",44)
    sub=clean(c.get("sub",""))
    sw,_=tw(d,sub,f_s); d.text((W/2-sw/2,y+76),sub,font=f_s,fill=SOFT)
    # 리버니 + 말풍선
    bunny(img,W/2,y+330,s=1.15)
    speech_bubble(d,W/2,y+430,c.get("bubble","오늘도 리버니가 알려줄게요"),F("pen",46))
    # 안개꽃 + 반짝이
    babys_breath(d,120,H-110,1.0)
    sparkle(d,W-170,300,12); sparkle(d,150,470,9); sparkle(d,W-140,H-220,10)
    # 하단
    f_f=F("kr",30)
    ft=f"{date.month}월 {date.day}일 · 저장해두고 천천히 보세요"
    fw,_=tw(d,ft,f_f); d.text((W/2-fw/2,H-130),ft,font=f_f,fill=SOFT)
    img.save(path,quality=95)

# ══════════════════════════════════════════════
# 렌더 — 본문 (info / tier / product)
# ══════════════════════════════════════════════
def slide_frame(img,d,idx):
    """공통: 점선 박스 + 리본 + 로고 + 페이지 표기 + 토끼."""
    ribbon_bow(d,W/2,120,0.9)
    tracked(d,0,178,"LIBUNNY NAIL",F("en",30),SOFT,track=10,center_w=W)
    dashed_round_box(d,[70,240,W-70,H-150],r=60)
    f_no=F("en",34)
    d.text((96,H-128),f"no.{idx+1}",font=f_no,fill=SOFT)
    hd="@libunny.nailroom"; f_h=F("en",28)
    hw,_=tw(d,hd,f_h); d.text((W-96-hw,H-126),hd,font=f_h,fill=SOFT)
    bunny(img,W-150,262,s=0.5)

def head_block(d,heading,y=316):
    f_h=F("kb",64)
    ln=clean(heading); hw,_=tw(d,ln,f_h)
    d.text((W/2-hw/2,y),ln,font=f_h,fill=BROWN)
    divider_dot(d,W/2,y+104,170)
    return y+150

def tip_block(d,tip,y):
    t=clean(tip)
    if not t: return y
    f_p=F("pen",52)
    txt="리버니 팁 · "+t
    pw,_=tw(d,txt,f_p)
    d.text((W/2-pw/2,y),txt,font=f_p,fill=ROSE)
    return y+80

def render_info(sl, idx, path, photo):
    bg=[CREAM,PINKBG][idx%2]   # 연두색(SAGEBG) 제거 — 크림/핑크만 순환
    img=Image.new("RGB",(W,H),bg); d=ImageDraw.Draw(img)
    slide_frame(img,d,idx)
    zone_top=head_block(d,sl.get("heading",""))
    tip=clean(sl.get("tip",""))
    # 팁이 있으면 하단 팁 슬롯을 비워두고 그 위 공간에 중앙정렬,
    # 팁이 없으면 박스 하단까지 전체를 정렬 영역으로 사용(위쪽 쏠림 버그 수정)
    if tip:
        tip_y=H-256; zone_bottom=tip_y-40
    else:
        tip_y=None; zone_bottom=H-150-40
    PHOTO_H=380
    max_body=3 if photo else 6
    f_b=F("kr",44)
    body_lines=wrap_kr(d,clean(sl.get("body","")),f_b,W-340)[:max_body]
    photo_h = (PHOTO_H+50) if photo else 0
    body_h = len(body_lines)*66
    total_h = photo_h+body_h
    zone_h = zone_bottom-zone_top
    y = zone_top+max(16,(zone_h-total_h)/2)
    if photo:
        paste_photo_panel(img,d,photo,[210,y,W-210,y+PHOTO_H]); y+=PHOTO_H+50
    for ln in body_lines:
        lw,_=tw(d,ln,f_b); d.text((W/2-lw/2,y),ln,font=f_b,fill=BROWN); y+=66
    if tip_y is not None:
        dashed_line(d,W/2-140,tip_y-30,W/2+140,tip_y-30)
        tip_block(d,tip,tip_y)
    sparkle(d,150,320,9); sparkle(d,W-160,H-260,10)
    img.save(path,quality=95)

def render_tier(sl, idx, path, photo):
    img=Image.new("RGB",(W,H),CREAM); d=ImageDraw.Draw(img)
    slide_frame(img,d,idx)
    zone_top=head_block(d,sl.get("heading","티어 정리"))
    tip_y=H-232
    zone_bottom=tip_y-30
    grade_col={"S":ROSE,"A":GOLD,"B":SOFT}
    f_g=F("en",50); f_i=F("kb",38); f_n=F("kr",30)
    tiers=(sl.get("tiers") or [])[:3]
    # 1단계: 각 행 높이를 먼저 측정
    rows=[]
    for t in tiers:
        g=str(t.get("grade","?")).upper()[:1]
        item_lines=wrap_kr(d,clean(t.get("items","")),f_i,W-380)[:2]
        note_lines=wrap_kr(d,clean(t.get("note","")),f_n,W-380)[:2]
        row_h=max(84,2+len(item_lines)*48+8+len(note_lines)*40)
        rows.append((g,item_lines,note_lines,row_h))
    total_h=sum(r[3] for r in rows)+30*max(0,len(rows)-1)
    zone_h=zone_bottom-zone_top
    y=zone_top+max(16,(zone_h-total_h)/2)
    # 2단계: 중앙정렬된 시작점부터 그리기
    for ri,(g,item_lines,note_lines,row_h) in enumerate(rows):
        col=grade_col.get(g,SOFT)
        row_top=y
        d.ellipse([130,y,206,y+76],outline=col,width=4)
        gw,_=tw(d,g,f_g); d.text((168-gw/2,y+8),g,font=f_g,fill=col)
        for i,ln in enumerate(item_lines):
            d.text((236,y+2+i*48),ln,font=f_i,fill=BROWN)
        note_y=y+2+len(item_lines)*48+8
        for i,ln in enumerate(note_lines):
            d.text((236,note_y+i*40),ln,font=f_n,fill=SOFT)
        y=row_top+row_h+30
        if ri<len(rows)-1:
            dashed_line(d,130,y-15,W-130,y-15,dash=8,gap=10)
    tip_y=H-232
    dashed_line(d,W/2-140,tip_y-30,W/2+140,tip_y-30)
    tip_block(d,sl.get("tip","등급은 리버니 사용 기준이에요"),tip_y)
    img.save(path,quality=95)

def render_product(sl, idx, path, photo):
    img=Image.new("RGB",(W,H),PINKBG); d=ImageDraw.Draw(img)
    slide_frame(img,d,idx)
    zone_top=head_block(d,sl.get("heading",""))
    zone_bottom=H-150-40   # product 슬라이드엔 별도 tip 존이 없어 박스 하단까지 사용
    pr=sl.get("product",{}) or {}
    price=clean(pr.get("price",""))
    f_pr=F("kb",46); f_b=F("kr",40); f_pc=F("kr",34); f_lab=F("kb",34)
    PHOTO_H=340
    body_lines=wrap_kr(d,clean(sl.get("body","")),f_b,W-320)[:4]
    rows=[]
    for label,key,col in [("좋아요","pros",ROSE),("아쉬워요","cons",SOFT)]:
        v=clean(pr.get(key,""))
        if not v: continue
        lab=f"· {label}  "
        lw,_=tw(d,lab,f_lab)
        lines=wrap_kr(d,v,f_pc,W-360-lw)[:2]
        rows.append((lab,lw,lines,col))
    # 1단계: 전체 블록 높이 측정(사진+가격뱃지+본문+장단점)
    photo_h=(PHOTO_H+34) if photo else 0
    price_h=104 if price else 0
    body_h=(len(body_lines)*58+16) if body_lines else 0
    procon_h=sum(max(46,46*len(lines))+20 for _,_,lines,_ in rows)
    total_h=photo_h+price_h+body_h+procon_h
    zone_h=zone_bottom-zone_top
    y=zone_top+max(16,(zone_h-total_h)/2)
    # 2단계: 중앙정렬된 시작점부터 그리기
    if photo:
        paste_photo_panel(img,d,photo,[250,y,W-250,y+PHOTO_H]); y+=PHOTO_H+34
    if price:
        pw,_=tw(d,"참고가  "+price,f_pr)
        d.rounded_rectangle([W/2-pw/2-30,y,W/2+pw/2+30,y+78],radius=39,fill=WHITE,outline=LINE,width=2)
        d.text((W/2-pw/2,y+12),"참고가  "+price,font=f_pr,fill=BROWN); y+=104
    for ln in body_lines:
        lw,_=tw(d,ln,f_b); d.text((W/2-lw/2,y),ln,font=f_b,fill=BROWN); y+=58
    if body_lines: y+=16
    for lab,lw,lines,col in rows:
        d.text((170,y),lab,font=f_lab,fill=col)
        for i,ln in enumerate(lines):
            d.text((170+lw,y+i*46),ln,font=f_pc,fill=BROWN)
        y+=max(46,46*len(lines))+20
    img.save(path,quality=95)

# ══════════════════════════════════════════════
# 렌더 — 마지막 장 (브랜드 카드 + 강한 CTA)
# ══════════════════════════════════════════════
def render_last(data, path):
    img=Image.new("RGB",(W,H),PINKBG); d=ImageDraw.Draw(img)
    m=64
    d.rounded_rectangle([m,m,W-m,H-m],radius=54,outline=LINE,width=3)
    bunny(img,W/2,430,s=1.9)
    tracked(d,0,600,"LIBUNNY NAIL",F("en",52),BROWN,track=18,center_w=W)
    f_kr=F("kb",64)
    t="리버니 네일룸"; kw_,_=tw(d,t,f_kr); d.text((W/2-kw_/2,676),t,font=f_kr,fill=BROWN)
    divider_dot(d,W/2,790,150)
    # 강한 CTA
    f_q=F("kr",46)
    q="당신에게 가장 잘 어울리는 네일을"
    qw,_=tw(d,q,f_q); d.text((W/2-qw/2,836),q,font=f_q,fill=BROWN)
    q2="만나고 싶다면?"
    q2w,_=tw(d,q2,f_q); d.text((W/2-q2w/2,900),q2,font=f_q,fill=BROWN)
    f_big=F("kb",76)
    big="리버니네일"
    bw_,_=tw(d,big,f_big)
    d.rounded_rectangle([W/2-bw_/2-46,980,W/2+bw_/2+46,1096],radius=58,fill=WHITE,outline=LINE,width=3)
    d.text((W/2-bw_/2,996),big,font=f_big,fill=ROSE)
    f_i=F("kr",34)
    info="송파·문정 프라이빗 1인샵 · 예약은 프로필 링크"
    iw,_=tw(d,info,f_i); d.text((W/2-iw/2,1130),info,font=f_i,fill=SOFT)
    tease=clean((data.get("last") or {}).get("next_tease",""))
    if tease:
        f_t2=F("pen",48)
        tt="다음 이야기 · "+tease
        tw2,_=tw(d,tt,f_t2); d.text((W/2-tw2/2,1196),tt,font=f_t2,fill=ROSE)
    heart_line(d,W/2,1284,30,fill=ROSE,width=3)
    sparkle(d,190,240,11); sparkle(d,W-180,320,9); sparkle(d,W-220,1180,10)
    img.save(path,quality=95)

# ══════════════════════════════════════════════
# 이메일
# ══════════════════════════════════════════════
def send_email(files, caption, topic):
    if SKIP_EMAIL:
        print("  ✉️ SKIP_EMAIL=true → 발송 생략"); return
    if not (GMAIL_ADDR and GMAIL_PW and MAIL_TO):
        print("  ⚠️ 이메일 시크릿 미설정 → 발송 생략"); return
    today=datetime.date.today()
    msg=MIMEMultipart()
    msg["Subject"]=f"🐰 리버니 오늘의 게시물 ({today.month}/{today.day}) — {topic[:24]}"
    msg["From"]=GMAIL_ADDR; msg["To"]=MAIL_TO
    body=("리버니 네일룸 오늘의 카드뉴스가 완성됐어요!\n\n"
          "① 첨부 이미지 5장을 순서대로 저장 (01→05)\n"
          "② 아래 캡션 복사 → 인스타 붙여넣기\n\n"
          "──────── 캡션 (복사용) ────────\n\n"+caption+
          "\n\n────────────────────────\n"
          "수정하고 싶으면: repo의 posts_nail/latest/content.json을 에디터(tools/nail_post_editor.html)로 열어 고치고\n"
          "Actions에서 rerender=true로 재실행하면 새 버전이 다시 도착해요.")
    msg.attach(MIMEText(body,"plain","utf-8"))
    for f in files:
        with open(f,"rb") as fp:
            part=MIMEImage(fp.read())
            part.add_header("Content-Disposition","attachment",filename=Path(f).name)
            msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as s:
        s.login(GMAIL_ADDR,GMAIL_PW)
        s.sendmail(GMAIL_ADDR,[m.strip() for m in MAIL_TO.split(",")],msg.as_string())
    print(f"  ✉️ 발송 완료 → {MAIL_TO}")

# ══════════════════════════════════════════════
def main():
    today=datetime.date.today()
    if RERENDER:
        cj=OUT/"content.json"
        if not cj.exists():
            print("❌ 재렌더 모드인데 posts_nail/latest/content.json이 없음"); sys.exit(1)
        data=json.loads(cj.read_text(encoding="utf-8"))
        topic=data.get("_topic","(재렌더)")
        print(f"🔁 재렌더 모드 — content.json 기반")
    else:
        if not ANTHROPIC_KEY:
            print("❌ ANTHROPIC_API_KEY(오타 시크릿 ANTROPIC_API_KEY로 주입) 없음"); sys.exit(1)
        topic,ttype = (TOPIC_OVERRIDE,"info") if TOPIC_OVERRIDE else load_or_make_topics()
        print(f"🐰 리버니 데일리 | 주제: {topic} ({ttype})")
        data=generate_content(topic,ttype)
        data["_topic"]=topic
    # 기존 이미지 캐시 유지(재렌더 시 사진 재검색 안 함)
    photo_cache={}
    if RERENDER and (OUT/"assets").exists():
        for p in (OUT/"assets").glob("photo_*.jpg"): photo_cache[p.stem]=p
    tmp=Path("._nail_tmp"); 
    if tmp.exists(): shutil.rmtree(tmp)
    tmp.mkdir(); (tmp/"assets").mkdir()
    files=[]
    p=tmp/"01_cover.png"; render_cover(data,p,today); files.append(p)
    FALLBACK_Q={"info":"pastel manicure nails close up","product":"nail care product flatlay pastel nails"}
    print(f"  🔑 사진 API 키 상태 — PEXELS_API_KEY: {'있음(' + str(len(PEXELS_KEY)) + '자)' if PEXELS_KEY else '❌ 없음'} / "
          f"UNSPLASH_ACCESS_KEY: {'있음(' + str(len(UNSPLASH_KEY)) + '자)' if UNSPLASH_KEY else '❌ 없음'}")
    for i,sl in enumerate((data.get("slides") or [])[:3]):
        photo=None
        t=sl.get("type","info")
        pr=sl.get("product",{}) or {}
        # 이 슬라이드의 주제 텍스트(제목+제품명+본문)에서 키워드 매칭 → 구체적 검색어 강제
        subject_text=" ".join([sl.get("heading",""),pr.get("name",""),
                                " ".join(sl.get("body",[])) if isinstance(sl.get("body"),list) else str(sl.get("body","")),
                                sl.get("img_query","")])
        forced=subject_override(subject_text)
        claude_q=(sl.get("img_query") or "").strip()
        fb=FALLBACK_Q.get(t)
        queries=(forced or [])+([claude_q] if claude_q else [])+([fb] if fb else [])
        key=f"photo_{i}"
        if key in photo_cache:
            photo=tmp/"assets"/f"{key}.jpg"; shutil.copy(photo_cache[key],photo)
            print(f"  🖼️ 슬라이드{i+1}: 캐시된 사진 재사용")
        elif t!="tier" and queries:
            if forced: print(f"    → 주제 키워드 매칭: '{forced[0]}' 우선 검색")
            print(f"  🔎 슬라이드{i+1} 사진 검색 ({t}) — 후보 {len(queries)}개: {queries}")
            cand=tmp/"assets"/f"{key}.jpg"
            if run_ok(fetch_photo,queries,cand): photo=cand
            time.sleep(1.2)   # API 요청 사이 짧은 간격 — 버스트 레이트리밋 방지
        p=tmp/f"{i+2:02d}_slide.png"
        if t=="tier": render_tier(sl,i,p,photo)
        elif t=="product": render_product(sl,i,p,photo)
        else: render_info(sl,i,p,photo)
        files.append(p)
    p=tmp/"05_last.png"; render_last(data,p); files.append(p)
    caption=data.get("caption","")
    (tmp/"caption.txt").write_text(caption,encoding="utf-8")
    (tmp/"content.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    if OUT.exists(): shutil.rmtree(OUT)
    shutil.move(str(tmp),str(OUT))
    files=[OUT/f.name for f in files]
    ARCH.mkdir(parents=True,exist_ok=True)
    for f in list(files)+[OUT/"caption.txt"]:
        shutil.copy(f,ARCH/Path(f).name)
    print(f"  ✅ 카드 {len(files)}장 → {OUT}")
    send_email([str(f) for f in files],caption,topic)
    print("🎉 완료!")

if __name__=="__main__":
    main()
