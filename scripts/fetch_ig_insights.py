# -*- coding: utf-8 -*-
"""
bodetail 인스타그램 인사이트 수집기
─ 공식 Instagram Graph API로 최근 게시물 반응 데이터를 수집해 저장 ─

⚠️ 계정 비밀번호 로그인 방식의 스크래핑은 사용하지 않는다.
   (메타 약관 위반 + 계정 정지 위험 — 브랜드 계정에는 치명적)
   Graph API가 메타가 공식 허용하는 유일한 자동화 루트다.

필요 GitHub Secrets:
  IG_ACCESS_TOKEN : 장기 액세스 토큰 (instagram_basic + instagram_manage_insights)
  IG_USER_ID      : 인스타그램 비즈니스 계정 ID (숫자)

출력: content/insights/insights_{날짜}.json
      (media별: 캡션 앞부분, 타입, 게시시각, 좋아요, 댓글, 도달, 저장, 공유, 조회)
"""
import os, sys, json, datetime
from pathlib import Path
import requests

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_ID = os.environ.get("IG_USER_ID", "").strip()
API   = "https://graph.facebook.com/v21.0"
OUT_DIR = Path("content/insights")

if not TOKEN or not IG_ID:
    print("ℹ️ IG_ACCESS_TOKEN / IG_USER_ID 시크릿이 없어 수집 건너뜀 (수동 노트만으로 학습 진행 가능)")
    sys.exit(0)


def api_get(path, **params):
    params["access_token"] = TOKEN
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"API {path} 실패 {r.status_code}: {r.text[:300]}")
    return r.json()


def media_insights(media_id, product_type):
    """게시물별 인사이트. 릴스/피드에 따라 지표가 달라서 하나씩 관대하게 시도."""
    metrics = (["views", "reach", "saved", "shares", "likes", "comments", "total_interactions"]
               if product_type == "REELS" else
               ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions"])
    result = {}
    for m in metrics:
        try:
            d = api_get(f"{media_id}/insights", metric=m)
            for item in d.get("data", []):
                vals = item.get("values", [{}])
                result[item["name"]] = vals[0].get("value", 0) if vals else 0
        except Exception:
            pass  # 지원 안 되는 지표는 조용히 스킵 (API 버전에 따라 다름)
    return result


def main():
    print("📊 인스타 인사이트 수집 시작")
    media = api_get(f"{IG_ID}/media",
                    fields="id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink",
                    limit=25)
    rows = []
    for m in media.get("data", []):
        cap = (m.get("caption") or "").strip().replace("\n", " ")
        row = {
            "id": m["id"],
            "posted_at": m.get("timestamp", ""),
            "type": m.get("media_product_type") or m.get("media_type", ""),
            "caption_head": cap[:80],
            "likes": m.get("like_count", 0),
            "comments": m.get("comments_count", 0),
            "permalink": m.get("permalink", ""),
        }
        row.update(media_insights(m["id"], row["type"]))
        rows.append(row)
        print(f"  ✅ {row['posted_at'][:10]} | {row['type']:<6} | 좋아요 {row['likes']} · 저장 {row.get('saved','-')} · 도달 {row.get('reach','-')} | {row['caption_head'][:30]}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    out = OUT_DIR / f"insights_{date}.json"
    out.write_text(json.dumps({"collected_at": date, "media": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 저장 → {out} ({len(rows)}개 게시물)")


if __name__ == "__main__":
    main()
