# -*- coding: utf-8 -*-
"""
bodetail 주간 성과 학습기
─ 최근 인사이트 + 최근 게시물 내용 + 기존 학습 규칙 → Claude 분석 → learnings.md 갱신 ─

작동 원리 (딥러닝이 아니라 '규칙 증류' 루프):
  1. 데이터 수집: content/insights/*.json (반응) + posts/*/post_content.json (내용)
  2. Claude가 "무엇이 저장·도달을 만들었는가"를 분석해
  3. content/learnings.md 를 통째로 재작성 (유지할 규칙 / 새 규칙 / 폐기 규칙)
  4. 다음날부터 generate_daily_post.py 가 이 파일을 프롬프트에 주입
  → 매주 조금씩 훅·주제·CTA·구성이 데이터 방향으로 이동

입력(있는 것만 사용, 없어도 동작):
  content/insights/insights_*.json   ← fetch_ig_insights.py 산출물
  content/insights/manual_notes.md   ← 수동 관찰 노트 (토큰 없을 때 대안)
  posts/*/post_content.json          ← 최근 게시물 내용
  content/learnings.md               ← 기존 규칙
"""
import os, re, json, glob, datetime
from pathlib import Path

import anthropic

KST = datetime.timezone(datetime.timedelta(hours=9))
DATE = datetime.datetime.now(KST).strftime("%Y-%m-%d")
LEARN_PATH = Path("content/learnings.md")


def load_recent_insights(n=2):
    files = sorted(glob.glob("content/insights/insights_*.json"))[-n:]
    out = []
    for f in files:
        try:
            out.append(json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def load_recent_posts(n=10):
    """최근 게시물 폴더의 post_content.json에서 핵심만 추출."""
    dirs = sorted([d for d in glob.glob("posts/2*") if Path(d).is_dir()])[-n:]
    out = []
    for d in dirs:
        p = Path(d) / "post_content.json"
        if not p.exists():
            continue
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            cover = next((s for s in c.get("slides", []) if s.get("type") == "cover"), {})
            out.append({
                "folder": Path(d).name,
                "section": c.get("section_label", ""),
                "cover_main": " ".join(cover.get("headline_main", [])),
                "cover_sub": cover.get("headline_sub", ""),
                "caption_head": (c.get("caption_full") or "")[:100],
                "num_slides": len(c.get("slides", [])),
            })
        except Exception:
            pass
    return out


def main():
    insights = load_recent_insights()
    posts = load_recent_posts()
    manual = Path("content/insights/manual_notes.md")
    manual_txt = manual.read_text(encoding="utf-8") if manual.exists() else ""
    current = LEARN_PATH.read_text(encoding="utf-8") if LEARN_PATH.exists() else "(아직 규칙 없음 — 첫 학습)"

    if not insights and not manual_txt and not posts:
        print("ℹ️ 학습할 데이터가 아직 없음 — 종료")
        return

    prompt = f"""너는 bodetail(@bodetail_official, 남성 그루밍 무드 매거진)의 콘텐츠 성과 분석가야.
아래 데이터를 분석해서 콘텐츠 제작 규칙 파일(learnings.md)을 **통째로 재작성**해줘.

[분석 원칙]
- 핵심 지표 우선순위: 저장(saved) > 도달(reach) > 공유(shares) > 좋아요. 저장이 알고리즘 추천의 연료다.
- 게시물 내용(훅 문구·섹션·슬라이드 수·캡션 구조)과 반응 수치를 연결해서 "왜"를 추론해.
- 데이터가 부족한 부분은 규칙을 만들지 말고 "검증 중" 항목으로 남겨.
- 기존 규칙 중 데이터와 모순되는 것은 폐기하고, 검증된 것은 유지·강화해.

[출력 형식 — 이 마크다운 구조 그대로, 2500자 이내]
# bodetail 성과 학습 규칙 (갱신: {DATE})
## 🎯 검증된 규칙 (반드시 반영)
- (훅/제목 규칙 …)
- (주제/섹션 규칙 …)
- (구성/슬라이드 규칙 …)
- (캡션/CTA 규칙 …)
## 🧪 검증 중 (다음 주 관찰)
- …
## 🗑️ 폐기 (데이터와 모순)
- …

[기존 규칙]
{current[:2000]}

[최근 게시물 내용 요약]
{json.dumps(posts, ensure_ascii=False, indent=1)[:3000]}

[반응 데이터 (Graph API)]
{json.dumps(insights, ensure_ascii=False)[:4000] if insights else "(수집된 API 데이터 없음)"}

[운영자 수동 관찰 노트]
{manual_txt[:1500] if manual_txt else "(없음)"}

learnings.md 내용만 출력해. 다른 텍스트·코드펜스 금지."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=2500,
                                 messages=[{"role": "user", "content": prompt}])
    new_md = msg.content[0].text.strip()
    new_md = re.sub(r'^```(?:markdown)?\s*', '', new_md)
    new_md = re.sub(r'\s*```$', '', new_md)

    if len(new_md) < 100 or not new_md.startswith("#"):
        print("⚠️ 응답 형식 이상 — 기존 규칙 유지")
        return

    # 이전 버전 아카이브 후 교체
    if LEARN_PATH.exists():
        arch = Path("content/learnings_archive")
        arch.mkdir(parents=True, exist_ok=True)
        (arch / f"learnings_{DATE}.md").write_text(current, encoding="utf-8")
    LEARN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARN_PATH.write_text(new_md + "\n", encoding="utf-8")
    print(f"🧠 학습 완료 → {LEARN_PATH} 갱신 ({len(new_md)}자)")
    print("   내일 게시물 생성부터 자동 반영됨")


if __name__ == "__main__":
    main()
