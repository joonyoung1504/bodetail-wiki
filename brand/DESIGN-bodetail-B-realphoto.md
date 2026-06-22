---
version: alpha
name: bodetail-instagram-design-system-B-REALPHOTO
variant: "버전 B — 실사 사진 + 잉크블랙 그림자 레이어 (감도 높은 서양풍 무드컷을 우리 톤으로 통일)"
description: >
  남성 디테일 무드 매거진을 위한 포토 퍼스트 카드뉴스 시스템. 깊은 잉크 블랙 캔버스
  위에 절제된 골드와 따뜻한 크림 타이포가 얹히고, 정확히 3:4(1080×1440)로 고정된 그리드에서
  Fraunces 세리프와 Pretendard 한글이 두 개의 목소리로 말한다. 핀터레스트 패션 매거진의
  여백감, 오늘의집의 레이아웃 문법(좌상단 라벨 / 하단 정렬 헤드라인 / 넘버링 슬라이드 /
  마지막 로고 마무리), 부산 무드매거진의 연재 문법(2단 헤드라인 + VOL. 시리즈 넘버링 +
  사진 소재 무관 동일 그라데이션 처리)을 결합하고, liadio의 감도 3원칙(과감한 클로즈업 ·
  은은한 도형으로 공간감 · 형태 반복으로 리듬)을 핵심 엔진으로 삼는다. 운영자 본인의
  신원은 드러내지 않되(faceless = 준영 본인 노출 안 함), 감도 높은 서양풍 실사 무드컷에
  잉크블랙 그림자 레이어를 한 층 씌워 어떤 사진이 와도 우리 톤(잉크블랙·골드)으로 통일한다.
  세르칸이 영화 스틸을 쓰는 것과 같은 "기성 사진 활용" 전략이되, 출처는 라이선스가 명확한
  소스로 한정한다. 모든 색은 사진과 골드 한 끗에만 허락된다. 광고가 아니라
  "디테일을 챙기는 남자의 안목" 그 자체.

colors:
  ink: "#0C0C0C"          # 브랜드 블랙 — 기본 캔버스
  ink-2: "#141414"        # 미세 밝은 변형 — 면 분리/깊이
  ink-3: "#1C1A17"        # 따뜻한 차콜 — 도형/그림자 톤
  gold: "#B0844A"         # 시그니처 골드 — 라벨·디바이더·강조에만
  gold-bright: "#C89A5C"  # 소폭 밝은 골드 — 작은 포인트
  cream: "#EDE6D8"        # 워드마크·세리프 헤드라인
  white: "#F5F4F0"        # 오프화이트 — 메인 임팩트 헤드라인
  body-muted: "#A9A39A"   # 서브카피·캡션 그레이
  hairline: "#B0844A"     # 골드 헤어라인(저알파로 사용)
  caption-veil: "rgba(12,12,12,0.55)"   # 캡션 박스 반투명 배경(오늘의집/liadio식)
  depth-veil: "rgba(255,255,255,0.045)" # 은은한 도형(공간감)용 라이트 베일
  depth-gold: "rgba(176,132,74,0.10)"   # 골드 도형 베일
  scrim-bottom: "rgba(12,12,12,0.65)"   # 하단 헤드라인 가독용 그라데이션(아래→위 롱 페이드)

typography:
  wordmark:
    fontFamily: "Fraunces, serif"
    fontSize: 80px
    fontWeight: 400
    lineHeight: 1.0
    letterSpacing: 0.5px
    note: "bodetail 워드마크. 소문자. 마지막 슬라이드/서명에만."
  display-serif:
    fontFamily: "Fraunces, serif"
    fontSize: 104px
    fontWeight: 400
    lineHeight: 1.0
    letterSpacing: -0.5px
    note: "에디토리얼 커버 헤드라인. 로만+이탤릭 혼용 가능(Sent / Bloom 식)."
  display-impact:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 900
    fontSize: 132px
    lineHeight: 0.95
    letterSpacing: -1px
    textTransform: uppercase
    note: "영문 펀치 헤드라인(FIND YOUR CORE / RICH BALM 식). 꽉 채운 클로즈업."
  headline-kr:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 700
    fontSize: 76px
    lineHeight: 1.18
    letterSpacing: -1px
    note: "한글 메인 헤드라인(오늘의집식). 하단 정렬, 2줄 기준."
  headline-sub:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 400
    fontSize: 34px
    lineHeight: 1.3
    letterSpacing: -0.3px
    note: "헤드라인 위/아래 보조줄(시리즈명·카테고리). 부산 무드매거진 레퍼런스에서 확인한 2단 구조."
  subhead-kr:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 600
    fontSize: 42px
    lineHeight: 1.3
    letterSpacing: -0.5px
    note: "넘버링 슬라이드의 소제목."
  label:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 500
    fontSize: 30px
    lineHeight: 1.0
    letterSpacing: 3px
    textTransform: uppercase
    note: "좌상단 섹션 라벨(WHY / PICK …). 골드."
  series-number:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 600
    fontSize: 24px
    lineHeight: 1.0
    letterSpacing: 1.5px
    textTransform: uppercase
    note: "VOL.XX 회차 표기. 라벨 옆 또는 아래. 연재물 인상으로 다음 편 기대 유도."
  body-kr:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 400
    fontSize: 34px
    lineHeight: 1.5
    letterSpacing: -0.3px
    note: "슬라이드 본문."
  body-en-fine:
    fontFamily: "Fraunces, serif"
    fontWeight: 300
    fontSize: 24px
    lineHeight: 1.45
    letterSpacing: 0px
    note: "커버 보조 영문 단락(liadio식 작은 디스크립션 블록)."
  caption:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 400
    fontSize: 27px
    lineHeight: 1.4
    letterSpacing: -0.2px
    note: "캡션 박스/COMMENT/출처."
  caption-strong:
    fontFamily: "Pretendard, sans-serif"
    fontWeight: 600
    fontSize: 27px
    lineHeight: 1.35
    letterSpacing: -0.2px

rounded:
  none: 0px
  sm: 10px       # 캡션 박스
  md: 16px
  pill: 9999px   # 배지/라벨 칩
  ellipse: "50%" # 공간감 도형

spacing:
  margin-x: 96px        # 좌우 세이프 마진
  margin-y: 112px       # 상하 세이프 마진
  edge-safe: 64px       # 그리드 거터 대비 절대 침범 금지 영역(글자·핵심요소)
  gap-xxs: 12px
  gap-xs: 20px
  gap-sm: 32px
  gap-md: 48px
  gap-lg: 72px

canvas:
  width: 1080px
  height: 1440px
  ratio: "3:4"          # 인스타 그리드 네이티브 = 크롭 0
  note: "절대 1:1/4:5로 내보내지 말 것. 그리드에서 양옆/상하가 잘림."

components:
  slide-cover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
    typography: "{typography.headline-kr}"
    rounded: "{rounded.none}"
    padding: "{spacing.margin-y} {spacing.margin-x}"
  slide-content:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.cream}"
    typography: "{typography.subhead-kr}"
    rounded: "{rounded.none}"
    padding: "{spacing.margin-y} {spacing.margin-x}"
  slide-closing:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.cream}"
    typography: "{typography.wordmark}"
    rounded: "{rounded.none}"
  label-section:
    backgroundColor: transparent
    textColor: "{colors.gold}"
    typography: "{typography.label}"
    note: "좌상단. 아래 골드 헤어라인 1px 동반 가능."
  headline-block:
    backgroundColor: transparent
    textColor: "{colors.white}"
    typography: "{typography.headline-kr}"
    note: "하단 정렬. 위에 scrim-bottom 그라데이션 깔아 가독 확보."
  headline-block-tiered:
    backgroundColor: transparent
    textColor: "{colors.white}"
    typography: "{typography.headline-kr}"
    secondaryTypography: "{typography.headline-sub}"
    secondaryColor: "{colors.body-muted}"
    note: >
      2단 헤드라인(부산 무드매거진 레퍼런스). 굵은 메인 헤드라인 + 그 위/아래
      더 얇은 보조줄(시리즈명·카테고리·맥락 한 줄). 정보량은 늘리되 복잡해 보이지
      않게 하는 핵심 장치. 보조줄이 위면 라벨처럼, 아래면 설명처럼 읽힌다 — 슬라이드
      성격에 따라 위/아래 선택.
  series-badge:
    backgroundColor: transparent
    textColor: "{colors.cream}"
    typography: "{typography.series-number}"
    note: >
      옵셔널 "VOL.07" 표기. label-section 옆 또는 바로 아래, 같은 가로선상.
      연재물이라는 인상 → "다음 편도 보고 싶다"는 기대 유도. 섹션×회차로 카운트
      (예: WHY 섹션 7번째 = WHY VOL.07).
  caption-box:
    backgroundColor: "{colors.caption-veil}"
    textColor: "{colors.white}"
    typography: "{typography.caption}"
    rounded: "{rounded.sm}"
    padding: "20px 28px"
  badge-oval:
    backgroundColor: transparent
    textColor: "{colors.cream}"
    typography: "{typography.caption-strong}"
    rounded: "{rounded.pill}"
    border: "1.5px solid {colors.cream}"
    padding: "12px 26px"
    note: "New / 저장 필수 등. liadio식 아웃라인 배지."
  rating-stars:
    textColor: "{colors.gold}"
    typography: "{typography.caption-strong}"
    note: "PICK/리뷰형. ★★★★★ 골드."
  depth-shape:
    backgroundColor: "{colors.depth-veil}"
    rounded: "{rounded.ellipse}"
    note: "피사체 뒤 은은한 타원. 감도원칙 2."
  comment-block:
    backgroundColor: transparent
    textColor: "{colors.body-muted}"
    typography: "{typography.caption}"
    note: "핀터레스트 카드뉴스식 작은 설명 단락(라벨: COMMENT 골드)."
  divider-hairline:
    backgroundColor: "{colors.gold}"
    note: "라벨/헤드라인 아래 얇은 골드선. 두께 2px, 길이 64~120px."
  number-box:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.ink}"
    typography: "{typography.display-impact}"
    rounded: "{rounded.none}"
    padding: "16px 28px"
    note: >
      좌상단 큰 넘버링 박스("+ 02" 식). 세르칸 벤치마킹. 넘버링 콘텐츠(아키타입 C)의
      슬라이드 순서 표기. 배경은 골드 또는 ink-3, 숫자는 굵게. 캐러셀 전체에 같은 위치 고정.
  signature-wordmark:
    backgroundColor: transparent
    textColor: "{colors.cream}"
    typography: "{typography.caption}"
    letterSpacing: 4px
    note: >
      모든 슬라이드 하단 중앙의 작은 'bodetail' 서명(세르칸의 SERKAN 워드마크 위치).
      자간 넓게, 저채도. 그리드 전체에 동일 위치 → 강력한 시리즈 통일감. 마무리 슬라이드의
      큰 워드마크와는 별개(이건 매 장 구석의 작은 도장).
  source-note:
    backgroundColor: transparent
    textColor: "{colors.body-muted}"
    typography: "{typography.caption}"
    fontSize: 22px
    note: >
      "*출처: ..." 정보 신뢰도 보강(세르칸 벤치마킹). 헤드라인 블록 하단 또는
      캡션박스 아래 작게. 데이터·주장형 콘텐츠에 권위를 더한다.
---

## Overview

bodetail의 인스타그램은 **제품 카탈로그가 아니라 매일 한 장씩 펴보는 무드 매거진**이다. 한 장씩 봐도 작품, 그리드로 모아 봐도 하나의 펼침면. 타깃은 디테일을 챙기고 싶은 20–30대 남자, 그리고 그런 남자를 곁에 두고 싶은 여자 — 핀터레스트에서 이미지를 저장하듯 우리 게시물을 저장하게 만드는 게 목표다.

전체 톤은 **깊은 잉크 블랙 위의 절제**다. 색은 거의 쓰지 않는다. 화면을 채우는 건 사진의 질감과 단 한 끗의 골드, 그리고 따뜻한 크림 타이포뿐. 레이아웃 문법은 오늘의집에서 빌려온다 — 좌상단 작은 섹션 라벨, 사진 위 하단에 묵직하게 앉는 한글 헤드라인, 슬라이드 안의 넘버링된 소제목과 본문, 마지막 장의 로고 마무리. 감도를 끌어올리는 엔진은 liadio의 3원칙(아래 별도 섹션)이다.

**Key Characteristics**
- 포토 퍼스트: UI·장식은 사라지고 사진과 디테일이 말한다. 텍스트는 최소.
- 단일 액센트: 모든 색의 순간은 **골드 한 끗**과 사진에만 허락된다. 두 번째 브랜드 컬러는 없다.
- 두 개의 목소리: **Fraunces 세리프**(에디토리얼·우아) + **Pretendard 한글**(정보·또렷). 영문 펀치는 Pretendard Black.
- faceless: **운영자(준영) 본인의 얼굴·신원만 비공개.** 모델·인물 등장 가능. 단 모든 사진은 **잉크블랙 그림자 레이어 처리**로 우리 톤에 통일(아래 그림자 레이어 시스템).
- 3:4(1080×1440) 고정: 그리드 크롭 0 → "클릭 화면 = 그리드 화면"이 일치.
- 골드는 면적의 약 5% 이하. 흔해지는 순간 싸 보인다.

## 캔버스 & 포맷

- **규격: 1080 × 1440px, 3:4 고정.** 1:1/4:5 금지(그리드에서 잘림).
- **세이프 마진**: 좌우 `{spacing.margin-x}`(96px), 상하 `{spacing.margin-y}`(112px). 글자·핵심 요소는 이 안에.
- **거터 세이프**: 모든 가장자리 `{spacing.edge-safe}`(64px) 안쪽엔 헤드라인·로고·얼굴급 핵심 요소 금지(그리드 셀 사이 거터 대비).
- **캐러셀 순서**: 커버(1) → 콘텐츠 슬라이드(2…N) → 마무리 로고(마지막).
- **릴스 커버 썸네일**: 영상은 9:16(1080×1920)이지만, **그리드에 노출되는 커버 프레임은 피드와 동일한 디자인 문법**(라벨+2단헤드라인+워드마크)을 1080×1440 세이프존 안에 배치 → 그리드에서 잘려도 핵심 텍스트 보존.
- **그리드 삼면화**(고정 소개용)일 때만: 업로드는 역순(우→중→좌)으로 올려 좌→오 정렬을 맞춘다.
- **AI 사진 + 코드 텍스트** 원칙 유지: 배경 사진만 생성, 라벨·헤드라인은 코드(Pillow)가 고정 좌표로 오버레이.

## 컬러 시스템

- 기본 캔버스는 `{colors.ink}`(#0C0C0C). 면을 나눠야 하면 `{colors.ink-2}`/`{colors.ink-3}`로 미세 단차만.
- 헤드라인은 `{colors.white}`(임팩트) 또는 `{colors.cream}`(세리프·우아). 본문/캡션은 `{colors.body-muted}`.
- **골드(`{colors.gold}`)는 라벨·헤어라인·별점·작은 강조에만.** 헤드라인 전체를 골드로 칠하지 않는다(거친 텍스처 위 예외적 타이틀 한 장 정도만 허용).
- 하단 헤드라인 가독은 색을 더하지 말고 `{colors.scrim-bottom}` 그라데이션으로 해결.
- 캡션 박스는 `{colors.caption-veil}` 반투명 — 사진을 가리지 않으면서 글자를 띄운다.

## 타이포그래피

네 개의 레지스터만 쓴다. 섞이면 무너진다.

1. **워드마크 / 우아 — Fraunces.** `{typography.wordmark}`(로고), `{typography.display-serif}`(에디토리얼 커버). 로만+이탤릭 혼용으로 리듬(예: *Find* **Your** *Core*). bodetail다움의 핵심.
2. **영문 펀치 — Pretendard Black.** `{typography.display-impact}`. 화면을 꽉 채우는 대문자 한 마디(감도원칙 1과 짝). 클로즈업 사진 위 하단/좌하단.
3. **한글 헤드라인 — Pretendard Bold.** `{typography.headline-kr}`. 오늘의집식 하단 2줄. 자간 -1px로 또렷하게.
4. **본문/라벨/캡션 — Pretendard.** `{typography.subhead-kr}` / `{typography.body-kr}` / `{typography.label}` / `{typography.caption}`.

> 폰트 파일은 프로젝트 `fonts/` 에 `Fraunces`(Variable 또는 Roman+Italic), `Pretendard`(Regular/Medium/SemiBold/Bold/Black) 전부 박아둘 것. 없으면 렌더가 매번 달라진다.

## 감도 3원칙 (liadio 엔진 — 가장 중요)

매 게시물은 아래 셋 중 **최소 둘**을 만족해야 "완성도 있다"고 본다.

1. **과감한 클로즈업으로 집중도 높이기.** 피사체(손·오브제·질감)를 프레임에 꽉 채운다. 멀리서 찍은 평범한 컷 금지. → `{typography.display-impact}`/`{typography.headline-kr}`와 짝.
2. **은은한 도형으로 공간감 살리기.** 피사체 뒤에 `{component.depth-shape}`(저알파 타원/원)를 깔아 레이어와 깊이를 만든다. 골드 베일(`{colors.depth-gold}`)도 가능. 과하지 않게, 거의 안 보일 만큼.
3. **형태를 반복 배치해 리듬 만들기.** 같은 도형·모티프(타원, 골드 라인, 라벨 위치)를 슬라이드마다 반복 → 캐러셀 전체가 한 호흡으로 읽힌다. 이 반복이 "한 사람이 만든 매거진" 느낌의 8할.

## 슬라이드 아키타입

오늘의집 문법 + 핀터레스트 카드뉴스 + 부산 무드매거진(연재형) 문법. 섹션 타입에 매칭해 로테이션(단조로움 방지).

- **A. 커버(에디토리얼)** — 풀블리드 사진 + 좌상단 `{component.label-section}`(+옵션 `{component.series-badge}`) + 하단 `{component.headline-block-tiered}`(메인 헤드라인 + 보조줄). 텍스트 최소, 여백 충분(FRKT 고감도형).
- **B. 커버(매거진 포스터)** — liadio식: 상단 Fraunces 타이틀 + 좌측 작은 영문 단락(`{typography.body-en-fine}`) + 중앙 클로즈업 피사체 위 `{component.depth-shape}` + 하단 임팩트 한 단어 + 중앙 `{component.caption-box}` 콜아웃.
- **C. 넘버링 콘텐츠** — 좌상단 가로 헤더(`{component.label-section}` + 헤어라인 + `{component.number-box}`를 한 선상에) + 소제목(`{typography.subhead-kr}`) + 본문 2–3줄(`{typography.body-kr}`) + 하단 사진 + 우하단 `{component.caption-box}`(핵심 한 줄). 세르칸 Routine Index형.
- **D. PICK/큐레이션** — 핀터레스트 카드식: 제품 클로즈업 + `{component.rating-stars}` + 작은 라벨(브랜드/가격) + `{component.comment-block}`(COMMENT). *P1에선 타브랜드만.*
- **E. 마무리** — `{component.slide-closing}`: 검은 화면 중앙에 bodetail 워드마크 + 그 아래 한 줄 태그라인("Detail changes everything" / "남들이 놓치는 한 끗").
- **F. 오브제 플랫레이**(세르칸 큐레이션형) — 어두운 바닥에 제품·도구 여러 개를 위에서 내려다보며 정렬(넘버 라벨 01~07 부착). PICK·자기관리템 큐레이션에. 골드 라벨 한 끗 + 저채도.

> **2단 헤드라인 + 시리즈 넘버링은 부산 무드매거진 레퍼런스에서 확인한 패턴.** 사진 소재가 매일 달라도 텍스트 자리·그라데이션 처리를 예외 없이 동일하게 강제해 그리드 전체가 통일감 있게 읽히는 게 핵심 — `scrim-bottom`을 모든 슬라이드에 빠짐없이 적용할 것.

### 세르칸 전수 분석에서 확정한 레이아웃 규칙 (약 100개 게시물·릴스 관찰)

1. **넘버링·연재 표기는 옵션이 아니라 기본값.** 세르칸 제목 대다수가 "BEST 8 / TOP 8 / ~6 / 上中下"를 단다. 저장 욕구의 핵심 장치. 우리도 가능한 한 제목에 숫자나 회차를 넣는다.
2. **헤드라인 자유 배치 허용.** 하단 정렬이 기본이지만, 중앙·상단·좌우 분할도 섞어 단조로움을 깬다. 텍스트를 사진의 빈 공간(어두운 영역)에 맞춰 유동 배치. 단 라벨·워드마크·헤어라인은 고정.
3. **자간 벌리기·단어 분할 리듬.** "외모 / 또한 / 경쟁력", "복 근 지우는 음식"처럼 단어를 띄우거나 자간을 의도적으로 벌려 시적 리듬을 준다. 강조 슬라이드에 한정.
4. **변환 관계 기호.** 화살표(→ ↓)·등호(=)로 "A = B", "A → B" 관계를 표현("전신 피로 OFF 스위치 =발마사지", "남성호르몬 = 잘생김호르몬"). 호기심 유발 + 정보 압축.
5. **피드·릴스 썸네일 동일 톤.** 릴스 커버도 피드와 같은 디자인 문법(라벨+2단헤드라인+워드마크+저채도)을 적용해 그리드 통일감 유지.

## 컴포넌트

**`label-section`** — 좌상단 섹션 라벨. `{colors.gold}` 텍스트, `{typography.label}`(대문자, 자간 3px). 바로 아래 `{component.divider-hairline}`(골드 2px, 길이 64–120px) 동반 가능. 위치 고정: 좌 `{spacing.margin-x}`, 상 `{spacing.margin-y}`.

> **세르칸식 헤더 정렬(권장 패턴)**: 라벨 + 가로 헤어라인 + 끝의 `+` 마크(또는 `{component.number-box}`)를 **한 가로선상에 정렬**한다. 라벨이 왼쪽, 얇은 선이 가로로 화면을 가로지르고, 오른쪽 끝에 넘버/마크. 이 가로 헤더 라인을 모든 슬라이드 같은 높이에 고정하면 캐러셀이 한 권의 매거진처럼 읽힌다.

**`headline-block`** — 하단 정렬 메인 헤드라인. `{colors.white}` + `{typography.headline-kr}`(한글) 또는 `{typography.display-impact}`(영문). 사진 위에 올 땐 `{colors.scrim-bottom}` 그라데이션을 먼저 깐다(별도 박스 없이 가독 확보). 좌 정렬 기본, 좌 `{spacing.margin-x}` / 하 `{spacing.margin-y}`.

> **그라데이션은 짧은 띠가 아니라 사진 하단 35~50%를 덮는 긴 페이드**(세르칸 방식). 아래는 거의 불투명, 위로 갈수록 투명. 어떤 사진이 와도 헤드라인 자리가 항상 어둡게 확보돼 그리드 통일감이 유지된다.

**`caption-box`** — 핵심 한 줄/콜아웃. `{colors.caption-veil}` 배경 + `{colors.white}` 텍스트, `{typography.caption}`, `{rounded.sm}`(10px), 패딩 20×28. 오늘의집의 우하단 설명박스, liadio의 중앙 콜아웃 둘 다 이 컴포넌트.

**`badge-oval`** — "New" / "저장 필수" 등. 배경 투명 + `{colors.cream}` 1.5px 아웃라인 타원, `{rounded.pill}`, `{typography.caption-strong}`. 커버 우상단 또는 피사체 옆.

**`rating-stars`** — PICK/리뷰형 별점. `{colors.gold}` ★★★★★. 제목 위 작은 라벨로(예: "카공 ★★★★★").

**`depth-shape`** — 감도원칙 2의 공간감 도형. `{colors.depth-veil}`(또는 `{colors.depth-gold}`) 타원, `{rounded.ellipse}`. 피사체 뒤 중앙. 거의 안 보일 정도의 저알파가 정답.

**`comment-block`** — 핀터레스트 카드뉴스식 작은 설명. 라벨 "COMMENT"(`{colors.gold}`, `{typography.label}` 축소) + 본문 `{colors.body-muted}` `{typography.caption}`. PICK·디테일 해설에.

**`divider-hairline`** — 골드 헤어라인. `{colors.gold}` 2px. 라벨/워드마크 아래 짧게. 우리 프로필 워드마크의 골드 언더라인과 동일 문법.

**`slide-closing`** — 마무리 슬라이드. `{colors.ink}` 풀블랙 중앙에 `{typography.wordmark}` bodetail(크림) + 아래 태그라인 `{typography.caption}`(`{colors.body-muted}`). 오늘의집이 마지막에 로고로 닫는 것과 동일.

**`number-box`** — 넘버링 콘텐츠(아키타입 C)의 좌상단 큰 숫자 박스("+ 02"). 세르칸 벤치마킹. `{colors.gold}` 또는 `{colors.ink-3}` 배경에 굵은 숫자. **모든 슬라이드에서 같은 위치 고정**이 핵심(반복=리듬).

**`signature-wordmark`** — 매 슬라이드 하단 중앙의 작은 bodetail 서명. 세르칸의 SERKAN 도장과 동일 문법. 자간 넓게(`letterSpacing 4px`), 저채도 크림. 그리드를 모아 봤을 때 "한 사람이 만든 매거진" 인상의 핵심. **마무리 슬라이드의 큰 워드마크와 혼동 금지** — 이건 매 장 구석의 작은 도장.

**`source-note`** — "*출처: ..." 표기. 세르칸 벤치마킹. 데이터·주장형 콘텐츠 하단에 작게 달아 신뢰도를 보강. `{colors.body-muted}`, 22px.

## 사진·이미지 디렉션

- **무드**: 어둡고 따뜻한 잉크 톤, 깊은 그림자, 미세 필름 그레인. 핀터레스트 패션 에디토리얼의 정적이고 고급스러운 정지감.
- **피사체 우선순위**: ① 감도 높은 서양풍 무드 실사(인물·오브제·공간) ② 손·질감·제품 클로즈업. 모두 잉크블랙 그림자 레이어로 톤 통일. **운영자 본인 얼굴은 안 나옴.**
- **구도**: 대칭 회피, 여백 충분, 한 점에 시선 집중(감도원칙 1).
- **카메라 언어 고정**(프롬프트에 매번 동일하게): "35mm, f1.8, shallow depth, slight film grain, warm low-key light, asymmetric composition". 없으면 AI가 'AI스러운 완벽 대칭'으로 회귀.
- **후처리 필터 코드로 강제**: 동일한 그레인 + 컬러 커브 + 약한 비네팅을 모든 컷에 적용 → 생성이 그날그날 달라도 "한 사람이 찍은" 통일감. 일관성의 8할.
- **저채도/흑백 옵션**(세르칸 벤치마킹): 사진을 흑백 또는 강한 저채도로 깔고 색은 골드 라벨 한 끗만 남기는 처리도 강력하다. 채도를 죽이면 그리드가 즉시 통일된다. 한 캐러셀 안에서는 채도 톤을 일관되게.

### 사진 소싱 로직 (어디서 실사를 구하나)

세르칸은 헐리웃 배우·영화 스틸을 그대로 쓴다(무단·저작권 회색지대). 우리는 같은 "기성 감도 사진 활용" 전략을 쓰되 **출처를 라이선스 명확한 곳으로 한정**해 리스크를 없앤다. 계정이 커지고 수익화·투자 단계로 가면 무단 사용은 치명적이므로.

1. **무료 상업 스톡 (주력)** — Unsplash / Pexels / Pixabay API. 서양풍·시네마틱·어두운 무드 키워드로 검색("moody portrait dark", "editorial men fashion noir", "cinematic still low key"). **상업적 사용 가능 + 저작권 표시 불필요** 라이선스만.
2. **유료 스톡 (선택)** — 예산 되면 Adobe Stock·Getty 등에서 더 높은 감도 확보.
3. **AI 생성 (보조)** — 특정 오브제·손 클로즈업이 스톡에 없을 때만.
4. **공통 후처리 = 그림자 레이어**(아래) — 출처가 무엇이든 동일 처리로 우리 톤에 흡수.

→ **금지**: 영화 스틸·유명인 사진 무단 사용(세르칸 방식 직접 모방), 라이선스 불명 이미지, 운영자 본인 얼굴.

## 그림자 레이어 시스템 (버전 B 핵심)

서양풍 실사 사진은 그대로 쓰면 제각각이라 그리드가 깨진다. **잉크블랙 그림자 레이어를 한 층 씌워** 어떤 사진이 와도 우리 톤으로 통일하는 게 이 버전의 엔진이다. 세르칸이 모든 사진에 붉은 그라데이션을 입혀 통일하는 것과 같은 원리, 색만 우리 잉크블랙.

**레이어 스택 (아래→위 순서, 코드로 고정 적용):**

1. **원본 실사** (스톡/AI).
2. **저채도·톤 커브**: 채도 -40~-70%, 콘트라스트 소폭 +, 따뜻한 쪽으로 화이트밸런스. (`{colors.ink}` 계열로 수렴)
3. **잉크블랙 멀티플라이 오버레이**: `{colors.ink}`(#0C0C0C)를 multiply 블렌드로 30~45% 덮음. 사진이 우리 검정에 잠긴다.
4. **하단 롱 그라데이션**: `{colors.scrim-bottom}`을 사진 하단 35~50%에 깔아 헤드라인 자리 확보(`headline-block` 가독).
5. **비네팅**: 가장자리 어둡게 -15~25%, 시선 중앙 집중.
6. **필름 그레인**: 미세 그레인 일정량 → 모든 컷 동일 질감(AI/스톡 출처 섞여도 한 톤).
7. **(옵션) 골드 한 끗**: 라벨·헤어라인에만. 사진엔 색 추가 안 함.

> **이 7단 스택을 코드 상수로 박아 모든 이미지에 동일 적용.** 파라미터(멀티플라이 알파·채도·그레인 강도)는 골든셋으로 캘리브레이션 후 고정. 출처가 달라도 결과 톤이 같아지는 게 핵심 — "한 사람이 찍은 매거진" 통일감의 8할.

**그림자 레이어 톤 가드:**
- 너무 어둡게 덮어 사진이 안 보이면 실패. 피사체는 식별되되 "우리 잉크블랙 세계에 들어온" 느낌이 정답.
- 한 캐러셀 안에서는 멀티플라이 알파를 동일하게(슬라이드마다 밝기 들쑥날쑥 금지).
- 인물 사진일 때 얼굴이 핵심이면 그 부분만 멀티플라이를 약하게(마스크) 해 표정 보존.

## Do's & Don'ts

### Do
- 색의 순간은 **골드 한 끗 + 사진**에만. 나머지는 블랙·크림·화이트·그레이.
- 헤드라인은 하단 정렬, 본문은 최소. 여백을 디자인 요소로 쓴다.
- 감도 3원칙 중 최소 2개를 매 게시물에 적용(클로즈업/도형/반복).
- 라벨·로고·헤어라인 위치를 **모든 슬라이드에서 픽셀 고정**(반복=리듬=감도).
- `{component.headline-block-tiered}`로 메인+보조줄을 함께 써서 정보량을 늘리되, 보조줄 폰트는 항상 메인보다 확연히 얇게(체급 차이가 위계를 만든다).
- 시리즈성 섹션(WHY/PICK 등)엔 `{component.series-badge}`로 회차를 표기해 연재 기대감을 쌓는다.
- 사진 소재가 무엇이든 `{colors.scrim-bottom}` 하단 그라데이션은 예외 없이 적용 — 이게 그리드 전체의 통일감을 만든다.
- 매 슬라이드 하단 중앙에 `{component.signature-wordmark}`(작은 bodetail 도장)를 같은 위치에 박는다 — 세르칸의 SERKAN 서명처럼 시리즈 통일감의 핵심.
- 데이터·주장형 콘텐츠엔 `{component.source-note}`로 출처를 밝혀 권위를 더한다.
- 1080×1440(3:4)로만 내보낸다. 텍스트는 코드로 오버레이.
- Fraunces(우아)와 Pretendard(정보)의 역할을 분리해 쓴다.

### Don't
- 두 번째 액센트 컬러 추가 금지. 골드 외 채도 있는 색은 사진 안에서만.
- 골드로 헤드라인 전체를 칠하지 말 것(거친 텍스처 타이틀 한 장 예외).
- 그라데이션·드롭섀도우·테두리 같은 장식 크롬 금지. 깊이는 사진과 `{component.depth-shape}`로.
- 운영자(준영) 본인 얼굴·신원을 노출하지 말 것 — 사람이 필요하면 라이선스 클리어된 스톡 실사로(그림자 레이어 처리 필수).
- 그림자 레이어를 건너뛴 원본 실사를 그대로 올리지 말 것 — 톤이 깨진다. 모든 사진은 7단 스택을 거친다.
- 저작권 불명 이미지(영화 스틸·유명인 사진 무단)를 쓰지 말 것 — 세르칸이 한다고 우리도 안전한 게 아니다.
- 텍스트를 AI 이미지에 굽지 말 것(한글 깨짐 + 감도 흔들림).
- 1:1/4:5로 업로드 금지. 슬라이드마다 폰트 크기·위치를 즉흥적으로 바꾸지 말 것.

## 카드뉴스 제작 순서 (Claude Code 위임용)

1. `content_calendar.json`에서 당일 항목 로드(섹션 라벨 / 헤드라인 / 슬라이드 본문 / image_prompt / seed 여부).
2. 섹션 타입 → 슬라이드 아키타입(A–E) 매칭, 레이아웃 변형 선택.
3. AI로 **배경 사진만** 생성(카메라 언어 고정) → 후처리 필터 적용.
4. Pillow로 고정 좌표에 `{component.label-section}` → `{component.headline-block}` → 필요 시 `{component.caption-box}`/`{component.depth-shape}` 오버레이.
5. 마지막 슬라이드 `{component.slide-closing}` 자동 부착.
6. 1080×1440 PNG로 내보내기 → 공개 URL 업로드 → 게시.
7. **초반 몇 주는 "초안 → 1초 컨펌 → 게시"**, 이후 완전 자동. 주간 단위로 최근 7일 톤 점검.

## Known Gaps / 미정

- **그림자 레이어 파라미터 미확정** — 멀티플라이 알파(30~45%)·채도 감소율·그레인 강도의 정확한 수치는 골든셋 5~10장으로 캘리브레이션 후 코드 상수로 고정.
- **스톡 소스 키워드 세트 미정** — "moody/cinematic/noir/editorial men" 계열 검색어 풀을 실제 검색하며 정리.
- **보이스 가이드**(금칙어["화장" 등]·호기심갭 제목 공식·캡션 어투·해시태그)는 본 문서 범위 밖 → `voice_guide.md`로 별도.
- Fraunces 이탤릭 혼용 규칙(어떤 단어를 이탤릭으로)은 커버 단위로 케이스화 필요 — 골든셋 누적 후 패턴화.
- `depth-shape` 알파/크기의 정확한 수치는 골든셋 5–10장으로 캘리브레이션 예정.
- 후처리 필터(그레인 강도·커브)의 구체 파라미터는 실제 생성 샘플로 튜닝 후 고정.
- 레이아웃 변형(아키타입별 2–3종)의 정확한 좌표표는 템플릿 확정 시 `templates/`에 별도 명세.
