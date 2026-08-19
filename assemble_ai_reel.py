# -*- coding: utf-8 -*-
"""
bodetail AI 릴스 조립기 v2
─ 힉스필드 클립·보이스를 자막까지 입힌 완성 릴스로 합성 ─

v2 변경점:
 · 자막 자동 번인 — script.txt만 넣으면 블록 타이밍에 맞춰 자동 생성
 · 정지 프레임 제거 — 보이스가 길면 미세 감속(setpts)으로 동적 느낌 유지
 · 입력 검증 강화 — 번호 짝·길이 이상을 사전 차단
 · 중복 아카이브 기본 해제 — 저장소 용량 절약

사지방(브라우저 전용) 전제: 조립은 GitHub Actions에서 수행한다.

입력 (videos/ai_reel/):
  clip_01.mp4, clip_02.mp4, ...   필수, 순서대로
  voice_01.mp3, voice_02.mp3, ... 선택 (없으면 무음)
  script.txt                      선택 — 한 줄에 한 블록. 있으면 자막 자동 번인
  bgm.mp3                         선택 (없으면 assets_audio/bgm/ 랜덤)

출력 (reels/latest_ai/):
  reel_ai.mp4        자막 번인 완성본 — 바로 업로드
  reel_nosub.mp4     자막 없는 버전 — 위치를 손보고 싶을 때
  subtitles.json     bodetail_editor.html 호환
  thumbnail.png / info.json

env:
  IN_DIR / OUT_DIR
  BGM_VOL (0.18)  VOICE_VOL (1.0)
  SUB_SIZE (58)   SUB_Y (1180)
  MAX_SLOWDOWN (1.15)  감속 상한 — 넘는 만큼은 핑퐁으로 채움
  MIN_SEG (0.7)        자막 구절 최소 노출 초 — 이보다 짧으면 이웃과 병합
  FILL_MODE (auto)     auto|slow|freeze — 보이스가 길 때 채우는 방식
  ARCHIVE (0)
"""
import os, re, sys, glob, json, random, shutil, subprocess, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

W, H, FPS = 1080, 1920, 30
IN_DIR  = Path(os.environ.get("IN_DIR",  "videos/ai_reel"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "reels/latest_ai"))
WORK    = Path("_aiwork")
BGM_DIR = Path("assets_audio/bgm")


def envf(k, d):
    v = os.environ.get(k, "")
    try:
        return float(v) if v.strip() else d
    except Exception:
        return d


BGM_VOL      = envf("BGM_VOL", 0.18)
VOICE_VOL    = envf("VOICE_VOL", 1.0)
SUB_SIZE     = int(envf("SUB_SIZE", 58))
SUB_Y        = int(envf("SUB_Y", 1180))
MAX_SLOWDOWN = envf("MAX_SLOWDOWN", 1.15)   # 프레임 중복 최소화
MIN_SEG      = envf("MIN_SEG", 0.7)         # 자막 구절 최소 노출(초) — 플리커 방지
ARCHIVE      = os.environ.get("ARCHIVE", "0") == "1"
FILL_MODE    = (os.environ.get("FILL_MODE", "") or "auto").lower()
_CPU         = os.cpu_count() or 2
WORKERS      = max(1, int(envf("WORKERS", max(1, _CPU // 2))))
FF_THREADS   = max(1, _CPU // WORKERS)
TARGET_LUFS  = envf("TARGET_LUFS", -14.0)   # 인스타/유튜브 기준 통합 음량

WARN = []


def die(msg):
    """치명적 오류 — 종료 전에 누적된 경고를 반드시 쏟아낸다.
    원격(Actions) 환경에서는 로그가 유일한 단서라 이게 없으면 원인 추적이 끊긴다."""
    print(f"\n❌ 치명적 오류: {msg}")
    if WARN:
        print(f"\n⚠️  종료 전 누적 경고 {len(WARN)}건:")
        for w in WARN:
            print("   - " + w)
    print("\n💡 확인 순서: ① 파일명 규칙(clip_01/voice_01) "
          "② 클립이 손상되지 않았는지 ③ 위 경고 내용")
    sys.exit(1)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("\n[ffmpeg stderr]\n" + r.stderr[-1500:])
        die("ffmpeg 실패: " + " ".join(str(c) for c in cmd[:10]) + " ...")
    return r


PROBE_TIMEOUT = 30

def probe(path, stream="v"):
    """길이(초). 손상 파일에서 프로세스가 멈추지 않도록 타임아웃을 건다."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream,
                            "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        die(f"{Path(path).name} 분석이 {PROBE_TIMEOUT}초를 넘겼습니다 — 손상된 파일일 수 있습니다.")
    try:
        return float(r.stdout.strip().split("\n")[0])
    except Exception:
        try:
            r2 = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, timeout=PROBE_TIMEOUT)
        except subprocess.TimeoutExpired:
            return 0.0
        try:
            return float(r2.stdout.strip())
        except Exception:
            return 0.0


# ── 1. 수집 + 검증 ──────────────────────────────────────────────
def collect():
    clips = sorted(glob.glob(str(IN_DIR / "clip_*.mp4")) + glob.glob(str(IN_DIR / "clip_*.MP4")))
    voices = sorted(glob.glob(str(IN_DIR / "voice_*.mp3")) +
                    glob.glob(str(IN_DIR / "voice_*.wav")) +
                    glob.glob(str(IN_DIR / "voice_*.m4a")))
    if not clips:
        print(f"ℹ️  {IN_DIR}/ 에 clip_*.mp4 없음 — 할 일 없이 종료 (정상)")
        sys.exit(0)

    # 엄격한 파일명 규칙 — clip_01.mp4 / voice_01.mp3 만 허용.
    # clip_01_final_v2.mp4 같은 변형을 조용히 통과시키면 순서가 뒤섞인다.
    CLIP_RE  = re.compile(r"^clip_(\d{1,3})\.(mp4|mov)$", re.I)
    VOICE_RE = re.compile(r"^voice_(\d{1,3})\.(mp3|wav|m4a)$", re.I)

    def strict(paths, rx, kind):
        nums, bad = [], []
        for p in paths:
            m = rx.match(Path(p).name)
            if m:
                nums.append(int(m.group(1)))
            else:
                bad.append(Path(p).name)
        if bad:
            die(f"{kind} 파일명이 규칙에 맞지 않습니다: {bad}\n"
                f"   허용 형식: {'clip_01.mp4' if kind=='클립' else 'voice_01.mp3'} "
                "(숫자 외 접미사·공백·괄호 불가)")
        return nums

    cn = strict(clips, CLIP_RE, "클립")
    vn = strict(voices, VOICE_RE, "보이스")
    if not cn:
        die("클립 파일명에 번호가 없습니다. clip_01.mp4 형식으로 맞춰주세요.")

    # 0바이트·극소 파일 사전 차단
    tiny = [Path(p).name for p in clips + voices if Path(p).stat().st_size < 1024]
    if tiny:
        die(f"손상되었거나 비어 있는 파일: {tiny}")

    # 번호순으로 재정렬 (사전순 정렬이 두 자리/세 자리 혼용 시 어긋나는 것 방지)
    clips = [p for _, p in sorted(zip(cn, clips))]
    voices = [p for _, p in sorted(zip(vn, voices))] if voices else []
    cn, vn = sorted(cn), sorted(vn)
    if len(set(cn)) != len(cn):
        die(f"클립 번호가 중복됩니다: {cn}")
    if voices:
        if len(voices) != len(clips):
            WARN.append(f"클립 {len(clips)}개 / 보이스 {len(voices)}개 — 개수 불일치. "
                        "남는 클립은 무음 처리됩니다.")
        elif cn != vn:
            die(f"클립 번호 {cn} 와 보이스 번호 {vn} 가 다릅니다. "
                "나레이션이 어긋나므로 중단합니다.")

    print(f"📥 클립 {len(clips)}개, 보이스 {len(voices)}개")
    return clips, voices


def load_script(n_blocks):
    p = IN_DIR / "script.txt"
    if not p.exists():
        print("ℹ️  script.txt 없음 — 자막 없이 조립 (에디터에서 직접 넣으세요)")
        return None
    lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return None
    if len(lines) != n_blocks:
        WARN.append(f"script.txt 줄 수({len(lines)}) ≠ 블록 수({n_blocks}). "
                    "앞에서부터 매칭합니다.")
    print(f"📝 자막 {len(lines)}줄 로드")
    return lines


# ── 2. 블록 합성 ───────────────────────────────────────────────
def build_block(i, clip, voice):
    cdur = probe(clip, "v")
    vdur = probe(voice, "a") if voice else 0.0
    if cdur <= 0:
        die(f"블록 {i}: 클립을 읽을 수 없습니다 ({Path(clip).name}) — "
            "파일이 손상됐거나 mp4가 아닐 수 있습니다.")

    if voice and vdur > cdur * 2.5:
        WARN.append(f"블록 {i}: 보이스({vdur:.1f}s)가 클립({cdur:.1f}s)의 2.5배 초과 — "
                    "파일 짝이 틀렸을 수 있습니다.")
    if voice and 0 < vdur < 0.4:
        WARN.append(f"블록 {i}: 보이스가 {vdur:.1f}s로 비정상적으로 짧습니다.")

    # 블록 길이는 나레이션이 결정한다. 클립이 길면 잘라 쓰고(권장),
    # 짧으면 아래 로직으로 채운다. 보이스가 없으면 클립 길이를 따른다.
    dur = max(vdur, 0.5) if voice and vdur > 0.1 else max(cdur, 0.5)
    if voice and cdur > vdur + 0.05:
        print(f"     ↳ 클립 {cdur - vdur:.2f}s 잘라냄 (나레이션 길이에 맞춤)")

    # ── 부족분 채우기: 감속(소폭) → 핑퐁(잔여) → 정지는 쓰지 않는다 ──
    # 감속은 프레임 중복을 만들고, 핑퐁은 방향성 있는 카메라 무브에서 튄다.
    # 그래서 작은 차이는 감속으로 흡수하고, 남는 만큼만 역재생으로 잇는다.
    pts, pong, mode = "", 0.0, "그대로"
    if vdur > cdur + 0.02:
        # 방향성이 뚜렷한 클립(걷기·붓기)은 역재생이 글리치로 보인다.
        # 근본 해법은 클립을 길게 뽑아 '잘라 쓰는' 것 — 아래는 안전망일 뿐이다.
        WARN.append(f"블록 {i}: 클립({cdur:.1f}s)이 보이스({vdur:.1f}s)보다 짧아 "
                    "늘려서 채웁니다. 다음부터는 클립을 넉넉히(10초) 뽑아 "
                    "잘라 쓰는 편이 화질·자연스러움 모두 낫습니다.")
        ratio = min(vdur / cdur, MAX_SLOWDOWN)
        if ratio > 1.001:
            pts = f",setpts={ratio:.4f}*PTS"
        after = cdur * ratio
        pong = max(0.0, dur - after)
        if FILL_MODE == "slow":        # 핑퐁 없이 감속만 (부족분은 정지)
            pong = 0.0
        elif FILL_MODE == "freeze":    # 감속도 핑퐁도 없이 정지만
            pts, ratio, after, pong = "", 1.0, cdur, 0.0
        parts = []
        if ratio > 1.001:
            parts.append(f"감속 x{ratio:.2f}")
        if pong > 0.05:
            parts.append(f"핑퐁 {pong:.2f}s")
        mode = " + ".join(parts) if parts else "그대로"
        if pong > after * 0.8:
            WARN.append(f"블록 {i}: 보이스가 클립보다 과도하게 깁니다 "
                        f"(클립 {cdur:.1f}s / 보이스 {vdur:.1f}s). "
                        "대본을 줄이거나 더 긴 클립을 쓰세요.")

    out = WORK / f"blk_{i:02d}.mp4"
    base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=28:2,eq=brightness=-0.28[bg];"
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{pts},fps={FPS},setsar=1")
    if pong > 0.05:
        # 앞부분 그대로 + 끝에서 역재생 구간을 이어붙여 동적 느낌 유지
        vf = (base + "[fw];[fw]split=2[fw1][fw2];"
              f"[fw2]reverse,trim=duration={pong:.3f},setpts=PTS-STARTPTS[rv];"
              f"[fw1][rv]concat=n=2:v=1,trim=duration={dur:.3f},setpts=PTS-STARTPTS[v]")
    else:
        hold = max(0.0, dur - (cdur * (1.0 if not pts else float(pts.split("=")[1].split("*")[0]))))
        pad = f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.02 else ""
        vf = base + pad + f",trim=duration={dur:.3f},setpts=PTS-STARTPTS[v]"

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip)]
    if voice:
        cmd += ["-i", str(voice)]
        af = (f"[1:a]volume={VOICE_VOL},apad=whole_dur={dur:.3f},"
              f"atrim=duration={dur:.3f},asetpts=N/SR/TB[a]")
        cmd += ["-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
                "-filter_complex", vf, "-map", "[v]", "-map", "1:a"]
    # 중간 결과물은 시각적 무손실(crf 14)로 — 최종에서 한 번 더 인코딩되므로
    # 여기서 압축을 세게 걸면 손실이 누적된다(generation loss).
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", str(FF_THREADS),
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{dur:.3f}", str(out)]
    run(cmd)
    if not out.exists() or out.stat().st_size < 2048:
        die(f"블록 {i} 렌더 결과가 비었습니다.")
    got = probe(out, "v")
    if abs(got - dur) > 0.35:
        WARN.append(f"블록 {i}: 목표 {dur:.2f}s 인데 결과가 {got:.2f}s — 싱크가 어긋날 수 있습니다.")
    print(f"  🎬 블록 {i}: 클립 {cdur:.2f}s / 보이스 {vdur:.2f}s -> {dur:.2f}s  [{mode}]")
    return out, dur


# ── 3. 자막 ────────────────────────────────────────────────────
def wrap_ko(text, per_line=17):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = w if not cur else cur + " " + w
        if len(t) <= per_line:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) <= 2:
        return lines
    h = len(lines) // 2
    return [" ".join(lines[:h]), " ".join(lines[h:])]


def ass_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def split_phrases(text, max_parts=3):
    """블록 대본을 자연스러운 구절로 분할. 쉼표 우선, 없으면 어절로 균등 분할."""
    t = text.strip()
    if len(t) <= 14:
        return [t]
    # 1순위: 쉼표
    if "," in t:
        parts = [p.strip() for p in t.split(",") if p.strip()]
        if len(parts) > max_parts:                      # 너무 잘게 쪼개지면 병합
            step = -(-len(parts) // max_parts)
            parts = [" ".join(parts[i:i + step]) for i in range(0, len(parts), step)]
        return parts
    # 2순위: 어절 기준 균등 분할
    words = t.split()
    n = 2 if len(t) <= 26 else 3
    n = min(n, max_parts, len(words))
    if n <= 1:
        return [t]
    per = -(-len(words) // n)
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)]


def phrase_events(lines, durs):
    """블록 대본 → 구절 (시작, 끝, 텍스트). 글자수 비례 배분 + 최소 노출 보장.

    짧은 구절이 0.2초만 스쳐 지나가면 읽히지 않고 눈만 피로해진다(플리커).
    MIN_SEG 미만이 생기면 이웃 구절과 병합해 다시 계산한다.
    """
    ev, t = [], 0.0
    for i, d in enumerate(durs):
        if i < len(lines):
            span = max(d - 0.15, 0.4)
            ph = split_phrases(lines[i])
            # 최소 노출을 못 채우면 구절 수를 줄여가며 재계산
            while len(ph) > 1:
                w = [max(len(p), 1) for p in ph]
                segs = [span * (x / sum(w)) for x in w]
                if min(segs) >= MIN_SEG:
                    break
                j = segs.index(min(segs))                 # 가장 짧은 구절을
                k = j - 1 if j == len(ph) - 1 else j + 1   # 이웃과 병합
                merged = (ph[j] + " " + ph[k]) if k > j else (ph[k] + " " + ph[j])
                ph = ph[:min(j, k)] + [merged] + ph[max(j, k) + 1:]
            w = [max(len(p), 1) for p in ph]
            segs = [span * (x / sum(w)) for x in w]
            cur = t + 0.08
            for p, s in zip(ph, segs):
                ev.append((cur, cur + s, p))
                cur += s
        t += d
    return ev


def build_ass(lines, durs, path):
    """크림색 글씨 + 검은 외곽선. 구절 단위로 교체되어 시각적 호흡을 만든다."""
    margin_v = max(60, H - SUB_Y - int(SUB_SIZE * 2.2))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: bd,Noto Sans CJK KR,{SUB_SIZE},&H00D8E6ED,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ev = []
    for st, en, txt in phrase_events(lines, durs):
        body = "\\N".join(wrap_ko(txt))
        ev.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},bd,,0,0,0,,{body}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    return len(ev), path


def build_subtitles_json(lines, durs, path):
    subs = []
    for st, en, txt in phrase_events(lines, durs):
        subs.append({"text_en": "", "text_ko": txt,
                     "start": round(st, 2), "end": round(en, 2),
                     "box_x": 90, "box_y": SUB_Y, "box_w": W - 180,
                     "box_h": int(SUB_SIZE * 2.2), "style": "outline", "pinned": False})
    path.write_text(json.dumps({"video": "reel_nosub.mp4", "duration": round(sum(durs), 2),
                                "canvas": {"w": W, "h": H}, "font_size": SUB_SIZE,
                                "subtitles": subs}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def measure_loudness(path):
    """1패스: 통합 음량·트루피크 측정 (EBU R128)."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True, timeout=180)
    try:
        s = r.stderr.rindex("{"); e = r.stderr.rindex("}") + 1
        m = json.loads(r.stderr[s:e])
        print(f"🔊 측정: {float(m['input_i']):.1f} LUFS / TP {float(m['input_tp']):.1f} dB "
              f"→ 목표 {TARGET_LUFS} LUFS")
        return m
    except Exception:
        WARN.append("라우드니스 측정 실패 — 단순 리미터로 대체합니다.")
        return None


def loudnorm_filter(m):
    """2패스: 측정값 기반 정규화. 리미터만 쓸 때 생기는 펌핑 없이
       다이나믹 레인지를 유지하며 목표 음량으로 맞춘다."""
    if not m:
        return "alimiter=limit=-1dB:level=disabled"
    return (f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true:print_format=summary")


def pick_bgm():
    local = list(IN_DIR.glob("bgm.*"))
    if local:
        return local[0]
    if BGM_DIR.exists():
        c = [p for p in BGM_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
        if c:
            return random.choice(c)
    return None


# ── 4. 메인 ────────────────────────────────────────────────────
def main():
    clips, voices = collect()
    lines = load_script(len(clips))
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 블록 렌더는 서로 독립적이므로 병렬 처리한다.
    # ffmpeg 자체도 멀티스레드라 워커를 과하게 늘리면 오히려 느려진다 → 코어/2 수준.
    jobs = [(i + 1, c, voices[i] if i < len(voices) else None) for i, c in enumerate(clips)]
    print(f"⚙️  블록 {len(jobs)}개 병렬 렌더 (워커 {WORKERS}, ffmpeg 스레드 {FF_THREADS})")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda a: build_block(*a), jobs))
    blocks = [r[0] for r in results]
    durs = [r[1] for r in results]
    total = sum(durs)

    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{b.resolve()}'\n" for b in blocks), encoding="utf-8")
    joined = WORK / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(joined)])
    print(f"🔗 결합 완료 — 총 {total:.1f}초")

    mixed = WORK / "mixed.mp4"
    bgm = pick_bgm()
    if bgm:
        print(f"🎵 BGM: {Path(bgm).name} (volume {BGM_VOL})")
        fs = max(0.0, total - 1.5)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
             "-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
             f"[1:a]volume={BGM_VOL},afade=t=in:st=0:d=1.0,afade=t=out:st={fs:.2f}:d=1.5[bg];"
             # 합성만 하고, 음량 정규화는 최종 단계에서 EBU R128로 한 번에 처리한다.
             f"[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-t", f"{total:.3f}", str(mixed)])
    else:
        print("ℹ️  BGM 없음 — 나레이션만")
        shutil.copy(joined, mixed)

    # ── 음량 정규화 (EBU R128 2패스) ──
    af = loudnorm_filter(measure_loudness(mixed))

    nosub = OUT_DIR / "reel_nosub.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mixed), "-af", af,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(nosub)])

    final = OUT_DIR / "reel_ai.mp4"
    if lines:
        n_ev, ass = build_ass(lines, durs, WORK / "sub.ass")
        # 최종 인코딩은 여기 한 번뿐 — 중간물이 crf 14였으므로 손실이 누적되지 않는다.
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mixed),
             "-vf", f"subtitles={ass}:fontsdir=/usr/share/fonts",
             "-af", af,
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", str(final)])
        build_subtitles_json(lines, durs, OUT_DIR / "subtitles.json")
        print(f"💬 자막 번인 완료 — {len(lines)}블록을 {n_ev}개 구절로 분할")
    else:
        shutil.copy(nosub, final)

    # 최종 산출물 무결성 확인
    fd = probe(final, "v")
    if not final.exists() or final.stat().st_size < 10240:
        die("최종 파일이 생성되지 않았거나 비어 있습니다.")
    if abs(fd - total) > 0.6:
        WARN.append(f"최종 길이 {fd:.2f}s 가 예상 {total:.2f}s 와 다릅니다.")

    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(final), "-ss", "0.3",
         "-frames:v", "1", str(OUT_DIR / "thumbnail.png")])

    (OUT_DIR / "info.json").write_text(json.dumps({
        "blocks": len(blocks), "duration_sec": round(total, 2),
        "block_durations": [round(d, 2) for d in durs],
        "voices": len(voices), "subtitles": len(lines) if lines else 0,
        "bgm": Path(bgm).name if bgm else None, "warnings": WARN,
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    if ARCHIVE:
        arch = Path("reels") / ("ai_" + datetime.datetime.now().strftime("%Y-%m-%d"))
        if arch.exists():
            shutil.rmtree(arch)
        shutil.copytree(OUT_DIR, arch)
        print(f"📦 아카이브: {arch}")

    shutil.rmtree(WORK)
    if WARN:
        print(f"\n⚠️  경고 {len(WARN)}건:")
        for w in WARN:
            print("   - " + w)
    print(f"\n✅ 완료 -> {final}  ({total:.1f}초, {len(blocks)}블록)")
    if lines:
        print("   자막까지 들어간 완성본입니다. 바로 업로드하세요.")
        print("   위치를 고치려면 reel_nosub.mp4 + subtitles.json을 에디터로 여세요.")


if __name__ == "__main__":
    main()
