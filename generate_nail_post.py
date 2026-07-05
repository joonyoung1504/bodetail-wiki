# -*- coding: utf-8 -*-
"""
리버니 네일룸(@libunny.nailroom) 데일리 게시물 생성기 v1
─ bodetail 데일리 게시물 시스템과 같은 구조, 무드만 리버니(화사한 파스텔+토끼)로 전환 ─

매일: 주제 스케줄에서 오늘 주제 선택 → Claude가 콘텐츠 생성(실용 정보 의무)
      → 파스텔 카드 5장(1080×1350) + 캡션 렌더 → posts_nail/latest/ 커밋
      → 완성본을 이메일로 발송 (누나는 메일에서 이미지 저장 → 인스타 업로드만 하면 끝)

타겟: 네일에 관심 있는 잠재고객(송파/문정 지역 + 네일 관심사) → 팔로우 유도
"""
import os, sys, json, shutil, smtplib, datetime, random, re
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
OUT = Path("posts_nail/latest")
ARCH = Path("posts_nail")/datetime.datetime.now().strftime("%Y-%m-%d")

# ── 리버니 팔레트 (피드 실물 무드 기반: 아이보리·연핑크·세이지·펄) ──
CREAM   = (251, 247, 242)   # 바탕 아이보리
PINK    = (247, 231, 229)   # 소프트 핑크
SAGE    = (232, 237, 227)   # 세이지 그린
PEARL   = (244, 242, 238)   # 펄 화이트
BROWN   = (107, 93, 82)     # 본문 웜 브라운그레이
ROSE    = (192, 138, 138)   # 포인트 로즈
GOLD    = (196, 168, 130)   # 포인트 골드베이지
GRAYPK  = (201, 191, 184)   # 토끼 몸통(크로셰 토끼 톤)
INNER   = (238, 210, 208)   # 토끼 귀 안쪽
BG_CYCLE = [CREAM, PINK, SAGE, PEARL, PINK]

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY","").strip()   # 게시물용(정확한 철자)
TOPIC_OVERRIDE = os.environ.get("TOPIC_OVERRIDE","").strip()
SKIP_EMAIL = os.environ.get("SKIP_EMAIL","").strip().lower() in ("1","true","yes")
GMAIL_ADDR = os.environ.get("GMAIL_ADDRESS","").strip()
GMAIL_PW   = os.environ.get("GMAIL_APP_PASSWORD","").strip()
MAIL_TO    = os.environ.get("MAIL_TO","").strip() or GMAIL_ADDR

# ══════════════════════════════════════════════
# 주제 스케줄 (일자 % 30 순환 — 원하는 대로 문구 수정 가능)
# 카테고리: 띠별/운세네일 · 관리꿀팁 · 케어템/영양제 · 디자인추천 · 퍼스널컬러 · 상황별 · 네일상식
# ══════════════════════════════════════════════
TOPICS = [
 "이번 달 띠별 행운 네일 컬러 추천 — 띠별로 좋은 기운을 주는 컬러와 그 의미",
 "젤네일 2주 더 오래 가게 하는 관리 꿀팁 5가지",
 "손톱 세로줄·갈라짐, 원인과 해결법 — 집에서 하는 케어 루틴",
 "물어뜯은 손톱도 예뻐지는 과정 — 손톱 모양 교정의 모든 것",
 "여름 물놀이에도 안 지워지는 네일 디자인 & 컬러 추천",
 "손톱 영양제 진짜 효과 있을까? 성분별(비오틴·콜라겐·케라틴) 정리",
 "퍼스널컬러 봄웜이 하면 예쁜 네일 컬러 5가지",
 "퍼스널컬러 여름쿨이 하면 예쁜 네일 컬러 5가지",
 "직장인을 위한 단정하지만 밋밋하지 않은 오피스 네일 추천",
 "젤네일 휴식기, 꼭 필요할까? 손톱 건강 팩트체크",
 "큐티클, 뜯지 말고 이렇게 — 집에서 하는 큐티클 케어 순서",
 "이번 주 별자리별 행운 네일 컬러",
 "손이 예뻐 보이는 네일 모양 고르는 법 (라운드·아몬드·스퀘어)",
 "짧은 손톱에 더 예쁜 디자인 모음 — 숏네일 추천",
 "네일샵 처음 가는 사람을 위한 예약~시술 과정 안내",
 "손 나이 -5살, 핸드크림 바르는 진짜 올바른 방법",
 "웨딩·상견례 등 중요한 날을 위한 온화한 네일 추천",
 "젤 제거 후 얇아진 손톱 회복시키는 법",
 "가을 뉴트럴 네일 컬러 미리보기 — 올해 유행 예측",
 "네일 오래 가는 사람들의 공통 습관 5가지",
 "손톱 건강에 좋은 음식 — 영양소별 정리",
 "퍼스널컬러 가을웜이 하면 예쁜 네일 컬러 5가지",
 "퍼스널컬러 겨울쿨이 하면 예쁜 네일 컬러 5가지",
 "이달의 탄생석 컬러 네일 — 의미와 어울리는 디자인",
 "패디큐어 시즌 준비 — 발 관리 순서와 꿀팁",
 "민감한 손톱을 위한 저자극 네일 케어 가이드",
 "네일 디자인 고를 때 피부톤별 피해야 할 컬러",
 "미니멀 네일 유행 — 원컬러를 고급스럽게 하는 법",
 "손톱 물어뜯는 습관 끊는 현실적인 방법",
 "시술 후 관리 안내 — 젤네일 첫 24시간이 중요한 이유",
]

def today_topic():
    if TOPIC_OVERRIDE: return TOPIC_OVERRIDE
    return TOPICS[datetime.date.today().day % len(TOPICS)]

# ══════════════════════════════════════════════
# STEP 1: Claude로 콘텐츠 생성
# ══════════════════════════════════════════════
def generate_content(topic):
    today=datetime.date.today()
    prompt=f"""너는 서울 송파/문정동의 프라이빗 1인 네일샵 '리버니 네일룸'(@libunny.nailroom)의
인스타 콘텐츠 에디터야. 오늘({today.year}년 {today.month}월 {today.day}일) 카드뉴스 주제:

"{topic}"

[브랜드 톤]
- 다정하고 화사한 언니 톤. 과장·호들갑 금지, 이모지는 🤍🐰✨ 정도만 아주 절제해서.
- 리버니 = 토끼 캐릭터의 아늑하고 사랑스러운 무드. 파스텔(아이보리·연핑크·세이지).

[콘텐츠 원칙 — 반드시]
- 읽는 사람이 '저장'하고 싶어질 실용 정보/팁이 카드마다 최소 1개씩 반드시 들어갈 것.
- 뻔한 얘기 금지. 네일 아티스트만 아는 디테일을 한 스푼씩.
- 띠별/별자리/탄생석 주제면: 항목별로 [컬러 이름 + 왜 좋은지 의미 + 어울리는 포인트] 구성.
- 잠재고객이 팔로우할 이유(다음 콘텐츠 기대감)를 마지막 카드에 자연스럽게.

순수 JSON만 출력:
{{"title_line1":"표지 제목 윗줄(6자 내외)","title_line2":"표지 제목 아랫줄(8자 내외)",
"hook_sub":"표지 부제 한 줄(15자 내외, 왜 봐야 하는지)",
"slides":[
 {{"num":"01","heading":"소제목(10자 내외)","body":"본문 2~3문장. 줄바꿈은 \\n","tip":"한 줄 꿀팁(25자 내외)"}},
 {{"num":"02","heading":"...","body":"...","tip":"..."}},
 {{"num":"03","heading":"...","body":"...","tip":"..."}}
],
"cta_note":"마지막 카드용 한 줄(다음 콘텐츠 기대 문구, 20자 내외)",
"caption":"인스타 캡션. 첫 줄 훅 → 내용 요약 2~3줄 → 저장/팔로우 유도 → 해시태그 15개(#송파네일 #문정동네일 #문정네일 #리버니네일룸 포함 + 주제 관련 + 잠재고객 검색어)"}}"""
    r=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-sonnet-4-5","max_tokens":2500,
              "messages":[{"role":"user","content":prompt}]},timeout=120)
    if r.status_code!=200:
        raise RuntimeError(f"Claude API 오류 {r.status_code}: {r.text[:300]}")
    txt=r.json()["content"][0]["text"].strip()
    txt=re.sub(r"^```(json)?|```$","",txt,flags=re.M).strip()
    data=json.loads(txt[txt.find("{"):txt.rfind("}")+1])
    print(f"  ✅ 콘텐츠 생성: {data['title_line1']} {data['title_line2']}")
    return data

# ══════════════════════════════════════════════
# STEP 2: 카드 렌더 (파스텔 + 토끼 + 반짝이)
# ══════════════════════════════════════════════
def _font(bold, size):
    cands = (["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"] if bold else
             ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"])
    for p in cands:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

EMOJI_RE=re.compile("["
    "\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D"
    "]+")
def clean(t):
    """카드에 렌더되는 텍스트에서 이모지 제거 — Noto CJK엔 이모지 글리프가 없어 □로 깨짐.
    (캡션은 인스타에서 정상 표시되므로 그대로 둠)"""
    return EMOJI_RE.sub("",str(t)).strip()

def draw_heart(d, cx, cy, s, color):
    """이모지 대신 벡터 하트."""
    r=s*0.30
    d.ellipse([cx-2*r, cy-r, cx, cy+r], fill=color)
    d.ellipse([cx, cy-r, cx+2*r, cy+r], fill=color)
    d.polygon([(cx-2*r,cy+r*0.35),(cx+2*r,cy+r*0.35),(cx,cy+2.1*r)], fill=color)

def _tw(d, txt, f):
    b=d.textbbox((0,0),txt,font=f); return b[2]-b[0], b[3]-b[1]

def draw_bunny(d, cx, cy, s=1.0, tone=GRAYPK):
    """크로셰 토끼 느낌의 미니멀 토끼(머리+귀) — 리버니 시그니처."""
    r=int(64*s)
    # 귀 (바깥)
    d.ellipse([cx-r*0.72-r*0.30, cy-r*2.05, cx-r*0.72+r*0.30, cy-r*0.45], fill=tone)
    d.ellipse([cx+r*0.72-r*0.30, cy-r*2.05, cx+r*0.72+r*0.30, cy-r*0.45], fill=tone)
    # 귀 안쪽
    d.ellipse([cx-r*0.72-r*0.15, cy-r*1.82, cx-r*0.72+r*0.15, cy-r*0.62], fill=INNER)
    d.ellipse([cx+r*0.72-r*0.15, cy-r*1.82, cx+r*0.72+r*0.15, cy-r*0.62], fill=INNER)
    # 얼굴
    d.ellipse([cx-r, cy-r*0.9, cx+r, cy+r*0.9], fill=tone)
    # 눈·코
    er=max(4,int(6*s))
    d.ellipse([cx-r*0.38-er, cy-er, cx-r*0.38+er, cy+er], fill=(60,52,46))
    d.ellipse([cx+r*0.38-er, cy-er, cx+r*0.38+er, cy+er], fill=(60,52,46))
    d.ellipse([cx-5*s, cy+r*0.28-4*s, cx+5*s, cy+r*0.28+4*s], fill=INNER)

def draw_sparkle(d, x, y, s, color=GOLD):
    """네 갈래 반짝이 ✦"""
    d.polygon([(x,y-s),(x+s*0.28,y-s*0.28),(x+s,y),(x+s*0.28,y+s*0.28),
               (x,y+s),(x-s*0.28,y+s*0.28),(x-s,y),(x-s*0.28,y-s*0.28)],fill=color)

def deco_common(d, seed):
    random.seed(seed)
    for _ in range(7):
        x=random.randint(60,W-60); y=random.randint(50,H-50)
        draw_sparkle(d,x,y,random.randint(7,14),
                     random.choice([GOLD,(224,205,190),(230,218,206)]))

def rounded(d, box, radius, fill, outline=None, width=3):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def wrap_kr(d, text, f, max_w):
    lines=[]
    for raw in str(text).split("\n"):
        cur=""
        for ch in raw:
            if _tw(d,cur+ch,f)[0]>max_w and cur and ch not in ".,!?~…)”\u0027":
                lines.append(cur); cur=ch
            else: cur+=ch
        lines.append(cur)
    return lines

def render_cover(data, path, date):
    img=Image.new("RGB",(W,H),CREAM); d=ImageDraw.Draw(img)
    deco_common(d, 11)
    # 상단 라벨
    f_eyebrow=_font(False,34)
    lbl="LIBUNNY NAIL · 리버니 네일룸"
    tw,_= _tw(d,lbl,f_eyebrow)
    rounded(d,[W/2-tw/2-34,110,W/2+tw/2+34,178],34,PINK)
    d.text((W/2-tw/2,126),lbl,font=f_eyebrow,fill=ROSE)
    # 날짜
    f_date=_font(False,30)
    ds=f"{date.year}년 {date.month}월 {date.day}일"
    dw,_=_tw(d,ds,f_date); d.text((W/2-dw/2,214),ds,font=f_date,fill=GOLD)
    # 제목
    f_t=_font(True,118)
    for i,line in enumerate([data["title_line1"],data["title_line2"]]):
        if not line: continue
        tw,_=_tw(d,line,f_t)
        d.text((W/2-tw/2,330+i*150),clean(line),font=f_t,fill=BROWN)
    # 부제 박스
    f_s=_font(False,42)
    sub=clean(data.get("hook_sub",""))
    sw,_=_tw(d,sub,f_s)
    rounded(d,[W/2-sw/2-44,680,W/2+sw/2+44,764],42,SAGE)
    d.text((W/2-sw/2,698),sub,font=f_s,fill=BROWN)
    # 토끼
    draw_bunny(d, W/2, 1010, s=1.5)
    # 하단 안내
    f_b=_font(False,34)
    tip="저장해두고 천천히 보세요"
    bw,_=_tw(d,tip,f_b); d.text((W/2-bw/2,H-140),tip,font=f_b,fill=ROSE)
    draw_heart(d, W/2+bw/2+34, H-122, 24, ROSE)
    img.save(path,quality=95)

def render_slide(sl, idx, path):
    bg=BG_CYCLE[idx%len(BG_CYCLE)]
    img=Image.new("RGB",(W,H),bg); d=ImageDraw.Draw(img)
    deco_common(d, 20+idx)
    # 번호 뱃지
    f_num=_font(True,54)
    rounded(d,[80,96,244,196],50,(255,255,255))
    nw,_=_tw(d,sl["num"],f_num); d.text((162-nw/2,116),sl["num"],font=f_num,fill=ROSE)
    # 미니 토끼 우상단
    draw_bunny(d, W-150, 190, s=0.62)
    # 소제목
    f_h=_font(True,72)
    for i,ln in enumerate(wrap_kr(d,clean(sl["heading"]),f_h,W-200)[:2]):
        d.text((90,270+i*92),ln,font=f_h,fill=BROWN)
    # 구분선(점선 느낌)
    for x in range(90,W-90,26):
        d.ellipse([x,470,x+7,477],fill=GOLD)
    # 본문 (흰 카드 위)
    f_b=_font(False,44)
    body_lines=wrap_kr(d,clean(sl["body"]),f_b,W-260)[:9]
    card_h=len(body_lines)*66+90
    rounded(d,[80,520,W-80,520+card_h],36,(255,255,255))
    for i,ln in enumerate(body_lines):
        d.text((130,566+i*66),ln,font=f_b,fill=BROWN)
    # 팁 박스
    tip=clean(sl.get("tip",""))
    if tip:
        f_tip=_font(True,40)
        y0=520+card_h+46
        tip_lines=wrap_kr(d,"tip.  "+clean(tip),f_tip,W-300)[:2]
        th=len(tip_lines)*58+56
        rounded(d,[80,y0,W-80,y0+th],32,PINK if bg!=PINK else SAGE)
        for i,ln in enumerate(tip_lines):
            d.text((130,y0+28+i*58),ln,font=f_tip,fill=ROSE)
    # 하단 핸들
    f_f=_font(False,30)
    hd="@libunny.nailroom"
    hw,_=_tw(d,hd,f_f); d.text((W/2-hw/2,H-96),hd,font=f_f,fill=GOLD)
    img.save(path,quality=95)

def render_last(data, path):
    img=Image.new("RGB",(W,H),PINK); d=ImageDraw.Draw(img)
    deco_common(d, 99)
    draw_bunny(d, W/2, 400, s=2.0)
    f_t=_font(True,84)
    t="리버니 네일룸"
    tw,_=_tw(d,t,f_t); d.text((W/2-tw/2,560),t,font=f_t,fill=BROWN)
    f_s=_font(False,42)
    lines=["송파 · 문정동 프라이빗 1인샵",
           "첫 방문 EVENT 진행 중",
           "예약·문의는 프로필 링크로"]
    for i,ln in enumerate(lines):
        lw,_=_tw(d,ln,f_s); d.text((W/2-lw/2,700+i*76),ln,font=f_s,fill=BROWN)
    # CTA 노트
    note=clean(data.get("cta_note",""))
    if note:
        f_n=_font(True,44)
        nw,_=_tw(d,note,f_n)
        rounded(d,[W/2-nw/2-46,1010,W/2+nw/2+46,1104],44,(255,255,255))
        d.text((W/2-nw/2,1032),note,font=f_n,fill=ROSE)
    f_h=_font(True,48)
    hd="@libunny.nailroom  팔로우"
    hw,_=_tw(d,hd,f_h); d.text((W/2-hw/2,1170),hd,font=f_h,fill=ROSE)
    draw_heart(d, W/2+hw/2+42, 1200, 30, ROSE)
    img.save(path,quality=95)

# ══════════════════════════════════════════════
# STEP 3: 이메일 발송
# ══════════════════════════════════════════════
def send_email(files, caption, topic):
    if SKIP_EMAIL:
        print("  ✉️ SKIP_EMAIL=true → 발송 생략"); return
    if not (GMAIL_ADDR and GMAIL_PW and MAIL_TO):
        print("  ⚠️ GMAIL_ADDRESS / GMAIL_APP_PASSWORD / MAIL_TO 시크릿이 없어 이메일 생략"); return
    today=datetime.date.today()
    msg=MIMEMultipart()
    msg["Subject"]=f"🐰 리버니 오늘의 게시물 ({today.month}/{today.day}) — {topic[:24]}"
    msg["From"]=GMAIL_ADDR; msg["To"]=MAIL_TO
    body=("리버니 네일룸 오늘의 카드뉴스가 완성됐어요!\n\n"
          "① 첨부된 이미지 5장을 저장하세요 (01→05 순서)\n"
          "② 아래 캡션을 복사해서 인스타에 붙여넣으세요\n\n"
          "──────── 캡션 (복사용) ────────\n\n"+caption+
          "\n\n────────────────────────\n(자동 발송 · bodetail automation)")
    msg.attach(MIMEText(body,"plain","utf-8"))
    for f in files:
        with open(f,"rb") as fp:
            part=MIMEImage(fp.read())
            part.add_header("Content-Disposition","attachment",filename=Path(f).name)
            msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as s:
        s.login(GMAIL_ADDR,GMAIL_PW)
        s.sendmail(GMAIL_ADDR,[m.strip() for m in MAIL_TO.split(",")],msg.as_string())
    print(f"  ✉️ 이메일 발송 완료 → {MAIL_TO}")

# ══════════════════════════════════════════════
def main():
    topic=today_topic()
    print(f"🐰 리버니 데일리 게시물 | 주제: {topic}")
    if not ANTHROPIC_KEY:
        print("❌ ANTHROPIC_API_KEY 시크릿 없음"); sys.exit(1)
    data=generate_content(topic)
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True,exist_ok=True)
    today=datetime.date.today()
    files=[]
    p=OUT/"01_cover.png"; render_cover(data,p,today); files.append(p)
    for i,sl in enumerate(data.get("slides",[])[:3]):
        p=OUT/f"{i+2:02d}_slide.png"; render_slide(sl,i,p); files.append(p)
    p=OUT/"05_last.png"; render_last(data,p); files.append(p)
    caption=data.get("caption","")
    (OUT/"caption.txt").write_text(caption,encoding="utf-8")
    (OUT/"content.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    ARCH.mkdir(parents=True,exist_ok=True)
    for f in files+[OUT/"caption.txt"]:
        shutil.copy(f,ARCH/Path(f).name)
    print(f"  ✅ 카드 {len(files)}장 + 캡션 → {OUT}")
    send_email([str(f) for f in files],caption,topic)
    print("🎉 완료!")

if __name__=="__main__":
    main()
