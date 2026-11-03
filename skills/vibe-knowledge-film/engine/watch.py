# -*- coding: utf-8 -*-
"""用 OpenCV 把成片读成运动时间轴。

  python engine/watch.py <工程>
  python engine/watch.py <工程> --video renders/raw.mp4

先缩小、再模糊，压掉胶片颗粒，然后算逐帧差分。
写出 review/watch.json：每秒运动能量、最静和最忙的几秒、亮度跳变时刻。
"""
import json, sys
from pathlib import Path

import cv2
import numpy as np


def opt(a, name):
    if name not in a:
        return None
    i = a.index(name)
    return a[i + 1] if i + 1 < len(a) else None


def pick_video(proj, given):
    if given:
        path = Path(given)
        if not path.is_file():
            path = proj / given
        if not path.is_file():
            sys.exit(f"找不到视频：{given}")
        return path
    for rel in ("renders/final.mp4", "renders/raw.mp4"):
        path = proj / rel
        if path.is_file():
            return path
    sys.exit("没有 renders/final.mp4 或 renders/raw.mp4。先渲片。")


def cluster(times, gap=0.4):
    out = []
    for t in times:
        if out and t - out[-1] <= gap:
            continue
        out.append(t)
    return out


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    proj = Path(a[0]).resolve()
    video = pick_video(proj, opt(a, "--video"))
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"OpenCV 打不开：{video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nframes = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    buckets = {}
    spikes = []
    prev = None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.GaussianBlur(cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA), (5, 5), 0)
        t = idx / fps
        if prev is not None:
            energy = float(cv2.absdiff(small, prev).mean())
            buckets.setdefault(int(t), []).append(energy)
            if energy >= 18:
                spikes.append(round(t, 2))
        prev = small
        idx += 1
    cap.release()

    per_sec = []
    flat = []
    for sec in range(int(nframes / fps) + 1 if fps else 0):
        vals = buckets.get(sec)
        if not vals:
            continue
        mean = round(float(np.mean(vals)), 2)
        per_sec.append({"t": sec, "motion": mean})
        flat.append(mean)
    jumps = cluster(spikes)
    order = sorted(per_sec, key=lambda r: r["motion"])
    report = {
        "source": str(video),
        "fps": round(float(fps), 3),
        "frames": idx,
        "seconds": per_sec,
        "quietest": order[:5],
        "busiest": list(reversed(order[-5:])),
        "flashes": jumps,
    }
    out = proj / "review" / "watch.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    dur = idx / fps if fps else 0
    p50 = float(np.median(flat)) if flat else 0
    still = sum(1 for x in flat if p50 and x < p50 * 0.55)
    busy = sum(1 for x in flat if p50 and x > p50 * 2.2)
    print(f"watch: {proj.name}")
    print(f"source: {video.relative_to(proj) if video.is_relative_to(proj) else video}  {dur:.1f}s  {fps:.2f}fps")
    if flat:
        print(f"每秒运动中位 {p50:.2f}；偏静 {still}/{len(flat)} 秒，偏忙 {busy}/{len(flat)} 秒")
        print("最静", " ".join(f"{r['t']}s" for r in order[:5]))
        print("最忙", " ".join(f"{r['t']}s" for r in reversed(order[-5:])))
    if jumps:
        print("亮度跳变", " ".join(f"{t:.1f}s" for t in jumps[:16]))
    else:
        print("没有明显的亮度跳变。")
    print("写成", out.relative_to(proj))


if __name__ == "__main__":
    main()
