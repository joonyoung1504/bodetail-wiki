#!/usr/bin/env python3
"""scripts/impact.py — 노트 하나가 바뀌면 검토가 필요한 노트 목록을 보여준다.

**아무것도 자동으로 고치지 않는다.** 목록만 출력하는 조회 도구다.
연쇄 수정은 반드시 사람 승인을 거쳐야 한다 — WIKI-RULES.md §9 /propagate 절차 참조.

사용법:
    python scripts/impact.py "decisions/주요-의사결정"
    python scripts/impact.py "MA_05"              # 부분 일치도 허용
    python scripts/impact.py "MA_05" --depth 1     # 전파 깊이 제한 (기본 3)

동작 원리 (2026-08-21 개정 — 양방향 조회):
  1. 저장소의 모든 .md 파일 frontmatter에서 relations: 필드를 읽어 두 그래프를 만든다.
       incoming[X] = X를 target으로 가리키는 (source, type) 목록
       outgoing[X] = X가 source로 가리키는 (type, target) 목록
     (direction: bidirectional 타입은 incoming 쪽에 양방향으로 합성해 심는다.)
  2. 조회한 노트가 "target"인 관계(incoming)와 "source"인 관계(outgoing)를 둘 다 본다
     — 단, 관계 타입의 query_direction이 그 방향을 지원할 때만. 예를 들어 may_invalidate는
     both라서 두 방향 다 보여주지만, supersedes는 incoming만 유의미해서 outgoing 방향
     조회에서는 안 보여준다(ontology/relation_types.yaml 참조).
  3. depth 1은 항상 전부 보여준다. depth 2 이상은 propagates: true 인 관계 타입을 통해
     서만, 그리고 depth 1에서 쓰인 것과 같은 방향으로만 더 전파한다(무한 확산 방지).
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
    """저장소의 모든 .md 파일 + raw/의 비-.md 원본(.txt/.html)을
    {노트명(확장자 없는 상대경로): Path} 로 반환.

    raw/에는 정리된 .md뿐 아니라 정리 전 원본(.txt/.html)도 있고, derived_from
    관계가 이런 원본을 target으로 가리키는 게 정상이다(예: raw/src_laonhase_mail.txt).
    .md만 스캔하면 relations: 에는 정확히 기록되는데 이 도구로는 그 노드를 조회할
    방법이 없어지는 버그가 있었다(2026-08-21 raw/ 관계 제안 테스트 중 발견).
    """
    notes = {}
    patterns = ["*.md", "raw/*.txt", "raw/*.html", "raw/*.htm"]
    for pattern in patterns:
        for p in REPO_ROOT.rglob(pattern):
            if any(part in IGNORE_DIRS for part in p.parts):
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            rel = rel[: -len(p.suffix)]  # 확장자 제거 (.md/.txt/.html/.htm)
            notes[rel] = p
    return notes


def build_graphs(notes, rel_types):
    """반환: (incoming, outgoing, unknown_types)
    incoming[X] = [(source, type), ...]  — X를 target으로 가리키는 관계 (양방향 타입 합성 포함)
    outgoing[X] = [(type, target), ...]  — X가 source로 가리키는 관계 (선언된 그대로 + 양방향 합성)
    unknown_types = [(note, type), ...]  — relation_types.yaml에 없는 타입을 쓴 곳
    """
    incoming = {}
    outgoing = {}
    unknown = []

    def add_incoming(tgt, typ, src):
        incoming.setdefault(tgt, []).append((src, typ))

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

            add_incoming(tgt, typ, name)
            outgoing.setdefault(name, []).append((typ, tgt))

            if rt and rt.get("direction") == "bidirectional":
                add_incoming(name, typ, tgt)
                outgoing.setdefault(tgt, []).append((typ, name))

    return incoming, outgoing, unknown


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


def analyze(start, incoming, outgoing, rel_types, max_depth):
    """반환: [(depth, note, type, via, direction)] 리스트.
    direction="incoming" → note가 via(=target)를 향해 --type--> 관계를 가짐 (note=source)
    direction="outgoing" → via(=source)가 note(=target)를 향해 --type--> 관계를 가짐
    """
    results = []
    visited = {start}
    frontier = [(start, "incoming"), (start, "outgoing")]
    depth = 1
    while frontier and depth <= max_depth:
        next_frontier = []
        for node, direction in frontier:
            candidates = incoming.get(node, []) if direction == "incoming" else \
                [(tgt, typ) for typ, tgt in outgoing.get(node, [])]
            for other, typ in candidates:
                rt = rel_types.get(typ, {})
                allowed = rt.get("query_direction", "incoming")
                if allowed not in (direction, "both"):
                    continue
                if other in visited:
                    continue
                visited.add(other)
                results.append((depth, other, typ, node, direction))
                if rt.get("propagates"):
                    next_frontier.append((other, direction))
        frontier = next_frontier
        depth += 1
    return results


def format_on_change(rt, direction):
    field = "on_change_incoming" if direction == "incoming" else "on_change_outgoing"
    text = (rt.get(field) or "").strip()
    if not text:
        return ""
    one_line = " ".join(text.split())
    if len(one_line) > 140:
        one_line = one_line[:140].rsplit(" ", 1)[0] + " …"
    return one_line


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("note", help="영향 분석할 노트 이름(전체 경로 또는 부분 문자열)")
    parser.add_argument("--depth", type=int, default=3, help="전파 최대 깊이 (기본 3)")
    args = parser.parse_args()

    rel_types = load_relation_types()
    notes = all_notes()
    start = resolve_note_name(args.note, notes)

    incoming, outgoing, unknown = build_graphs(notes, rel_types)

    if unknown:
        print("⚠ ontology/relation_types.yaml에 정의되지 않은 relation type 사용 (경고만, 계속 진행):")
        for note, typ in unknown:
            print(f"  - {note}: type={typ!r} — 오타이거나 relation_types.yaml에 추가가 필요합니다.")
        print()

    results = analyze(start, incoming, outgoing, rel_types, args.depth)

    print(f"'{start}'가 바뀌면 검토가 필요한 노트\n")

    if not results:
        print("  (relations: 로 이 노트를 가리키거나, 이 노트가 가리키는 노트가 없습니다")
        print("   — 영향 없음, 또는 관계가 아직 기록 안 됨)")
        return

    by_depth = {}
    for depth, note, typ, via, direction in results:
        by_depth.setdefault(depth, []).append((note, typ, via, direction))

    for depth in sorted(by_depth):
        print(f"[depth {depth}]")
        for note, typ, via, direction in by_depth[depth]:
            rt = rel_types.get(typ, {})
            relation_line = f"{note} --{typ}--> {via}" if direction == "incoming" else f"{via} --{typ}--> {note}"
            print(f"  {note}   [{direction}]")
            print(f"    {relation_line}")
            on_change = format_on_change(rt, direction)
            if on_change:
                print(f"    조치: {on_change}")
        print()

    total = len(results)
    print(f"총 {total}개 노트가 영향권 (depth 1~{max(by_depth)}).")
    print("이 목록은 조회 결과일 뿐입니다 — 수정은 WIKI-RULES.md §9 /propagate 절차로 승인받은 뒤에만 하세요.")


if __name__ == "__main__":
    main()
