# -*- coding: utf-8 -*-
"""用 PaddleOCR 读底部字幕，和 film.js 的 SUBS 对一下。

  python engine/read_subs.py <工程>
  python engine/read_subs.py <工程> --every 0.5 --to 30
  python engine/read_subs.py <工程> --video renders/raw.mp4

每 0.5 秒截一帧，只裁纵向 78% 以下。模型第一次运行会下载。
写出 review/subs.json。
"""
import json, os, re, sys

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
from pathlib import Path

import cv2

SUB_RE = re.compile(
    r"""\{\s*a:\s*([0-9.]+)\s*,\s*b:\s*([0-9.]+)\s*,\s*zh:\s*(['"])(.*?)\3\s*,\s*en:\s*(['"])(.*?)\5""",
    re.S,
)


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


def norm(s):
    s = re.sub(r"\{([^{}]*)\}", r"\1", s)
    return re.sub(r"[\s，。、！？：；—\-–·,.!?:;\"'“”‘’（）()]", "", s).lower()


def recall(expected, observed):
    exp, obs = norm(expected), norm(observed)
    if not exp:
        return 1.0
    return sum(1 for ch in exp if ch in obs) / len(exp)


def lines_of(res):
    texts = list(res["rec_texts"]) if "rec_texts" in res else []
    scores = list(res["rec_scores"]) if "rec_scores" in res else [1] * len(texts)
    kept = [t for t, s in zip(texts, scores) if float(s) >= 0.45 and str(t).strip()]
    return "".join(kept)


def load_subs(proj):
    film = proj / "film.js"
    if not film.is_file():
        return []
    text = film.read_text(encoding="utf-8")
    rows = []
    for m in SUB_RE.finditer(text):
        rows.append({"a": float(m.group(1)), "b": float(m.group(2)), "zh": m.group(4), "en": m.group(6)})
    return rows


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    proj = Path(a[0]).resolve()
    video = pick_video(proj, opt(a, "--video"))
    every = float(opt(a, "--every") or 0.5)
    to = opt(a, "--to")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"OpenCV 打不开：{video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur = frames / fps if fps else 0
    end = min(dur, float(to)) if to else dur

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(
        lang="ch",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        enable_mkldnn=False,
    )

    samples = []
    t = 0.0
    while t < end - 1e-3:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        h = frame.shape[0]
        crop = frame[int(h * 0.78):, :]
        text = ""
        for res in ocr.predict(crop):
            text = lines_of(res)
            break
        samples.append({"t": round(t, 2), "text": text})
        t += every
    cap.release()

    subs = load_subs(proj)
    checks = []
    problems = []
    for sub in subs:
        if to and sub["a"] >= float(to):
            continue
        seen = "".join(s["text"] for s in samples if sub["a"] - 0.35 <= s["t"] <= sub["b"] + 0.35)
        score = round(recall(sub["zh"], seen), 2)
        row = {"a": sub["a"], "b": sub["b"], "zh": sub["zh"], "seen": seen, "recall": score, "dwell": round(sub["b"] - sub["a"], 2)}
        checks.append(row)
        if score < 0.6:
            problems.append(f"{sub['a']:.1f}–{sub['b']:.1f}s 字幕没对上（{score:.0%}）：{sub['zh']}")

    report = {"source": str(video), "every": every, "until": round(end, 2), "samples": samples, "checks": checks, "problems": problems}
    out = proj / "review" / "subs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"read_subs: {proj.name}")
    print(f"source: {video.relative_to(proj) if video.is_relative_to(proj) else video}  抽到 {end:.1f}s / {dur:.1f}s  每 {every}s")
    print(f"字幕 {len(checks)} 句，对上 {sum(1 for c in checks if c['recall'] >= 0.6)}")
    if problems:
        print(f"问题 {len(problems)} 条：")
        for line in problems[:12]:
            print(" -", line)
    elif checks:
        print("屏幕上的字和 film.js 对得上。")
    else:
        print("film.js 里没有解析到 SUBS。时间轴在 samples。")
    print("写成", out.relative_to(proj))


if __name__ == "__main__":
    main()
