"""INV-DEC-DELETE: decisions/ 폴더 파일은 삭제·이동으로 없앨 수 없다."""
import _common as c


def check(entries):
    problems = []
    for status, old, new in entries:
        if status.startswith("D"):
            if old.startswith("decisions/") and old.endswith(".md"):
                problems.append(
                    f"{old}\n"
                    f"    decisions/ 폴더 파일은 삭제할 수 없습니다 (WIKI-RULES.md '지우지 않는다' 원칙).\n"
                    f"    내용을 폐기하려면 삭제 대신 frontmatter tags에 deprecated를 추가하고\n"
                    f"    '→ 진짜 노트는 여기' 리다이렉트 스텁으로 남기세요."
                )
        elif status.startswith("R"):
            still_in_decisions = bool(new) and new.startswith("decisions/")
            if old.startswith("decisions/") and old.endswith(".md") and not still_in_decisions:
                problems.append(
                    f"{old} → {new}\n"
                    f"    decisions/ 밖으로의 이동은 삭제와 동일하게 취급됩니다."
                )
    return problems
