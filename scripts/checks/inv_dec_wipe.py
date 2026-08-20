"""INV-DEC-WIPE: decisions/ 파일 내용이 deprecated 태그 없이 80% 이상 삭제되면 차단."""
import _common as c

WIPE_RATIO_THRESHOLD = 0.2  # 원본 대비 이 비율 이하로 줄면 "통째로 지워짐"으로 간주
MIN_HEAD_LINES_FOR_WIPE_CHECK = 10  # 너무 짧은 파일은 잡음이 많아 검사 제외


def check(entries):
    problems = []
    for status, old, new in entries:
        if not status.startswith("M"):
            continue
        target = new or old
        if not (target.startswith("decisions/") and target.endswith(".md")):
            continue
        head = c.get_head_content(target)
        staged = c.get_staged_content(target)
        if head is None or staged is None:
            continue
        head_lines = len(head.splitlines())
        staged_lines = len(staged.splitlines())
        if head_lines < MIN_HEAD_LINES_FOR_WIPE_CHECK:
            continue
        ratio = staged_lines / head_lines if head_lines else 1.0
        if ratio <= WIPE_RATIO_THRESHOLD and not c.has_deprecated_tag(staged):
            problems.append(
                f"{target}\n"
                f"    {head_lines}줄 → {staged_lines}줄로 {int((1 - ratio) * 100)}% 삭제됐는데\n"
                f"    deprecated 태그가 없습니다. 의도된 폐기라면 frontmatter tags에\n"
                f"    deprecated를 추가하세요."
            )
    return problems
