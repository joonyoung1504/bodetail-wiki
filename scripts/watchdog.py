#!/usr/bin/env python3
"""
bodetail-vault raw/ 폴더 감시 → Claude API 분류 → git push 자동화 스크립트
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
VAULT_ROOT = Path(__file__).parent.parent.resolve()
RAW_DIR = VAULT_ROOT / "raw"
LOG_FILE = Path(__file__).parent / "watchdog.log"

VALID_FOLDERS = [
    "product", "brand", "market", "ops",
    "decisions", "content", "marketing_auto",
]

KNOWN_CONCEPTS = [
    "BFRB", "무수오일", "롤온", "MOQ", "저장률", "완주율", "수요검증",
    "스모크테스트", "대기자명단", "오가닉마케팅", "예창패", "화장품법",
    "D2C", "재구매구조", "독점처방", "단위경제", "CAC", "LTV",
    "블루오션", "메타API", "AB실험", "4겹해자", "EP시리즈", "훅",
    "비포애프터", "Adam-TTS", "상표출원", "릴스", "벤더독점직수출",
    "K뷰티", "옥스블러드",
]

# ── 로깅 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def read_file_content(file_path: Path) -> str:
    """md / html 파일을 텍스트로 읽기"""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    if file_path.suffix.lower() == ".html":
        # html 태그 제거 (간단 처리)
        import re
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def get_existing_notes(vault_root: Path) -> list[str]:
    """raw/ 제외한 분류된 노트 목록 반환"""
    notes = []
    for folder in VALID_FOLDERS:
        folder_path = vault_root / folder
        if folder_path.exists():
            for f in sorted(folder_path.glob("*.md")):
                notes.append(f"{folder}/{f.stem}")
    return notes


def git_push(vault_root: Path, commit_msg: str) -> bool:
    """git add . → commit → push. 성공 여부 반환."""
    for cmd in (
        ["git", "add", "."],
        ["git", "commit", "-m", commit_msg],
        ["git", "push"],
    ):
        result = subprocess.run(cmd, cwd=vault_root, capture_output=True, text=True)
        if result.returncode != 0:
            # "nothing to commit"은 무시
            if "nothing to commit" in result.stdout + result.stderr:
                log.info("커밋할 변경 없음 — push 건너뜀")
                return True
            log.error(f"git 오류 ({' '.join(cmd)}): {result.stderr.strip()}")
            return False
        log.info(f"git: {' '.join(cmd)} → OK")
    return True


# ── Claude API 분류 ────────────────────────────────────────────────────────────

def build_prompt(file_path: Path, content: str, existing_notes: list[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    notes_str = "\n".join(existing_notes) if existing_notes else "(없음)"
    concepts_str = ", ".join(KNOWN_CONCEPTS)

    return f"""당신은 bodetail(바디테일) 스타트업의 Obsidian 세컨드브레인 자동 분류 봇입니다.

## 폴더 가이드
- product/   : 제품 설계·처방·용기·단위경제
- brand/     : 브랜드 정체성·페르소나·콘텐츠 전략
- market/    : 시장 분석·경쟁사·수출 전략
- ops/       : OEM·공급망·운영·법무·인증
- decisions/ : 의사결정 기록
- content/   : 콘텐츠 기획·릴스·성과 분석
- marketing_auto/ : 마케팅 자동화·데이터 파이프라인

## 현재 볼트 노트 목록
{notes_str}

## 알려진 Concept 태그 (concepts/ 폴더)
{concepts_str}

## 처리할 원본 파일
파일명: {file_path.name}

{content}

## 지시사항
위 파일을 분석해서 **JSON만** 응답하세요. 코드블록·설명 텍스트 없이 순수 JSON.

{{
  "target_folder": "위 7개 폴더 중 하나",
  "target_filename": "한국어-kebab-case.md",
  "processed_content": "완성된 마크다운 전체"
}}

processed_content 형식 (frontmatter + 본문 + Knowledge Connections):
---
summary: "한 줄 핵심 요약"
tags: [태그1, 태그2, 태그3]
created: {today}
updated: {today}
---

# 제목

(원본 내용을 보존하되 섹션 구조 정리)

## Knowledge Connections
- **Related Topics:** [[concepts/개념1]], [[concepts/개념2]]
- **Related Notes:** [[폴더/노트명]], [[폴더/노트명]]
- **Open Questions:** 미결 사항 (없으면 "없음")

규칙:
- 원본 내용을 절대 삭제하지 말 것 — 구조화·정리만
- Related Topics는 위 concepts 목록에 실제 있는 것만
- Related Notes는 위 볼트 노트 목록에 실제 있는 것만
- target_filename은 내용을 잘 반영하는 간결한 한국어 kebab-case
"""


def call_claude(prompt: str) -> dict:
    import anthropic  # 런타임 import (API 키 검사 후 호출)
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # 마크다운 코드블록 안에 있을 경우 추출
    if "```" in raw:
        parts = raw.split("```")
        for i, part in enumerate(parts):
            stripped = part.lstrip("json").strip()
            if stripped.startswith("{"):
                raw = stripped
                break

    return json.loads(raw)


def classify_and_move(file_path: Path) -> tuple[str, str]:
    """
    raw/ 파일을 Claude로 분류 → 대상 폴더에 저장 → 원본 삭제.
    반환: (target_folder, target_filename)
    """
    content = read_file_content(file_path)
    existing_notes = get_existing_notes(VAULT_ROOT)
    prompt = build_prompt(file_path, content, existing_notes)

    log.info(f"Claude API 호출: {file_path.name}")
    result = call_claude(prompt)

    target_folder = result.get("target_folder", "ops")
    target_filename = result.get("target_filename", file_path.name)
    processed_content = result.get("processed_content", content)

    if target_folder not in VALID_FOLDERS:
        log.warning(f"유효하지 않은 폴더 '{target_folder}' → 'ops' 로 대체")
        target_folder = "ops"

    if not target_filename.endswith(".md"):
        target_filename += ".md"

    target_dir = VAULT_ROOT / target_folder
    target_dir.mkdir(exist_ok=True)
    target_path = target_dir / target_filename

    # 파일명 충돌 방지
    if target_path.exists():
        stem, suffix = target_path.stem, target_path.suffix
        target_path = target_dir / f"{stem}-{datetime.now().strftime('%H%M%S')}{suffix}"
        target_filename = target_path.name

    target_path.write_text(processed_content, encoding="utf-8")
    log.info(f"저장: {target_folder}/{target_filename}")

    file_path.unlink()
    log.info(f"원본 삭제: raw/{file_path.name}")

    return target_folder, target_filename


# ── 파일시스템 이벤트 핸들러 ──────────────────────────────────────────────────

class RawFolderHandler(FileSystemEventHandler):
    def __init__(self):
        self._in_progress: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        # .md / .html 만
        if path.suffix.lower() not in (".md", ".html"):
            return

        # 숨김·임시 파일 무시
        if path.name.startswith(".") or path.name.startswith("~"):
            return

        key = str(path)
        if key in self._in_progress:
            return
        self._in_progress.add(key)

        log.info(f"새 파일 감지: {path.name}")

        # Obsidian이 파일 쓰기 완료할 때까지 잠시 대기
        time.sleep(3)

        if not path.exists():
            self._in_progress.discard(key)
            return

        try:
            folder, filename = classify_and_move(path)
            commit_msg = f"auto: {filename} 분류완료 → {folder}/"
            git_push(VAULT_ROOT, commit_msg)
        except json.JSONDecodeError as e:
            log.error(f"JSON 파싱 오류: {e}")
        except Exception as e:
            log.error(f"처리 오류 ({path.name}): {e}", exc_info=True)
        finally:
            self._in_progress.discard(key)


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.error(
            "ANTHROPIC_API_KEY 환경변수가 없습니다.\n"
            "scripts/SETUP.md 를 참고해 API 키를 설정하세요."
        )
        sys.exit(1)

    if not RAW_DIR.exists():
        log.error(f"raw/ 폴더를 찾을 수 없습니다: {RAW_DIR}")
        sys.exit(1)

    log.info("=" * 60)
    log.info(f"bodetail-vault watchdog 시작")
    log.info(f"Vault: {VAULT_ROOT}")
    log.info(f"감시 폴더: {RAW_DIR}")
    log.info("=" * 60)

    handler = RawFolderHandler()
    observer = Observer()
    observer.schedule(handler, str(RAW_DIR), recursive=False)
    observer.start()

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        log.info("중단 신호 수신 — 종료 중...")
        observer.stop()

    observer.join()
    log.info("watchdog 종료")


if __name__ == "__main__":
    main()
