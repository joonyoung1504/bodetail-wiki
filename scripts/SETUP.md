---
tags: [layer/meta]
---

# watchdog 설정 가이드

## 1. Python 패키지 설치

터미널(PowerShell 또는 CMD)에서 아래 실행:

```bash
cd C:\Users\이준영\Desktop\옵시디언\bodetail-vault
pip install -r scripts\requirements.txt
```

---

## 2. Anthropic API 키 설정

**방법 A — 배치파일에 직접 입력 (간단)**

`scripts\start_watchdog.bat` 를 메모장으로 열고:
```
set ANTHROPIC_API_KEY=YOUR_KEY_HERE
```
`YOUR_KEY_HERE` 부분을 실제 API 키로 교체 후 저장.

**방법 B — Windows 시스템 환경변수 등록 (권장, 더 안전)**

1. `Win + S` → "환경 변수" 검색 → **시스템 환경 변수 편집** 클릭
2. 하단 **환경 변수** 버튼 클릭
3. "사용자 변수" 또는 "시스템 변수" → **새로 만들기**
4. 변수 이름: `ANTHROPIC_API_KEY`
5. 변수 값: 실제 API 키 붙여넣기
6. 확인 → 확인

방법 B를 쓰면 `start_watchdog.bat` 안의 `set ANTHROPIC_API_KEY=` 줄은 삭제해도 됩니다.

---

## 3. 수동 테스트 실행

```bash
cd C:\Users\이준영\Desktop\옵시디언\bodetail-vault
scripts\start_watchdog.bat
```

`raw/` 폴더에 `.md` 파일을 하나 복사해 넣으면 자동 분류가 시작됩니다.
로그는 `scripts\watchdog.log` 에 기록됩니다.

---

## 4. 윈도우 시작 시 자동 실행 등록

### 방법 A — 시작프로그램 폴더에 바로가기 추가 (가장 쉬움)

1. `Win + R` → `shell:startup` 입력 → 엔터
2. 시작프로그램 폴더가 열리면, `start_watchdog.bat` 의 **바로가기** 를 이 폴더에 붙여넣기
   - `start_watchdog.bat` 우클릭 → **바로 가기 만들기** → 생성된 바로가기를 시작프로그램 폴더로 이동
3. PC 재시작 후 자동 실행 확인

### 방법 B — 작업 스케줄러 등록 (백그라운드, 창 숨김)

1. `Win + S` → **작업 스케줄러** 검색 → 실행
2. 오른쪽 **작업 만들기** 클릭
3. **일반** 탭:
   - 이름: `bodetail-watchdog`
   - "사용자가 로그온할 때만 실행" 선택
   - "가장 높은 수준의 권한으로 실행" 체크
4. **트리거** 탭 → 새로 만들기:
   - 작업 시작: **로그온할 때**
5. **동작** 탭 → 새로 만들기:
   - 동작: **프로그램 시작**
   - 프로그램/스크립트: `C:\Users\이준영\Desktop\옵시디언\bodetail-vault\scripts\start_watchdog.bat`
6. **확인** → 저장

---

## 5. 자동 실행 해제 방법

- **방법 A (시작프로그램):** `shell:startup` 폴더에서 바로가기 삭제
- **방법 B (작업 스케줄러):** 작업 스케줄러에서 `bodetail-watchdog` 우클릭 → 삭제

---

## 6. 로그 확인

```bash
# 최근 50줄 확인
Get-Content scripts\watchdog.log -Tail 50
```

---

## 7. 파일 분류 흐름

```
raw/ 에 파일 추가
    ↓ (3초 대기, 쓰기 완료 확인)
Claude API 호출 (분류 + 구조화 + Knowledge Connections)
    ↓
product/ brand/ market/ ops/ decisions/ content/ marketing_auto/ 중 하나로 이동
    ↓
raw/ 원본 삭제
    ↓
git add . → git commit → git push
```
