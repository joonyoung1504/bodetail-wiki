#!/usr/bin/env python3
"""posts/latest/post_content.json의 표지 headline이 잠금값(_locked_headline)과
일치하는지 검사한다.

배경: generate_daily_post.py는 생성 시점에 cover.headline_main을
topics_30.json의 title_main으로 코드 레벨에서 강제 고정하고(A안), 그 원본값을
post_content.json에 _locked_headline으로 같이 기록해둔다. 정상적으로 생성된
파일이라면 이 두 값은 항상 같다.

이 스크립트가 진짜로 잡아내는 건 "생성 이후"의 변조다 — 예를 들어
tools/bodetail_editor.html로 사람이 표지 문구를 손으로 고쳐서 다시 내보낸 경우,
_locked_headline은 그대로인데 headline_main만 바뀌어 불일치가 생긴다.

posts/ 는 .gitignore 대상이라 git 스테이징 여부로는 검사 시점을 판단할 수 없다.
그래서 git 상태와 무관하게 매 커밋마다 작업 디렉터리의 파일을 직접 읽어 검사한다.
posts/latest/post_content.json이 없으면(또는 이 필드가 없는 구버전 파일이면)
검사 대상이 없는 것으로 보고 통과시킨다.

exit 0 = 통과(또는 검사 대상 없음), exit 1 = 불일치(차단).
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
POST_JSON = REPO_ROOT / "posts" / "latest" / "post_content.json"


def main():
    if not POST_JSON.exists():
        print("ℹ posts/latest/post_content.json 없음 — 표지 headline 검사 생략")
        return 0

    try:
        post = json.loads(POST_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠ posts/latest/post_content.json 파싱 실패({e}) — 검사 생략")
        return 0

    if "_locked_headline" not in post:
        print("ℹ _locked_headline 필드 없음(구버전 게시물) — 검사 생략")
        return 0

    expected = post["_locked_headline"]
    cover = next((s for s in post.get("slides", []) if s.get("type") == "cover"), None)
    actual = cover.get("headline_main") if cover else None

    if cover is None or actual != expected:
        print("❌ 표지 headline 불일치 — posts/latest/post_content.json")
        print(f"   잠금값(_locked_headline): {expected!r}")
        print(f"   실제(headline_main):      {actual!r}")
        print("   generate_daily_post.py로 재생성하거나, 에디터에서 표지 문구를")
        print("   잠금값과 동일하게 되돌린 뒤 다시 시도하세요.")
        return 1

    print(f"✅ 표지 headline 일치 확인: {expected!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
