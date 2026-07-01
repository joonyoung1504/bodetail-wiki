"""
rerender_category_a.py — 이미지/자막만 수정 후 빠른 재렌더
=====================================================
generate_category_a.py가 저장해둔 reels/latest_a/assets/(clip.mp4, bgm_used.mp3,
images/*.jpg) 와 reels/latest_a/direction_edit.json(에디터에서 수정된 값)을 읽어
ffmpeg만으로 reel_final.mp4를 다시 만든다.

유튜브 재다운로드도, AssemblyAI/Claude API 호출도 없음 — 그래서 빠르고 무료.
bodetail_editor.html의 "카테고리 A 릴스" 탭에서:
  1) direction_edit.json 열기
  2) (선택) 이미지 교체 → "이미지 전체 저장"으로 다운로드 → GitHub에 재업로드(같은 파일명으로 덮어쓰기)
  3) 수정된 direction_edit.json 내보내기 → GitHub에 재업로드
  4) 이 스크립트를 실행하는 워크플로("카테고리 A 재렌더") 실행
"""

import json
from pathlib import Path

import generate_category_a as gen

LATEST  = gen.LATEST
ASSETS  = LATEST/"assets"
IMGDIR  = ASSETS/"images"
TMP     = Path("/tmp/rerender_a")

def main():
    edit_path = LATEST/"direction_edit.json"
    if not edit_path.exists():
        raise RuntimeError(f"{edit_path} 없음 — 먼저 카테고리 A 릴스를 한 번 생성해야 함")
    d = json.loads(edit_path.read_text(encoding="utf-8"))

    clip = ASSETS/"clip.mp4"
    bgm  = ASSETS/"bgm_used.mp3"
    if not clip.exists():
        raise RuntimeError(f"{clip} 없음 — assets/clip.mp4가 커밋되어 있는지 확인")

    dur      = float(d.get("reel_duration", 20.0))
    drop_t   = float(d.get("drop_at_rel", dur))
    bgm_start= float(d.get("bgm_start", 0.0))
    montage  = bool(d.get("montage", False))
    cuts     = d.get("cuts", [])
    emphasis = d.get("emphasis_words", [])
    words    = d.get("words", [])   # 이미 clip 기준 상대(초) — clip_start=0으로 취급
    img_names= d.get("images", [])
    bgm_present = bool(d.get("bgm_present", False)) and bgm.exists()

    images = [str(IMGDIR/name) for name in img_names if (IMGDIR/name).exists()]
    missing = [name for name in img_names if not (IMGDIR/name).exists()]
    if missing:
        print(f"  ⚠️ 이미지 {len(missing)}장 못 찾음(건너뜀): {missing}")

    TMP.mkdir(parents=True, exist_ok=True)
    for old in TMP.glob("*"):
        pass  # 하위 파일은 각 build 함수가 덮어씀

    print(f"🎬 재렌더 시작 | 길이 {dur:.1f}s | 드롭 {drop_t:.1f}s | 몽타주 {'ON' if montage else 'OFF'} | 이미지 {len(images)}장")

    # AssemblyAI 형식(ms, 절대) 대신 words_to_relative가 기대하는 형식으로 맞춰
    # build_ass에 바로 넣을 수 있도록 clip_start=0, 단위를 ms로 되돌려 전달
    words_ms = [{"start": w["t"]*1000, "end": w["e"]*1000, "text": w["w"]} for w in words]

    ass = gen.build_ass(words_ms, 0.0, dur, emphasis, TMP/"subs.ass")
    pA  = gen.make_vertical(clip, TMP/"partA.mp4", 0, drop_t)

    if montage and images and len(cuts) >= 2:
        pB = gen.build_montage(images, cuts, TMP/"partB.mp4", TMP/"segs")
        vo = gen.concat_videos([pA, pB], TMP/"video_only.mp4")
    else:
        vo = pA

    out = LATEST/"reel_final.mp4"
    gen.finalize(vo, clip, (bgm if bgm_present else None), ass, out,
                 min(drop_t, dur), dur, bgm_start)
    print(f"✅ 재렌더 완료 → {out} ({out.stat().st_size/1024/1024:.1f}MB)")

if __name__ == "__main__":
    main()
