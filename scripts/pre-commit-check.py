#!/usr/bin/env python3
"""bodetail-vault pre-commit 검사.

WIKI-RULES.md/CLAUDE.md에 문장으로만 적혀 있던 규칙을 실제로 강제한다.

1. decisions/ 폴더 파일 삭제 차단 (deprecated 태그 여부와 무관 — 삭제 자체를 금지)
2. decisions/ 파일 내용이 deprecated 태그 없이 대부분(80% 이상) 삭제되면 차단
3. 스테이징된 .md 파일에 frontmatter summary 필드가 없으면 경고(차단 아님)
4. posts/latest/post_content.json의 표지 headline이 잠금값과 다르면 차단
   (posts/는 .gitignore 대상이라 스테이징 여부와 무관하게 매 커밋마다 검사)
5. 커밋에 50개 이상 파일이 포함되면 CLAUDE.md 예외조항 확인 y/n 프롬프트

exit 0 = 커밋 진행, exit 1 = 커밋 차단.
"""
import re
import subprocess
import sys
from pathlib import Path

# Windows 콘솔 기본 코드페이지(cp949 등)로 한글 출력이 깨지는 것 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GIT_BASE = ["git", "-c", "core.quotepath=false"]
WIPE_RATIO_THRESHOLD = 0.2  # 원본 대비 이 비율 이하로 줄면 "통째로 지워짐"으로 간주
MIN_HEAD_LINES_FOR_WIPE_CHECK = 10  # 너무 짧은 파일은 잡음이 많아 검사 제외
BULK_CHANGE_THRESHOLD = 50


def run(cmd):
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.stdout


def staged_name_status():
    """스테이징된 변경을 (status, old_path, new_path) 리스트로 반환. new_path는 rename일 때만 값 있음."""
    out = run(GIT_BASE + ["diff", "--cached", "--name-status", "-M"])
    entries = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") or status.startswith("C"):
            entries.append((status, parts[1], parts[2]))
        else:
            entries.append((status, parts[1], None))
    return entries


def get_staged_content(path):
    """스테이징(인덱스)된 버전의 파일 내용. 없으면 None."""
    result = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout if result.returncode == 0 else None


def get_head_content(path):
    """HEAD 커밋 시점의 파일 내용. 없으면 None."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout if result.returncode == 0 else None


def frontmatter_block(content):
    if content is None:
        return None
    m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    return m.group(1) if m else None


def has_deprecated_tag(content):
    fm = frontmatter_block(content)
    if fm is None:
        return False
    m = re.search(r"^tags:\s*\[(.*?)\]", fm, re.MULTILINE)
    if not m:
        return False
    return "deprecated" in m.group(1)


def has_summary_field(content):
    fm = frontmatter_block(content)
    if fm is None:
        return False
    return re.search(r"^summary:", fm, re.MULTILINE) is not None


def check_decisions_integrity(entries):
    """decisions/ 삭제·대량 지움을 검사해 차단 사유 목록을 반환."""
    problems = []
    for status, old, new in entries:
        if status.startswith("D"):
            if old.startswith("decisions/") and old.endswith(".md"):
                problems.append(
                    f"[삭제 차단] {old}\n"
                    f"    decisions/ 폴더 파일은 삭제할 수 없습니다 (WIKI-RULES.md '지우지 않는다' 원칙).\n"
                    f"    내용을 폐기하려면 삭제 대신 frontmatter tags에 deprecated를 추가하고\n"
                    f"    '→ 진짜 노트는 여기' 리다이렉트 스텁으로 남기세요."
                )
        elif status.startswith("R"):
            still_in_decisions = bool(new) and new.startswith("decisions/")
            if old.startswith("decisions/") and old.endswith(".md") and not still_in_decisions:
                problems.append(
                    f"[이동 차단] {old} → {new}\n"
                    f"    decisions/ 밖으로의 이동은 삭제와 동일하게 취급됩니다."
                )
        elif status.startswith("M"):
            target = new or old
            if target.startswith("decisions/") and target.endswith(".md"):
                head = get_head_content(target)
                staged = get_staged_content(target)
                if head is None or staged is None:
                    continue
                head_lines = len(head.splitlines())
                staged_lines = len(staged.splitlines())
                if head_lines < MIN_HEAD_LINES_FOR_WIPE_CHECK:
                    continue
                ratio = staged_lines / head_lines if head_lines else 1.0
                if ratio <= WIPE_RATIO_THRESHOLD and not has_deprecated_tag(staged):
                    problems.append(
                        f"[내용삭제 차단] {target}\n"
                        f"    {head_lines}줄 → {staged_lines}줄로 {int((1 - ratio) * 100)}% 삭제됐는데\n"
                        f"    deprecated 태그가 없습니다. 의도된 폐기라면 frontmatter tags에\n"
                        f"    deprecated를 추가하세요."
                    )
    return problems


def check_summary_warnings(entries):
    warnings = []
    for status, old, new in entries:
        if status.startswith("D"):
            continue
        target = new or old
        if not target.endswith(".md"):
            continue
        content = get_staged_content(target)
        if content is None:
            continue
        if not has_summary_field(content):
            warnings.append(target)
    return warnings


def check_post_headline_consistency():
    """posts/latest/post_content.json의 표지 headline이 잠금값(_locked_headline)과
    일치하는지 scripts/check_post_consistency.py로 검사한다.

    posts/ 는 .gitignore 대상이라 '스테이징된 파일'만 보는 방식으로는 이 검사를
    걸 수 없다 — 그래서 git 상태와 무관하게 매 커밋마다 무조건 한 번 실행한다.
    반환: (통과여부, 출력텍스트)
    """
    checker = Path(__file__).resolve().parent / "check_post_consistency.py"
    if not checker.exists():
        return True, ""
    result = subprocess.run(
        [sys.executable, str(checker)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def check_bulk_change(entries):
    count = len(entries)
    if count < BULK_CHANGE_THRESHOLD:
        return True
    print(f"\n⚠ 대량 변경 감지: 이번 커밋에 {count}개 파일이 포함됩니다.")
    print("  CLAUDE.md '자동 실행의 예외' 조항(50개 이상 파일 변경 시 확인 후 진행)에 해당합니다.")
    try:
        answer = input("  CLAUDE.md 예외조항을 확인했고 계속 진행합니까? [y/N] ")
    except EOFError:
        print("\n  비대화형 환경이라 확인을 받을 수 없어 커밋을 차단합니다.")
        print("  확인했다면 'git commit --no-verify'로 우회하거나 터미널에서 다시 시도하세요.")
        return False
    return answer.strip().lower() == "y"


def main():
    entries = staged_name_status()

    problems = check_decisions_integrity(entries)
    warnings = check_summary_warnings(entries)

    headline_ok, headline_output = check_post_headline_consistency()
    if headline_output:
        print(headline_output)
    if not headline_ok:
        problems.append(
            "[표지 headline 불일치] posts/latest/post_content.json\n"
            "    위 scripts/check_post_consistency.py 출력을 참고하세요."
        )

    if warnings:
        print("⚠ summary 필드 누락 (경고만, 커밋은 계속 진행됩니다):")
        for w in warnings:
            print(f"  - {w}")

    if problems:
        print("\n커밋이 차단되었습니다:\n")
        for p in problems:
            print(f"  {p}\n")
        sys.exit(1)

    if not check_bulk_change(entries):
        print("\n커밋이 취소되었습니다.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
