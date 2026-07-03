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

    # 구버전 direction_edit.json 호환 (필드 없으면 합리적 기본값으로 추론)
    footage_dur = float(d.get("footage_duration", d.get("reel_duration", 20.0)))
    total_dur   = float(d.get("reel_duration", footage_dur))
    effect_t    = float(d.get("effect_t", d.get("drop_at_rel", footage_dur)))
    effect_type = d.get("effect_type", "montage" if d.get("montage") else "bw")
    outro_sec   = float(d.get("outro_sec", 2.5))
    bgm_start   = float(d.get("bgm_start", 0.0))
    bgm_climax  = d.get("bgm_climax", None)
    bgm_climax  = float(bgm_climax) if bgm_climax is not None else None
    sub_y       = float(d.get("sub_y", 50))
    broll_mode  = d.get("broll_mode", "montage")
    cutaway_sec = float(d.get("cutaway_sec", 1.6))
    cutaway_style = d.get("cutaway_style", "image")
    intro_black = float(d.get("intro_black_sec", 0))
    sub_mode    = d.get("sub_mode", "word")
    sub_scale   = float(d.get("sub_scale", 1.0))
    montage     = bool(d.get("montage", False)) and effect_type=="montage"
    cuts        = d.get("cuts", [])
    emphasis    = d.get("emphasis_words", [])
    words       = d.get("words", [])   # 이미 clip 기준 상대(초) — clip_start=0으로 취급
    img_names   = d.get("images", [])
    bgm_present = bool(d.get("bgm_present", False)) and bgm.exists()
    voice_present = bool(d.get("voice_present", gen.has_audio(clip)))
    swell         = bool(d.get("swell", d.get("punchy", bgm_present)))

    images = [str(IMGDIR/name) for name in img_names if (IMGDIR/name).exists()]
    missing = [name for name in img_names if not (IMGDIR/name).exists()]
    if missing:
        print(f"  ⚠️ 이미지 {len(missing)}장 못 찾음(건너뜀): {missing}")

    TMP.mkdir(parents=True, exist_ok=True)

    print(f"🎬 재렌더 시작 | 원본길이 {footage_dur:.1f}s | 총길이 {total_dur:.1f}s | "
          f"효과시점 {effect_t:.1f}s | 효과 {effect_type} | 음성트랙 {'있음' if voice_present else '없음'} | "
          f"이미지 {len(images)}장 | 자막 y={sub_y:.0f}%")

    # AssemblyAI 형식(ms, 절대) 대신 words_to_relative가 기대하는 형식으로 맞춰
    # build_ass에 바로 넣을 수 있도록 clip_start=0, 단위를 ms로 되돌려 전달
    words_ms = [{"start": w["t"]*1000, "end": w["e"]*1000, "text": w["w"]} for w in words]

    # 자막은 효과 시점 이후 안 나옴 (음성·자막 동반 컷오프 사양)
    sub_end = None if not swell else effect_t
    ass = gen.build_ass(words_ms, 0.0, footage_dur, emphasis, TMP/"subs.ass",
                        sub_end=sub_end, sub_y=sub_y, sub_mode=sub_mode, sub_scale=sub_scale)

    ib = intro_black if intro_black>0 else None
    if montage and images and len(cuts) >= 2:
        pA = gen.make_vertical(clip, TMP/"partA.mp4", 0, effect_t, black_until=ib)
        pB = gen.build_montage(images, cuts, TMP/"partB.mp4", TMP/"segs")
        vo_footage = gen.concat_videos([pA, pB], TMP/"video_footage.mp4")
    elif effect_type=="bw":
        vo_footage = gen.make_vertical(clip, TMP/"video_footage.mp4", 0, footage_dur, bw_from=effect_t, black_until=ib)
    else:
        # 몽타주 없음/그 외 → 전체 길이(footage_dur)로 구성 (일부만 자르면 영상이 잘리는 버그였음 — 수정됨)
        vo_footage = gen.make_vertical(clip, TMP/"video_footage.mp4", 0, footage_dur, black_until=ib)

    # 컷어웨이 재현: 에디터에서 수정된 강조어/자막 타이밍 기준으로 재계산 —
    # 강조 체크박스를 바꾸면 컷어웨이 타이밍도 그에 맞춰 따라옴
    if broll_mode=="cutaway":
        wr=[{"t":w["t"],"e":w["e"],"w":w["w"]} for w in words if w["t"]>=(ib or 0)+0.3]
        if cutaway_style=="blackword":
            card=gen.build_black_card(TMP/"black_card.png")
            cutaways=gen.cutaway_windows(wr,emphasis,effect_t,99,cutaway_sec,word_flash=True)
            if cutaways:
                print(f"  ⬛ 블랙 플래시 {len(cutaways)}개 재현")
                vo_footage=gen.apply_cutaways(vo_footage,TMP/"video_cutaway.mp4",[str(card)],cutaways,footage_dur)
        elif images:
            cutaways=gen.cutaway_windows(wr,emphasis,effect_t,len(images),cutaway_sec)
            if cutaways:
                print(f"  🎞️ 컷어웨이 {len(cutaways)}개 재현")
                vo_footage=gen.apply_cutaways(vo_footage,TMP/"video_cutaway.mp4",images,cutaways,footage_dur)

    if effect_type=="outro":
        outro_card = gen.build_outro_card(TMP/"outro.mp4", outro_sec)
        vo = gen.concat_videos([vo_footage, outro_card], TMP/"video_only.mp4")
    else:
        vo = vo_footage

    out = LATEST/"reel_final.mp4"
    gen.finalize(vo, clip, (bgm if bgm_present else None), ass, out,
                 effect_t, total_dur, bgm_start, bgm_climax=bgm_climax,
                 voice_present=voice_present, swell=swell)
    print(f"✅ 재렌더 완료 → {out} ({out.stat().st_size/1024/1024:.1f}MB)")

if __name__ == "__main__":
    main()
