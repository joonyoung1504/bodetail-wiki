"""INV-P1: posts/latest/post_content.json의 표지 headline은 잠금값(_locked_headline)과
정확히 일치해야 한다.

실제 검사 로직은 scripts/check_post_consistency.py에 있다(독립적으로도 실행 가능하게
설계됨). 여기서는 그 스크립트를 서브프로세스로 호출해 결과만 이 검사 인터페이스
(check(entries) -> list[str])에 맞춰 반환한다.

posts/는 .gitignore 대상이라 entries(스테이징된 파일 목록)로는 이 검사를 걸 수 없다 —
그래서 entries와 무관하게 매번 실행한다.
"""
import subprocess
import sys
from pathlib import Path


def check(entries):
    checker = Path(__file__).resolve().parent.parent / "check_post_consistency.py"
    if not checker.exists():
        return []
    result = subprocess.run(
        [sys.executable, str(checker)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
    if result.returncode != 0:
        return ["posts/latest/post_content.json — 위 scripts/check_post_consistency.py 출력을 참고하세요."]
    return []
