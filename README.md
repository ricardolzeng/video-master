# 视频大师

本机 Cursor 驱动的 Vibe 知识大赏 / 夜曲流水线。底座仍是 `seek(t)` + `image2pipe`，加上 `vk.js` / `audio.py`。不换引擎。

## 生产铁律

- 画幅 **16:9 · 1920×1080 · 30fps**。默认不改成 9:16，也不改成 60fps。
- 全片默认 **`--jobs 4`**。`--jobs 1` 才走单路。
- 前 **2～3 秒必须是具象钩子**（观众一眼能认出的东西），不要用抽象标题硬开场。
- 声音来源**必须先问用户**：`synth`（events 合成，≈-18 LUFS）或指定 BGM 文件。`--bgm` 默认**只垫该曲子、不叠** vibe 事件音；要叠须显式 `--with-sfx`。
- MusicGen 不是生产声源。权重是 CC-BY-NC，禁止作为抖音或商用成片的声音。

## canvas-design → 夜曲成片

1. **哲学 + tokens。** 定好这支片子的视觉判断，再落到 `tokens.json`（画布、色板、`optics.grain_opacity`、字体）。`python tools/init_tokens.py` 会写出模板和示例。`film.js` 不要 `fetch` 这个文件；渲染器在打开页面前注入 `window.VK_TOKENS`。
2. **静帧两轮。** `--stills` 看关键帧，`--sheet` 看全片节奏。有 tokens 时静帧会打印 `VK_TOKENS.width`。
3. **`storyboard.json`。** 只写钩子和分镜。它不驱动音效。
4. **`film.js`（`seek`）。** 每一帧只由时间 `t` 决定。音效用 `fr.sfx(时刻, 名字)` 登记。
5. **`render`。** 默认 4 路，出无声 `renders/raw.mp4`。
6. **`audio.py`。** 读 `audio/events.json`，合成 `renders/final.mp4`。
7. **`qa_final`。** 核对 1920×1080、约 30fps、`yuv420p`、首尾不是死黑，并按 -18 LUFS 做响度告警。

## 栈

- Skill：`skills/vibe-knowledge-film`（Canvas + Playwright + 本机 Chrome）
- 文案 Skill：`skills/vibe-knowledge-script`（全片文字层：字幕 + 画面字；开写 `film.js` 前先锁文字总表）
- 文案外部评审稿：`docs/视频大师-全片文案评审提示语.md`（可直接贴给 Claude）
- Python：`.venv`（playwright / numpy / scipy / Pillow）
- 成片感知：`.venv-perceive`（librosa、OpenCV、PaddleOCR，Python 3.12）
- ffmpeg：`bin/ffmpeg`（本机这份有 `libx264`、`h264_videotoolbox`、`libx265`、`hevc_videotoolbox`、`libkvazaar`；没有 NVENC，也没有单独的 ffprobe）
- 字体：`skills/vibe-knowledge-film/engine/fonts/`（OFL）
- 可选交付档（不改默认）：`--scale 2`＝4K 逻辑放大，`--fps 60`，`--hevc`，或预设 `--spec uhd60`。规格走 `VK_RENDER`，不写进 `tokens.json`。详见 `docs/视频大师-双规格升级实施计划.md`。

## 命令（zsh）

```bash
cd "/Users/ricardo.l.zeng/Desktop/代运营/视频生成自动化"
export PATH="$(pwd)/bin:$PATH"

.venv/bin/python tools/init_tokens.py
.venv/bin/python skills/vibe-knowledge-film/scripts/new_film.py films/<片名> --world C   # C=夜曲 B=寓言
# 写 films/<片名>/film.js，并按需要改 storyboard.json。不要从 tokens.json fetch。

.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --stills 2 5 8
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --sheet 16
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名>              # 默认 4 路 · 1080p30
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --jobs 1     # 强制单路
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --gpu        # ANGLE/Metal，不用 d3d11
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --vt         # H.264 VideoToolbox；失败回退 libx264 -crf 14
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --scale 2 --fps 30   # 可选 4K30
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --hevc              # 可选 HEVC（x265）；可与 --vt 正交
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --spec uhd60        # ≡ --scale 2 --fps 60 --hevc --vt
.venv/bin/python skills/vibe-knowledge-film/engine/render.py films/<片名> --events
.venv/bin/python skills/vibe-knowledge-film/engine/audio.py films/<片名>                    # 仅 synth
.venv/bin/python skills/vibe-knowledge-film/engine/audio.py films/<片名> --bgm audio/bgm.mp3 -8   # 仅用户 BGM
.venv/bin/python skills/vibe-knowledge-film/engine/audio.py films/<片名> --bgm audio/bgm.mp3 -8 --with-sfx
.venv/bin/python tools/qa_final.py films/<片名>                      # 默认 --tier hd30
.venv/bin/python tools/qa_final.py films/<片名> --tier uhd60 --file renders/final_uhd60_hevc.mp4
.venv/bin/python tools/qa_final.py films/<片名> --douyin-pad         # 仅 hd30：上下黑边 1080×1920

# 成片感知（看运动、听事件、对字幕）。第一次读字幕会下载 PaddleOCR 模型。
.venv-perceive/bin/python skills/vibe-knowledge-film/engine/watch.py films/<片名>
.venv-perceive/bin/python skills/vibe-knowledge-film/engine/listen.py films/<片名>
.venv-perceive/bin/python skills/vibe-knowledge-film/engine/read_subs.py films/<片名>
```

Mac 和 Windows 的差别：`--gpu` 用 `--use-angle=metal`（外加 GPU 光栅化），不用 `--use-angle=d3d11`。硬编开关是 `--vt`，不是 `--nvenc`。HEVC 用 `--hevc`（可与 `--vt` 正交）。ffmpeg 用仓库里的 `bin/ffmpeg`。

## 验收片 / 成片

- `films/capability_demo`：10 秒验收片，前 2 秒是大字「代码成片」
- `验收片_能力演示_10s.mp4`
- `乡村教师_夜曲简述_180s.mp4`（原片，保留不动）
- `乡村教师_快节奏_148s.mp4`（`films/village_teacher_fast`）。当时垫过一段 MusicGen，只算实验，不是这条流水线的生产声源

## 非生产实验（MusicGen）

权重是 **CC-BY-NC**。可以在本机试听，不能进抖音或商用成片。生产对白和配乐走上面的 `audio.py`。

```bash
# 已装：.venv-music + models/musicgen-small。不要放进生产步骤。
.venv-music/bin/mlx-audiogen --model musicgen \
  --weights-dir models/musicgen-small \
  --prompt "..." --seconds 30 --output audio/bgm/xxx.wav
```
