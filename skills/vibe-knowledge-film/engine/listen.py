# -*- coding: utf-8 -*-
"""用 librosa 把成片声音读成时间轴，和 audio/events.json 对一下。

  python engine/listen.py <工程>
  python engine/listen.py <工程> --wav 曲子.wav

默认读 audio/score.wav。没有就从 renders/final.mp4 抽出音轨。
写出 review/listen.json：每秒响度、静音是否真静、tick 是否落在 onset 上、节拍估计。
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

QUIET_DB = -42.0
ONSET_TOL = 0.18


def repo_root():
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "bin" / "ffmpeg").exists() and (p / "skills").is_dir():
            return p
    return here.parents[3]


def ffmpeg_bin():
    found = shutil.which("ffmpeg")
    if found:
        return found
    cand = repo_root() / "bin" / "ffmpeg"
    if cand.exists():
        return str(cand)
    sys.exit("找不到 ffmpeg。把仓库 bin/ 放进 PATH。")


def opt(a, name):
    if name not in a:
        return None
    i = a.index(name)
    return a[i + 1] if i + 1 < len(a) else None


def load_wav(path):
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    return y, sr


def extract_audio(ff, video, dest):
    subprocess.run(
        [ff, "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "22050", str(dest)],
        check=True,
    )


def seg_db(y, sr, a, b, edge=0.15):
    a2, b2 = a + edge, b - edge
    if b2 - a2 < 0.2:
        a2, b2 = a, b
    i0, i1 = int(a2 * sr), int(b2 * sr)
    seg = y[max(0, i0):max(i1, i0 + 1)]
    if len(seg) == 0:
        return None
    rms = float(np.sqrt(np.mean(seg ** 2)))
    return round(20 * np.log10(max(rms, 1e-8)), 1)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    proj = Path(a[0]).resolve()
    events_path = proj / "audio" / "events.json"
    spec = json.loads(events_path.read_text(encoding="utf-8")) if events_path.is_file() else {}
    wav = opt(a, "--wav")
    if wav:
        src = Path(wav)
        if not src.is_file():
            src = proj / wav
        if not src.is_file():
            sys.exit(f"找不到音频：{wav}")
    elif (proj / "audio" / "score.wav").is_file():
        src = proj / "audio" / "score.wav"
    elif (proj / "renders" / "final.mp4").is_file():
        src = proj / "renders" / "final.mp4"
    else:
        sys.exit("没有 audio/score.wav，也没有 renders/final.mp4。先跑 audio.py。")

    cleanup = None
    if src.suffix.lower() == ".mp4":
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        cleanup = Path(tmp.name)
        extract_audio(ffmpeg_bin(), src, cleanup)
        y, sr = load_wav(cleanup)
        cleanup.unlink(missing_ok=True)
    else:
        y, sr = load_wav(src)

    import librosa
    dur = len(y) / sr
    rms = librosa.feature.rms(y=y, frame_length=sr, hop_length=sr, center=False)[0]
    db = [round(float(x), 1) for x in (20 * np.log10(np.maximum(rms, 1e-8)))]
    onset = [round(float(t), 3) for t in librosa.onset.onset_detect(y=y, sr=sr, units="time")]
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    tempo = round(float(np.atleast_1d(tempo)[0]), 1)
    beats = [round(float(t), 3) for t in librosa.frames_to_time(beat_frames, sr=sr)]

    meta = spec.get("meta") or {}
    windows = []
    for pair in meta.get("silence") or []:
        if len(pair) >= 2:
            windows.append({"kind": "silence", "a": float(pair[0]), "b": float(pair[1])})
    for when, name, p in spec.get("events") or []:
        if name == "hush":
            p = p or {}
            windows.append({"kind": "hush", "a": float(when), "b": float(when) + float(p.get("dur", 2.5))})

    silence_rows = []
    problems = []
    for w in windows:
        level = seg_db(y, sr, w["a"], w["b"])
        row = {**w, "db": level, "quiet": bool(level is not None and level <= QUIET_DB)}
        silence_rows.append(row)
        if level is None:
            continue
        if level > QUIET_DB:
            problems.append(f"{w['kind']} {w['a']:.1f}–{w['b']:.1f}s 还有 {level} dB，不够静")

    ticks = []
    for when, name, p in spec.get("events") or []:
        if name not in ("tick", "tock"):
            continue
        when = float(when)
        if onset:
            nearest = min(onset, key=lambda t: abs(t - when))
            lag = round(nearest - when, 3)
        else:
            nearest, lag = None, None
        hit = bool(lag is not None and abs(lag) <= ONSET_TOL)
        ticks.append({"t": when, "name": name, "onset": nearest, "lag": lag, "hit": hit})
        if not hit:
            problems.append(f"{name} {when:.2f}s 附近没有 onset" + (f"（最近 {nearest}s）" if nearest is not None else ""))

    report = {
        "source": str(src),
        "seconds": round(dur, 2),
        "db_per_second": db,
        "silence": silence_rows,
        "ticks": ticks,
        "tempo_bpm": tempo,
        "beats": beats[:48],
        "problems": problems,
    }
    out = proj / "review" / "listen.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    hit_n = sum(1 for t in ticks if t["hit"])
    print(f"listen: {proj.name}")
    print(f"source: {src.relative_to(proj) if src.is_relative_to(proj) else src}  {dur:.1f}s")
    print(f"节拍估计 {tempo} BPM（合成垫底上只作参考）")
    if ticks:
        print(f"tick/tock {len(ticks)} 个，对上 {hit_n}")
    if silence_rows:
        quiet_n = sum(1 for r in silence_rows if r["quiet"])
        print(f"静音段 {len(silence_rows)} 处，真静 {quiet_n}")
    if problems:
        print(f"问题 {len(problems)} 条：")
        for line in problems[:12]:
            print(" -", line)
    else:
        print("事件和声音对得上。")
    print("写成", out.relative_to(proj))


if __name__ == "__main__":
    main()
