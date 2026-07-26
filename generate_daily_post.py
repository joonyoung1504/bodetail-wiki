# -*- coding: utf-8 -*-
"""
bodetail 게시물 → 릴스 변환기 v1
─ 카드뉴스 최종본 PNG들을 릴스(1080×1920) 슬라이드쇼 영상으로 자동 변환 ─

워크플로:
 1) 에디터에서 완성한 슬라이드 PNG들을 reels_input/ 폴더에 업로드(커밋)
 2) GitHub Actions가 자동 실행 → 릴스 mp4 2종 생성
    · reel_final.mp4  : BGM 포함 완성본 (assets_audio/bgm/ 중 랜덤 1곡)
    · reel_silent.mp4 : 무음 버전 (인스타 앱에서 트렌딩 오디오 입힐 때 사용)
 3) reels/latest_post/ 에 커밋됨 → 다운로드해서 업로드

규칙:
 · 슬라이드 순서 = 파일명 오름차순 정렬 (01.png, 02.png … 권장)
 · 어떤 비율의 PNG든 OK — 9:16 캔버스에 블러 배경 채움 + 중앙 배치
 · 바이럴 하드컷 스타일: 효과 없음, 정지 화면 → 즉시 다음 장
 · 표지 1.5초 / 본문 1.9초 / 마지막 장 2.2초 (env로 조절 가능)
   — 읽기보다 살짝 빠른 페이싱 = 다시보기 유도(재생수 부스트)
 · assets_audio/sfx/boom.mp3 존재 시 마지막 장 시작에 브랜드 붐 SFX 믹스

env:
  INPUT_DIR   (기본 reels_input)
  COVER_SEC   (기본 2.4)  SLIDE_SEC (기본 3.2)  LAST_SEC (기본 3.0)
  BGM_VOL     (기본 0.85)
"""
import os, sys, glob, random, shutil, subprocess, datetime
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance

W, H, FPS = 1080, 1920, 30
INPUT_DIR = Path(os.environ.get("INPUT_DIR", "reels_input"))
OUT       = Path("reels/latest_post")
ARCH      = Path("reels") / ("post_" + datetime.datetime.now().strftime("%Y-%m-%d"))
WORK      = Path("_reelwork")

COVER_SEC = float(os.environ.get("COVER_SEC", "1.5"))
SLIDE_SEC = float(os.environ.get("SLIDE_SEC", "1.9"))
LAST_SEC  = float(os.environ.get("LAST_SEC",  "2.2"))
BGM_VOL   = float(os.environ.get("BGM_VOL",   "0.85"))

BGM_DIR = Path("assets_audio/bgm")
SFX_BOOM = None
for ext in ("mp3", "wav", "m4a"):
    p = Path(f"assets_audio/sfx/boom.{ext}")
    if p.exists():
        SFX_BOOM = p
        break


def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def collect_slides():
    exts = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG")
    files = []
    for e in exts:
        files += glob.glob(str(INPUT_DIR / e))
    files = sorted(set(files))
    if not files:
        print(f"ℹ️  {INPUT_DIR}/ 에 이미지 없음 — 할 일 없이 종료 (정상)")
        sys.exit(0)
    if len(files) < 2:
        die("슬라이드가 2장 이상 필요함.")
    print(f"📥 슬라이드 {len(files)}장: " + ", ".join(Path(f).name for f in files))
    return files


def to_canvas(src, dst):
    """어떤 비율이든 1080×1920 캔버스로: 블러+어둡게 처리한 배경 채움 + 원본 중앙 배치."""
    im = Image.open(src).convert("RGB")

    # 배경: 원본을 캔버스 꽉 차게 확대 → 블러 → 감광
    bg = im.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 2, int(bg.height * scale) + 2), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2,
                  (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)

    # 전경: 가로 1080 기준 맞춤(세로가 1920 넘으면 세로 기준)
    fscale = min(W / im.width, H / im.height)
    fg = im.resize((round(im.width * fscale), round(im.height * fscale)), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(dst, "PNG")


def build_video(canvases, durs):
    """하드컷 슬라이드쇼: 각 장을 정지 화면으로 durs만큼 보여주고 즉시 다음 장."""
    n = len(canvases)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c, d in zip(canvases, durs):
        cmd += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(c)]

    fparts = [f"[{i}:v]fps={FPS},setsar=1[v{i}]" for i in range(n)]
    fparts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]")
    total = sum(durs)

    silent = WORK / "base_silent.mp4"
    cmd += ["-filter_complex", ";".join(fparts), "-map", "[vout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-movflags", "+faststart", str(silent)]
    subprocess.run(cmd, check=True)
    print(f"🎬 베이스 영상 완료 ({total:.1f}초, 하드컷 {n}장)")
    return silent, total


def pick_bgm():
    if not BGM_DIR.exists():
        return None
    cands = [p for p in BGM_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
    if not cands:
        return None
    bgm = random.choice(cands)
    print(f"🎵 BGM: {bgm.name}")
    return bgm


def mux_audio(silent, total, bgm, out_path, boom_at=None):
    """BGM 루프 + 페이드 + (옵션) 붐 SFX 믹스."""
    fade_out_st = max(0.0, total - 1.4)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
           "-stream_loop", "-1", "-i", str(bgm)]
    afilters = (f"[1:a]volume={BGM_VOL},afade=t=in:st=0:d=0.8,"
                f"afade=t=out:st={fade_out_st:.2f}:d=1.4[bgm]")
    amap = "[bgm]"
    if boom_at is not None and SFX_BOOM:
        cmd += ["-i", str(SFX_BOOM)]
        delay_ms = int(boom_at * 1000)
        afilters += (f";[2:a]adelay={delay_ms}|{delay_ms},volume=1.0[boom];"
                     f"[bgm][boom]amix=inputs=2:duration=first:normalize=0[mix]")
        amap = "[mix]"
    cmd += ["-filter_complex", afilters, "-map", "0:v", "-map", amap,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
            str(out_path)]
    subprocess.run(cmd, check=True)


def main():
    files = collect_slides()
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    canvases = []
    for i, f in enumerate(files):
        dst = WORK / f"c{i:02d}.png"
        to_canvas(f, dst)
        canvases.append(dst)
    print(f"🖼️  9:16 캔버스 변환 완료")

    n = len(canvases)
    durs = [COVER_SEC] + [SLIDE_SEC] * (n - 2) + [LAST_SEC]
    silent_base, total = build_video(canvases, durs)

    # 무음 버전 (트렌딩 오디오용) — 항상 생성
    shutil.copy(silent_base, OUT / "reel_silent.mp4")

    # BGM 버전
    bgm = pick_bgm()
    if bgm:
        boom_at = sum(durs[:-1])  # 마지막 장 시작 시점
        mux_audio(silent_base, total, bgm, OUT / "reel_final.mp4",
                  boom_at=boom_at if SFX_BOOM else None)
        print("✅ reel_final.mp4 (BGM 포함) 생성")
    else:
        print("ℹ️  assets_audio/bgm/ 에 음원이 없어 BGM 버전은 건너뜀 (무음 버전만 생성)")

    # 아카이브 + 입력 슬라이드 백업
    if ARCH.exists():
        shutil.rmtree(ARCH)
    shutil.copytree(OUT, ARCH)
    (ARCH / "slides").mkdir(exist_ok=True)
    for f in files:
        shutil.copy(f, ARCH / "slides" / Path(f).name)

    shutil.rmtree(WORK)
    print(f"📦 완료 → {OUT}/ (아카이브: {ARCH}/)")


if __name__ == "__main__":
    main()
