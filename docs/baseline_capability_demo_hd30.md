# capability_demo 默认档回归基线（第 0 步）

时间：2026-11-02。引擎改动前。`films/capability_demo`，默认 1920×1080×30 H.264。

## 静帧 MD5（PNG）

| t (s) | 文件 | md5 |
|------:|------|-----|
| 0.5 | `review/baseline_pre/s_0000.50.png` | `0b12db0bc5ce8f655927de82afabe0f8` |
| 2.0 | `review/baseline_pre/s_0002.00.png` | `49f18155e7814a1bc2e7f2235b77cc5b` |
| 5.0 | `review/baseline_pre/s_0005.00.png` | `cae8a530796d27414b4744f9bcfdd748` |
| 9.0 | `review/baseline_pre/s_0009.00.png` | `64d9fa3d44e1133c544a87b2b750e23a` |

截帧耗时（仅 stills）：约 1.7 s wall。

## qa_final（已有 `renders/final.mp4`）

- stream: 1920×1080 30.0fps yuv420p
- loudness: I=-17.1 LUFS peak=-1.5 dBFS
- 结果：pass

全片重渲耗时留到第 5 步与升级后对照。

## 第 5 步实测（升级后）

- **S=1 静帧**：四枚基线 MD5 全部一致。
- **4K30 / 3s**（`--scale 2 --fps 30`）：约 54 s wall；3840×2160、bt709。
- **uhd60 / 3s 单路**：约 101 s。
- **uhd60 / 10s · `--jobs 4`**：约 **123 s** wall（约 12× 实时）。
- **uhd60 / 10s · `--jobs 2`**：约 **185 s** wall。结论：4 路明显更快，可继续默认 4。
- **成片**：`renders/final_uhd60_hevc.mp4`，`qa_final --tier uhd60` pass；HEVC / hvc1 / 3840×2160 / 60fps。
- **已知**：本机 `hevc_videotoolbox` 即使 `-b:v 50M -constant_bit_rate true`，成片码率常落在数 Mbps；要咬住 40～60 Mbps 用 `--hevc`（libx265）不要加 `--vt`。
