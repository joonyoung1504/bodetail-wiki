"""INV-OPS-BULK: 커밋에 50개 이상 파일이 포함되면 CLAUDE.md 예외조항 확인 y/n을 받는다.

다른 검사와 달리 이 검사는 통과 여부를 파일 목록이 아니라 사용자 응답으로 결정한다.
비대화형 환경(입력을 받을 수 없음)에서는 안전하게 차단한다(fail-safe).
"""
BULK_CHANGE_THRESHOLD = 50


def check(entries):
    count = len(entries)
    if count < BULK_CHANGE_THRESHOLD:
        return []

    print(f"\n⚠ 대량 변경 감지: 이번 커밋에 {count}개 파일이 포함됩니다.")
    print("  CLAUDE.md '자동 실행의 예외' 조항(50개 이상 파일 변경 시 확인 후 진행)에 해당합니다.")
    try:
        answer = input("  CLAUDE.md 예외조항을 확인했고 계속 진행합니까? [y/N] ")
    except EOFError:
        return [
            f"커밋에 {count}개 파일 포함 — 비대화형 환경이라 확인을 받을 수 없어 차단합니다.\n"
            f"    확인했다면 'git commit --no-verify'로 우회하거나 터미널에서 다시 시도하세요."
        ]

    if answer.strip().lower() == "y":
        return []
    return [f"커밋에 {count}개 파일 포함 — 사용자가 진행을 취소했습니다."]
