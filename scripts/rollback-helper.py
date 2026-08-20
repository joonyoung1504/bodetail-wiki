#!/usr/bin/env python3
"""scripts/rollback-helper.py — 최근 커밋이 어떤 노트를 건드렸는지, 그 노트에 걸린
관계(relations)와 함께 보여준다.

되돌리는 엔진을 새로 만들지 않는다 — git이 이미 잘한다. 이 스크립트는 **되돌릴 대상을
찾는 것**까지만 돕고, 실행할 `git revert` 명령을 화면에 출력한다.

**아무것도 자동으로 실행하지 않는다.** 출력된 명령을 사람이 읽고 직접 실행한다.

사용법:
    python scripts/rollback-helper.py                 # 최근 10개 커밋
    python scripts/rollback-helper.py -n 20            # 최근 20개 커밋
    python scripts/rollback-helper.py --commit <hash>  # 특정 커밋 하나만 상세히
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_BASE = ["git", "-c", "core.quotepath=false"]
NOTE_DIRS = ("product/", "brand/", "market/", "ops/", "decisions/",
             "content/", "marketing_auto/", "concepts/")


def run(cmd):
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    return result.stdout


def recent_commits(n):
    out = run(GIT_BASE + ["log", f"-{n}", "--pretty=format:%H%x1f%ad%x1f%s", "--date=short"])
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        h, date, subject = line.split("\x1f", 2)
        commits.append((h, date, subject))
    return commits


def files_in_commit(commit_hash):
    out = run(GIT_BASE + ["show", "--name-only", "--pretty=format:", commit_hash])
    return [f for f in out.splitlines() if f.strip()]


def is_note(path):
    return path.endswith(".md") and path.startswith(NOTE_DIRS)


def note_key(path):
    return path[:-3] if path.endswith(".md") else path


def load_relation_graph():
    """impact.py와 동일한 방식으로 relations 그래프를 만든다. PyYAML 없으면 빈 그래프."""
    if yaml is None:
        return {}, {}
    rel_types_file = REPO_ROOT / "ontology" / "relation_types.yaml"
    if not rel_types_file.exists():
        return {}, {}
    rel_types = {t["id"]: t for t in
                 (yaml.safe_load(rel_types_file.read_text(encoding="utf-8")) or {}).get("relation_types", [])}

    outgoing = {}
    incoming = {}
    for p in REPO_ROOT.rglob("*.md"):
        if ".git" in p.parts or ".obsidian" in p.parts:
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()[:-3]
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        for r in fm.get("relations", []) or []:
            typ, tgt = r.get("type"), r.get("target")
            if not typ or not tgt:
                continue
            outgoing.setdefault(rel, []).append((typ, tgt))
            incoming.setdefault(tgt, []).append((typ, rel))
            if rel_types.get(typ, {}).get("direction") == "bidirectional":
                outgoing.setdefault(tgt, []).append((typ, rel))
                incoming.setdefault(rel, []).append((typ, tgt))
    return outgoing, incoming


def describe_commit(h, date, subject, outgoing, incoming, show_revert=True):
    print(f"\n{h[:10]}  {date}  {subject}")
    files = files_in_commit(h)
    notes = [f for f in files if is_note(f)]
    others = [f for f in files if f not in notes]

    if notes:
        print("  건드린 노트:")
        for f in notes:
            key = note_key(f)
            rel_bits = []
            for typ, tgt in outgoing.get(key, []):
                rel_bits.append(f"{typ}→{tgt}")
            for typ, src in incoming.get(key, []):
                rel_bits.append(f"{typ}←{src}")
            rel_str = f"   [{', '.join(rel_bits)}]" if rel_bits else ""
            print(f"    - {f}{rel_str}")
    if others:
        print(f"  기타 파일: {len(others)}개 ({', '.join(others[:5])}{' ...' if len(others) > 5 else ''})")
    if not files:
        print("  (변경 파일 없음 — 병합 커밋일 수 있음)")

    if show_revert:
        print(f"  되돌리려면: git revert {h}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", type=int, default=10, help="최근 몇 개 커밋을 볼지 (기본 10)")
    parser.add_argument("--commit", help="특정 커밋 해시 하나만 상세히 본다")
    args = parser.parse_args()

    outgoing, incoming = load_relation_graph()
    if yaml is None:
        print("⚠ PyYAML이 없어 관계(relations) 정보 없이 파일 목록만 보여줍니다.\n")

    if args.commit:
        out = run(GIT_BASE + ["log", "-1", "--pretty=format:%H%x1f%ad%x1f%s", "--date=short", args.commit])
        if not out.strip():
            print(f"커밋 '{args.commit}'을 찾을 수 없습니다.")
            sys.exit(1)
        h, date, subject = out.split("\x1f", 2)
        describe_commit(h, date, subject, outgoing, incoming)
        return

    commits = recent_commits(args.n)
    print(f"최근 {len(commits)}개 커밋 (건드린 위키 노트 + 걸린 관계):")
    for h, date, subject in commits:
        describe_commit(h, date, subject, outgoing, incoming)

    print("\n---")
    print("여러 커밋을 한 번에 되돌리려면: git revert <old-hash>..<new-hash>")
    print("(범위 지정 시 최신 커밋부터 역순으로 되돌아감 — 충돌 가능성은 git이 알려줍니다)")
    print("이 스크립트는 명령만 알려줄 뿐 아무것도 실행하지 않습니다.")


if __name__ == "__main__":
    main()
