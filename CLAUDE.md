# Claude 운영 규칙 (항상 적용)

1. 모든 작업을 승인 없이 자동 실행
2. 파일 수정·생성·삭제 자동 허용
3. 모든 작업 완료 후 반드시 git add . → git commit -m "작업내용 한줄요약" → git push 자동 실행
4. 중간에 나에게 묻지 말 것. 스스로 판단해서 진행
5. 오류 발생 시 스스로 해결 후 계속 진행

## raw/ 파일 추가 시 자동 지식화 규칙

raw/ 폴더에 새 파일이 추가되면 아래를 순서대로 자동 실행:

**1단계 — 분류**
내용 읽고 적절한 폴더로 정리된 노트 생성:
- 제품·처방·성분·용기 → product/
- 브랜드·로고·컬러·페르소나·세계관 → brand/
- 시장·경쟁사·수출·벤더·K뷰티 → market/
- OEM·견적·발주·협의 → ops/
- 의사결정·확정사항 → decisions/
- 콘텐츠·릴스·대본·콘티 → content/
- 마케팅·지표·자동화·바이럴 → marketing_auto/

**2단계 — 키워드 추출 및 객체화**
핵심 개념을 [[키워드]] 단위로 추출:
- 사업 개념 (예: [[무수오일]], [[롤온]], [[BFRB]], [[MOQ]], [[저장률]])
- 해당 키워드 노트가 concepts/ 에 없으면 빈 스텁 노트 생성
- 스텁 형식:
  # [[키워드]]
  ## Brief Summary
  (1~2줄 정의)
  ## Knowledge Connections
  - Related Topics: [[관련개념]]
  - Related Notes: [[관련노트]]
  - Open Questions:

**3단계 — Knowledge Connections 추가**
분류된 노트 맨 아래에 추가:
  ## Knowledge Connections
  - **Related Topics:** [[개념키워드A]], [[개념키워드B]]
  - **Related Notes:** [[기존관련노트]]
  - **Open Questions:** 미확정 사항

**4단계 — 역방향 링크**
기존 관련 노트들에도 이 노트로 오는 [[링크]] 추가

**5단계 — git push**
git add . → git commit -m "auto: [파일명] 지식화 완료" → git push

## 사업 맥락 (항상 참고)
- 브랜드: 바디테일(bodetail) — 20~30대 남성 손톱케어
- 제품: 무수 드라이 오일 세럼, 롤온 20ml, OEM=라온하제
- 타깃: 손톱 물어뜯기(BFRB) 남성 페르소나
- 인스타: @bodetail, 첫 릴스 제작 중
- 규제: 치료·회복·완치 금지 → 관리·정돈·보습·케어만
