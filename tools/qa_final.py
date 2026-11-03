# -*- coding: utf-8 -*-
"""终检成片。默认不生成抖音竖版。

  python tools/qa_final.py <工程>
  python tools/qa_final.py <工程> --file renders/raw.mp4
  python tools/qa_final.py <工程> --tier hd30|uhd30|uhd60|vd30
  python tools/qa_final.py <工程> --audio-profile synth|bgm
  python tools/qa_final.py <工程> --douyin-pad

--tier 由参数决定，不由文件反推。默认 hd30。
硬性（hd30）：1920×1080、帧率距 30 不超过 0.1、yuv420p、H.264、首尾不是死黑。
硬性（uhd30）：3840×2160、帧率距 30 不超过 0.1、yuv420p、H.264、首尾不是死黑。
硬性（uhd60）：3840×2160、帧率距 60 不超过 0.1、yuv420p、HEVC、首尾不是死黑。
硬性（vd30）：2160×3840、帧率距 30 不超过 0.1、yuv420p、H.264、首尾不是死黑（竖屏母版）。
响度只告警：synth≈-18（约 -20.5～-15.5），bgm≈-14（约 -16.5～-11.5）。
--douyin-pad 仅 hd30：垫成 1080×1920 上下黑边。uhd 母版直接拒绝。
"""
import re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEAK_MAX = -1.0
PROFILES = {
    "synth": (-20.5, -15.5, -18),
    "bgm": (-16.5, -11.5, -14),
}
TIERS = {
    "hd30": {"w": 1920, "h": 1080, "fps": 30.0, "codec": "h264"},
    "uhd30": {"w": 3840, "h": 2160, "fps": 30.0, "codec": "h264"},
    "uhd60": {"w": 3840, "h": 2160, "fps": 60.0, "codec": "hevc"},
    "vd30": {"w": 2160, "h": 3840, "fps": 30.0, "codec": "h264"},
}


def ffmpeg_bin():
    found = shutil.which("ffmpeg")
    if found:
        return found
    cand = ROOT / "bin" / "ffmpeg"
    if cand.is_file():
        return str(cand)
    sys.exit("找不到 ffmpeg。把仓库 bin/ 放进 PATH，或安装 ffmpeg。")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(ff, path):
    proc = run([ff, "-hide_banner", "-i", str(path)])
    text = proc.stderr or ""
    line = next((ln for ln in text.splitlines() if "Stream #" in ln and "Video:" in ln), "")
    if not line:
        sys.exit(f"读不到视频流：{path}\n{text[-800:]}")
    m = re.search(
        r"Video:\s+([a-z0-9_]+).*?,\s*([a-z0-9]+).*?,\s*(\d+)x(\d+),.*?([\d.]+)\s*fps",
        line,
    )
    if not m:
        # 兼容少数字典序：codec 后可能先出现分辨率
        m2 = re.search(r"Video:\s+([a-z0-9_]+)", line)
        m3 = re.search(r"(\d+)x(\d+)", line)
        m4 = re.search(r"([\d.]+)\s*fps", line)
        m5 = re.search(r"yuv[a-z0-9]+", line)
        if not (m2 and m3 and m4):
            sys.exit(f"解析不了视频流：{line}")
        codec = m2.group(1).lower()
        pix = (m5.group(0) if m5 else "?")
        w, h, fps = int(m3.group(1)), int(m3.group(2)), float(m4.group(1))
    else:
        codec, pix = m.group(1).lower(), m.group(2)
        w, h, fps = int(m.group(3)), int(m.group(4)), float(m.group(5))
    if codec in ("h264", "avc1", "libx264"):
        family = "h264"
    elif codec in ("hevc", "h265", "hev1", "hvc1", "libx265"):
        family = "hevc"
    else:
        family = codec
    has_audio = any("Stream #" in ln and "Audio:" in ln for ln in text.splitlines())
    return {"pix": pix, "w": w, "h": h, "fps": fps, "audio": has_audio, "codec": family, "raw_codec": codec, "line": line.strip()}


def grab(ff, path, w, h, tail):
    cmd = [ff, "-v", "error"]
    if tail:
        cmd += ["-sseof", "-0.2"]
    cmd += ["-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True)
    need = w * h * 3
    if proc.returncode != 0 or len(proc.stdout) < need:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        sys.exit(f"抽帧失败（{'尾' if tail else '首'}）：{err or '输出太短'}")
    buf = proc.stdout[:need]
    n = w * h
    total = 0.0
    mx = 0.0
    for i in range(0, need, 3):
        y = 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2]
        total += y
        if y > mx:
            mx = y
    return total / n, mx


def dead(mean, mx):
    return mean < 2 and mx < 8


def loudness(ff, path):
    proc = run([ff, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    log = proc.stderr or ""
    body = log[log.rfind("Summary:"):] if "Summary:" in log else ""
    mi = re.search(r"I:\s+([-\d.]+)\s+LUFS", body)
    mp = re.search(r"Peak:\s+([-\d.]+)\s+dBFS", body)
    if not mi:
        return None, None, (log[-500:] or "没有 Summary")
    peak = float(mp.group(1)) if mp else None
    return float(mi.group(1)), peak, None


def douyin(ff, src):
    out = src.with_name(f"{src.stem}_douyin.mp4")
    cmd = [
        ff, "-v", "error", "-y", "-i", str(src),
        "-vf", "scale=1080:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "medium",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        sys.exit(f"--douyin-pad 失败：{(proc.stderr or '')[-600:]}")
    print("douyin:", out)


def parse_flags(a):
    tier, profile, pad, rel = "hd30", "synth", False, None
    i = 0
    rest = []
    while i < len(a):
        if a[i] == "--tier":
            if i + 1 >= len(a):
                sys.exit("--tier 需要 hd30 / uhd30 / uhd60")
            tier = a[i + 1]; i += 1
            if tier not in TIERS:
                sys.exit(f"未知 --tier {tier}")
        elif a[i] == "--audio-profile":
            if i + 1 >= len(a):
                sys.exit("--audio-profile 需要 synth 或 bgm")
            profile = a[i + 1]; i += 1
            if profile not in PROFILES:
                sys.exit(f"未知 --audio-profile {profile}")
        elif a[i] == "--douyin-pad":
            pad = True
        elif a[i] == "--file":
            if i + 1 >= len(a):
                sys.exit("--file 需要路径")
            rel = a[i + 1]; i += 1
        else:
            rest.append(a[i])
        i += 1
    return rest, tier, profile, pad, rel


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    rest, tier, profile, pad, rel = parse_flags(a)
    if not rest:
        sys.exit(__doc__)
    proj = Path(rest[0]).resolve()
    spec = TIERS[tier]
    loud_lo, loud_hi, loud_target = PROFILES[profile]
    src = (proj / rel).resolve() if rel else proj / "renders" / "final.mp4"
    if not src.is_file():
        sys.exit(f"没有成片：{src}")
    if pad and tier != "hd30":
        sys.exit("uhd 母版拒绝 --douyin-pad；请从 1080p30 母版派生竖版")
    ff = ffmpeg_bin()
    info = probe(ff, src)
    fails, warns = [], []
    print(f"tier={tier} profile={profile}")
    print(f"stream: {info['w']}x{info['h']} {info['fps']}fps {info['pix']} codec={info['raw_codec']}→{info['codec']}")
    if (info["w"], info["h"]) != (spec["w"], spec["h"]):
        fails.append(f"画幅 {info['w']}x{info['h']}，要 {spec['w']}x{spec['h']}")
    if abs(info["fps"] - spec["fps"]) > 0.1:
        fails.append(f"帧率 {info['fps']}，距 {spec['fps']} 超过 0.1")
    if info["pix"] != "yuv420p":
        fails.append(f"像素格式 {info['pix']}，要 yuv420p")
    if info["codec"] != spec["codec"]:
        fails.append(f"编码 {info['raw_codec']}（{info['codec']}），要 {spec['codec']}")
    for label, tail in (("首帧", False), ("尾帧", True)):
        mean, mx = grab(ff, src, info["w"], info["h"], tail)
        print(f"{label}: luma mean={mean:.2f} max={mx:.2f}")
        if dead(mean, mx):
            fails.append(f"{label}死黑（mean={mean:.2f} max={mx:.2f}）")
    if not info["audio"]:
        warns.append("无音轨，跳过响度")
    else:
        integrated, peak, err = loudness(ff, src)
        if err:
            warns.append(f"响度未能测量：{err.strip()}")
        else:
            peak_s = "n/a" if peak is None else f"{peak:.1f}"
            print(f"loudness: I={integrated:.1f} LUFS peak={peak_s} dBFS（目标约 {loud_target}）")
            if not (loud_lo <= integrated <= loud_hi):
                warns.append(f"集成响度 {integrated:.1f} LUFS，目标约 {loud_target}（{loud_lo}～{loud_hi}）")
            if peak is not None and peak > PEAK_MAX:
                warns.append(f"真峰值 {peak:.1f} dBFS，高于约 {PEAK_MAX}")
    for w in warns:
        print("告警:", w)
    if fails:
        for f in fails:
            print("失败:", f)
        sys.exit("qa_final: fail")
    if pad:
        douyin(ff, src)
    print("qa_final: pass")


if __name__ == "__main__":
    main()
