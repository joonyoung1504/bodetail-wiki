#!/bin/sh
# bodetail-vault git hooks 설치 스크립트.
#
# .git/hooks/ 는 git이 버전관리하지 않아 clone해도 따라오지 않는다.
# 새 PC에서 저장소를 clone한 뒤 이 스크립트를 한 번 실행하면
# scripts/pre-commit (버전관리됨)이 .git/hooks/pre-commit 으로 설치된다.
#
# 사용법 (저장소 어디서든): bash scripts/install-hooks.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/scripts/pre-commit"
DEST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
    echo "오류: $SRC 를 찾을 수 없습니다." >&2
    exit 1
fi

mkdir -p "$REPO_ROOT/.git/hooks"
cp "$SRC" "$DEST"
chmod +x "$DEST"

echo "pre-commit 훅 설치 완료 → $DEST"
echo "검사 로직: scripts/pre-commit-check.py (이 파일을 고치면 재설치 없이 바로 반영됩니다)"

if ! python3 -c "import yaml" 2>/dev/null && ! python -c "import yaml" 2>/dev/null; then
    echo ""
    echo "⚠ PyYAML이 안 보입니다. ontology/invariants.yaml 기반 검사가 동작하려면:"
    echo "    python -m pip install -r scripts/requirements.txt"
    echo "  (없어도 훅 자체는 죽지 않고 경고만 띄우고 통과시킵니다 — fail-open)"
fi
