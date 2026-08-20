#!/usr/bin/env python3
"""bodetail-vault pre-commit 검사 — 데이터 기반 디스패처.

검증 규칙은 여기 하드코딩하지 않는다. ontology/invariants.yaml을 읽어 순회하고,
각 항목의 id에 대응하는 scripts/checks/<id>.py 의 check(entries) 함수를 호출한다.

새 규칙 추가 = ontology/invariants.yaml에 항목 하나 + scripts/checks/에 함수 하나.
이 파일 자체는 더 이상 고칠 필요가 없다(디스패치 로직만 담당).

exit 0 = 커밋 진행, exit 1 = 커밋 차단.
"""
import importlib
import sys
from pathlib import Path

# Windows 콘솔 기본 코드페이지(cp949 등)로 한글 출력이 깨지는 것 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
INVARIANTS_FILE = REPO_ROOT / "ontology" / "invariants.yaml"
CHECKS_DIR = Path(__file__).resolve().parent / "checks"

try:
    import yaml
except ImportError:
    print("⚠ PyYAML이 설치되어 있지 않아 invariants.yaml 기반 검사를 건너뜁니다.")
    print("  'python -m pip install -r scripts/requirements.txt' 로 설치하세요.")
    sys.exit(0)

sys.path.insert(0, str(CHECKS_DIR))
import _common  # noqa: E402  (scripts/checks/_common.py)


def module_name_for(invariant_id):
    return invariant_id.lower().replace("-", "_")


def load_invariants():
    if not INVARIANTS_FILE.exists():
        print(f"⚠ {INVARIANTS_FILE} 없음 — 검사를 건너뜁니다.")
        return []
    data = yaml.safe_load(INVARIANTS_FILE.read_text(encoding="utf-8")) or {}
    return data.get("invariants", [])


def check_origins(invariants):
    """origin 필드가 비어있거나 '미상'으로 시작하면 경고(차단 아님).
    CLAUDE.md 규칙: 이유 없는 규칙은 나중에 아무도 못 지운다."""
    missing = []
    for inv in invariants:
        origin = (inv.get("origin") or "").strip()
        if not origin or origin.startswith("미상"):
            missing.append(inv.get("id", "?"))
    if missing:
        print("⚠ origin 근거가 없거나 '미상'으로 남은 규칙 (경고만, 커밋은 진행됩니다):")
        for mid in missing:
            print(f"  - {mid} — ontology/invariants.yaml에서 origin을 채워주세요.")


def run_invariant(inv):
    """하나의 invariant를 실행. 반환: (severity, problems: list[str])."""
    inv_id = inv.get("id", "?")
    module_name = module_name_for(inv_id)
    module_path = CHECKS_DIR / f"{module_name}.py"
    if not module_path.exists():
        print(f"⚠ {inv_id}: scripts/checks/{module_name}.py 없음 — 이 규칙은 검증되지 않고 있습니다.")
        return inv.get("severity", "warn"), []

    try:
        module = importlib.import_module(module_name)
        importlib.reload(module)  # 같은 이름 재사용 대비(테스트 반복 실행 시)
    except Exception as e:
        print(f"⚠ {inv_id}: scripts/checks/{module_name}.py 로드 실패({type(e).__name__}: {e}) — 건너뜁니다.")
        return inv.get("severity", "warn"), []

    entries = _common.staged_name_status()
    try:
        problems = module.check(entries)
    except Exception as e:
        print(f"⚠ {inv_id}: 검사 실행 중 오류({type(e).__name__}: {e}) — 건너뜁니다.")
        return inv.get("severity", "warn"), []

    return inv.get("severity", "warn"), (problems or [])


def main():
    invariants = load_invariants()
    if not invariants:
        sys.exit(0)

    check_origins(invariants)

    blocking = []   # [(id, description, problems)]
    warnings = []   # [(id, description, problems)]

    for inv in invariants:
        severity, problems = run_invariant(inv)
        if not problems:
            continue
        entry = (inv.get("id", "?"), inv.get("description", "").strip(), problems)
        if severity == "block":
            blocking.append(entry)
        else:
            warnings.append(entry)

    if warnings:
        print("\n⚠ 경고 (커밋은 계속 진행됩니다):")
        for inv_id, desc, problems in warnings:
            print(f"\n[{inv_id}] {desc}")
            for p in problems:
                print(f"  - {p}")

    if blocking:
        print("\n커밋이 차단되었습니다:")
        for inv_id, desc, problems in blocking:
            print(f"\n[{inv_id}] {desc}")
            for p in problems:
                print(f"  {p}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
