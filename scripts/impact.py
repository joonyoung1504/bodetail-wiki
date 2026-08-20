#!/usr/bin/env python3
"""scripts/impact.py — 노트 하나가 바뀌면 검토가 필요한 노트 목록을 보여준다.

**아무것도 자동으로 고치지 않는다.** 목록만 출력하는 조회 도구다.
연쇄 수정은 반드시 사람 승인을 거쳐야 한다 — WIKI-RULES.md §9 /propagate 절차 참조.

사용법:
    python scripts/impact.py "decisions/주요-의사결정"
    python scripts/impact.py "MA_05"              # 부분 일치도 허용
    python scripts/impact.py "MA_05" --depth 1     # 전파 깊이 제한 (기본 3)

동작 원리:
  1. 저장소의 모든 .md 파일 frontmatter에서 relations: 필드를 읽어 관계 그래프를 만든다.
     (A가 relations: [{type: X, target: B}] 를 가지면 A --X--> B 간선.)
  2. "노트가 바뀌면 영향받는 것"은 그 노트를 target으로 가리키는 노트들(역방향 간선)이다.
  3. depth 1은 항상 전부 보여준다. depth 2 이상은 ontology/relation_types.yaml의
     propagates: true 인 관계 타입을 통해서만 더 전파한다(무한 확산 방지).
  4. complements처럼 direction: bidirectional인 타입은 양방향 간선으로 취급한다.
"""
import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("⚠ PyYAML이 필요합니다: python -m pip install -r scripts/requirements.txt")
    sys.exit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
RELATION_TYPES_FILE = REPO_ROOT / "ontology" / "relation_types.yaml"
IGNORE_DIRS = {".git", ".obsidian", "__pycache__", "node_modules"}


def load_relation_types():
    data = yaml.safe_load(RELATION_TYPES_FILE.read_text(encoding="utf-8")) or {}
    return {t["id"]: t for t in data.get("relation_types", [])}


def frontmatter(text):
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None


def all_notes():
    """저장소의 모든 .md 파일을 {노트명(확장자 없는 상대경로): Path} 로 반환."""
    notes = {}
    for p in REPO_ROOT.rglob("*.md"):
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()[:-3]  # .md 제거
        notes[rel] = p
    return notes


def build_graph(notes, rel_types):
    """반환: edges[target] = [(source, type), ...]  (target을 향한 역방향 간선 모음)"""
    edges = {}
    unknown = []  # [(note, type)] — relation_types.yaml에 없는 타입을 쓴 곳

    def add(src, typ, tgt):
        edges.setdefault(tgt, []).append((src, typ))

    for name, path in notes.items():
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if not fm:
            continue
        for rel in fm.get("relations", []) or []:
            typ = rel.get("type")
            tgt = rel.get("target")
            if not typ or not tgt:
                continue
            rt = rel_types.get(typ)
            if rt is None:
                unknown.append((name, typ))
            add(name, typ, tgt)
            if rt and rt.get("direction") == "bidirectional":
                add(tgt, typ, name)

    if unknown:
        print("⚠ ontology/relation_types.yaml에 정의되지 않은 relation type 사용 (경고만, 계속 진행):")
        for note, typ in unknown:
            print(f"  - {note}: type={typ!r} — 오타이거나 relation_types.yaml에 추가가 필요합니다.")
        print()

    return edges


def resolve_note_name(query, notes):
    if query in notes:
        return query
    q = query.lower()
    matches = [n for n in notes if q in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"'{query}'가 여러 노트와 일치합니다 — 더 구체적으로 지정하세요:")
        for m in sorted(matches):
            print(f"  - {m}")
        sys.exit(1)
    print(f"'{query}'와 일치하는 노트를 찾을 수 없습니다.")
    sys.exit(1)


def analyze(start, edges, rel_types, max_depth):
    """반환: [(depth, source, type, target)] 리스트. target은 이 사슬을 유발한 상위 노트."""
    results = []
    visited = {start}
    frontier = [start]
    depth = 1
    while frontier and depth <= max_depth:
        next_frontier = []
        for node in frontier:
            for source, typ in edges.get(node, []):
                if source in visited:
                    continue
                visited.add(source)
                results.append((depth, source, typ, node))
                rt = rel_types.get(typ, {})
                if rt.get("propagates"):
                    next_frontier.append(source)
        frontier = next_frontier
        depth += 1
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("note", help="영향 분석할 노트 이름(전체 경로 또는 부분 문자열)")
    parser.add_argument("--depth", type=int, default=3, help="전파 최대 깊이 (기본 3)")
    args = parser.parse_args()

    rel_types = load_relation_types()
    notes = all_notes()
    start = resolve_note_name(args.note, notes)

    edges = build_graph(notes, rel_types)
    results = analyze(start, edges, rel_types, args.depth)

    print(f"'{start}'가 바뀌면 검토가 필요한 노트\n")

    if not results:
        print("  (relations: 로 이 노트를 가리키는 노트가 없습니다 — 영향 없음, 또는 관계가 아직 기록 안 됨)")
        return

    by_depth = {}
    for depth, source, typ, via in results:
        by_depth.setdefault(depth, []).append((source, typ, via))

    for depth in sorted(by_depth):
        print(f"[depth {depth}]")
        for source, typ, via in by_depth[depth]:
            rt = rel_types.get(typ, {})
            on_change = (rt.get("on_change") or "").strip()
            arrow_target = via if depth == 1 else f"{via} (전파 경유)"
            print(f"  {source}")
            print(f"    --{typ}--> {arrow_target}")
            if on_change:
                one_line = " ".join(on_change.split())
                if len(one_line) > 110:
                    one_line = one_line[:110].rsplit(" ", 1)[0] + " …"
                print(f"    조치: {one_line}")
        print()

    total = len(results)
    print(f"총 {total}개 노트가 영향권 (depth 1~{max(by_depth)}).")
    print("이 목록은 조회 결과일 뿐입니다 — 수정은 WIKI-RULES.md §9 /propagate 절차로 승인받은 뒤에만 하세요.")


if __name__ == "__main__":
    main()
