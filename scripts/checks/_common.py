"""pre-commit 검사 모듈들이 공유하는 헬퍼.

scripts/pre-commit-check.py가 scripts/checks/ 를 sys.path에 넣고 각 검사
모듈을 이름으로 import하므로, 이 모듈도 같은 방식으로 import해서 쓴다.
"""
import re
import subprocess

GIT_BASE = ["git", "-c", "core.quotepath=false"]


def run(cmd):
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.stdout


def staged_name_status():
    """스테이징된 변경을 (status, old_path, new_path) 리스트로 반환.
    new_path는 rename/copy(R/C)일 때만 값 있음."""
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
