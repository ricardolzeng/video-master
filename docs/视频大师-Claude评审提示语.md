你是外部评审，不要改代码，不要重写引擎。请只评审「视频大师」这套本机知识短片方案是否自洽，卡点是否找对，以及下面标成「推断、尚未拍板」的需求里哪些不该做。

输出用中文，按这个顺序：
1. 方案是否自洽（十行以内）
2. 真正的卡点，和下面列出的卡点有哪些不一致
3. 推断需求：采纳 / 拒绝 / 先别做，每条给理由
4. 最小升级顺序（仍保持 seek(t) + image2pipe）。每步写改哪些文件、如何验收、不要顺手改什么
5. 明确不要再推荐的替代方案

## 最终目标

产品名是「视频大师」。它是 Mac 上用 Cursor 驱动的知识短片流水线，对标抖音「Vibe 知识大赏」那种没有口播、靠字幕和画面演算的片子。

已经在生产的形态：
- 画风默认是 C 夜曲（深黑底、细宋、蓝金、双语字幕、左上章节标）。B 寓言仍可用。
- 母版是 16:9、1920×1080、30fps、H.264。不要把默认改成 9:16，也不要把默认改成 60fps。
- 前 2～3 秒必须是观众一眼能认出的具象钩子。
- 声音生产走 film.js 的 fr.sfx → render.py --events → audio.py。无 BGM 时 loudnorm 约 -18 LUFS。
- 抖音竖版只是可选衍生：上下黑边垫成 1080×1920，默认不生成。

下一步要增加的交付能力（还没做）：
- 能可选地交出 3840×2160、HEVC、60fps。这是加一档，不是替换现在的 1080p30 默认。
- 之后会使用参考片《运气的形状》那首已有配乐。另一项目正在把这首曲子拆成节奏，用来指导字幕和章节落在哪一拍。本仓库还不消费那份节奏表。

## 当前卡点

1. 画布和截图窗口写死 1920×1080。vk.js 里 W/H 是常量；render.py 的 Playwright viewport 也是这个尺寸。现有 film.js 的坐标、字号都按 1080p 写。把窗口拉大只会放大这张 1080p 画布，不是按 4K 重画。
2. 帧率：film() 能读 spec.fps，缺省 30。tokens.json、静帧校验和 qa_final.py 把不是 1920×1080×30 的结果判失败。现有片子都没设 60。
3. 编码只接了 H.264：默认 libx264 -crf 14；可选 --vt 用 h264_videotoolbox，失败再退回 libx264。没有 --hevc。
4. 本机 bin/ffmpeg 实际还有 libx265、hevc_videotoolbox、libkvazaar。README 只写了 libx264 和 h264_videotoolbox，文档落后于二进制。没有 NVENC，也没有单独的 ffprobe，质检靠解析 ffmpeg -i。
5. 没有「开拍前的节拍表」入口。listen.py 用 librosa 事后核对成片（响度、onset、节拍估计），不能在写 film.js 之前把小节锁进分镜。
6. A 鎏金暗场已从 new_film.py 的菜单拿掉（只能 --world C 或 B）。gilt 的色板、字幕、年份栏、金字片名卡仍在 vk.js / vk-kit.js。用户要的是《运气的形状》那首配乐的节奏匹配，不是先把整套编年史画面恢复成默认模板。
7. 4K 且 60fps 时，像素约 4 倍、帧数约 2 倍。10 秒验收片现在大约 20 秒渲完；同一条走 4K60 会是数分钟。三分钟成片会明显更久。

## 当前技术方案（已在 Mac 落地，请按这个评审，不要假设还是 Windows 方案）

仓库目录名仍是「视频生成自动化」。产品名只改在 README 和验收片片名上。

底座不换：
- skills/vibe-knowledge-film/engine/vk.js：一张 Canvas，seek(t)，每一帧只由时间 t 决定。胶片颗粒是预生成噪声贴图按帧轮换，禁止 Math.random。spec.grain 优先，否则 VK_TOKENS.optics.grain_opacity，再否则 0.05。
- engine/render.py：逐帧 seek → PNG screenshot（timeout 60000）→ image2pipe → ffmpeg。全片默认 --jobs 4，--jobs 1 单路，--clip 永远单路。子进程透传 --gpu / --vt。
- 有 tokens.json 时，goto 之前 page.add_init_script 注入 window.VK_TOKENS。film.js 禁止 fetch。
- engine/audio.py：按 audio/events.json 合成。无 BGM 约 -18 LUFS；--bgm 垫外部曲子，约 -14 LUFS。
- tools/qa_final.py：硬性检查 1920×1080、距 30fps 不超过 0.1、yuv420p、首尾非死黑。响度只告警。--douyin-pad 才出竖版。
- tools/init_tokens.py：写出 films/_template 和 films/capability_demo 的 tokens.json / storyboard.json。storyboard.json 只是创作契约，不驱动 fr.sfx。
- 成片感知（事后，不参与生成）：.venv-perceive 里的 watch.py（OpenCV 运动）、listen.py（librosa）、read_subs.py（PaddleOCR 对字幕）。

Mac 和 Windows 已经分叉，不要把 Windows 参数写回来：
- --gpu 只加 --use-angle=metal、--enable-gpu、--enable-gpu-rasterization、--ignore-gpu-blocklist。不用 d3d11。启动失败则去掉这些参数重试。
- 硬编开关是 --vt，不是 --nvenc。
- ffmpeg 用仓库 bin/ffmpeg（arm64）。

验收片 films/capability_demo 为 10 秒夜曲，片名卡是「视频大师」，前 2 秒是大字「代码成片」。已用默认 4 路渲过，qa_final 通过（约 -17.1 LUFS）。乡村教师几条成片不要重渲。

声音边界：
- MusicGen / mlx-audiogen 只是本机实验，权重 CC-BY-NC，禁止作为抖音或商用声源。
- C 夜曲的生产声是 audio.py 合成。A/B 参考片用的是同一首现成配乐，拆解速度约 112.35 BPM：一句字幕大约两小节，章节落在小节的整数倍上。仓库里没有这首音频文件。

已拒绝、请不要再建议：
- 用单文件 vibe_pipeline.py 或示范 film.html 换掉夜曲引擎
- 把默认画幅改成 9:16 或把默认帧率改成 60
- 把 MusicGen 写成生产依赖
- 把 Anthropic canvas-design（anthropics/skills，只出一张 PNG/PDF 海报）接进生产。本机没装这个 skill。它的字体包以西文为主，覆盖不了思源宋体 / 黑体
- 用 Remotion、Motion Canvas 换掉 film.js

拟议中的 4K60 HEVC 接法（尚未实现，请评审这是否是最小改法）：
- 逻辑坐标保持 1920×1080。出 4K 时画布设为 3840×2160，开画前 ctx.setTransform(2,0,0,2,0,0)，这样旧 film.js 不用重写。
- fps 用已有的 spec.fps，由 tokens.canvas.fps 传入。
- 新增可选 --hevc：优先 hevc_videotoolbox，失败退 libx265，MP4 打 hvc1，像素格式先维持 yuv420p。audio.py 继续 -c:v copy。
- qa 分成两档：默认仍是 1080p30 H.264；只有显式的高规格档才检查 3840×2160、约 60fps、HEVC。
- 颗粒贴图现在是 480×270 拉满全屏，4K 下会糊，需要按成片尺寸重做。

## 我没有明说、但是你必须一并评审的需求

这些是从制作约束推出来的，用户还没有逐条确认。请标明采纳、拒绝或先别做。

1. 1080p30 H.264 必须继续是默认生产档。4K60 HEVC 是可选档，调用时才启用。静默改默认会造成已有夜曲片和质检标准一起失效。
2. 4K 应缩放逻辑坐标，而不是要求把乡村教师和验收片的 film.js 坐标全部重写。
3. 节奏拆分留在另一个项目。本仓库只应定义一份可消费的节拍契约（BPM、小节、强拍、段落能量），在写分镜时对齐字幕和章节。不要把拆拍器做进这个仓库。
4. listen.py 保持成片事后核对。它不能代替开拍前的节拍表。
5. 使用《运气的形状》的配乐，不等于把 A 鎏金暗场恢复成 new_film.py 的默认世界。A 的画面是编年史（年份栏、实物道具、金字卡），成本高，而且菜单里已经拿掉。配乐可以垫在夜曲或寓言上。若评审认为节奏匹配必须连外观一起恢复，请单独论证，不要当成既定需求。
6. 这首配乐是参考片里的录音，仓库未包含该文件。发布成片需要使用权。评审可以指出风险，但不要设计下载或翻录步骤。
7. 垫外部 BGM 时响度目标是约 -14 LUFS，纯合成夜曲仍是约 -18。qa 的告警不能用一个阈值打两档。
8. 9:16 只作为 --douyin-pad 衍生。母版保持 16:9。4K 母版若要竖版，应另定规则，不要把 3840×2160 直接裁成抖音成片。
9. 产品名「视频大师」和磁盘目录「视频生成自动化」不是一回事。评审不要建议为了改名去移动仓库路径。
10. Mac 的 GPU / 编码器参数不能抄 Windows 的 d3d11 和 NVENC。若建议 Windows 同时支持 4K60 HEVC，请把它写成另一档适配，而不是改 Mac 已经验证过的 --gpu / --vt。
11. 中文成片依赖仓库里的 OFL 思源字体。不要改成 canvas-design 的西文字体包。
12. 升级时不要重渲 films/village_teacher*。验收仍用 films/capability_demo 的短片，先证明一档新规格，再考虑长片。

## 请重点回答的问题

- 双规格（1080p30 H.264 默认 + 可选 4K60 HEVC）是否比「直接把默认改成 4K60」更合理？
- ctx.setTransform(2,…) 复用旧 film.js，会在字号、线宽、辉光、颗粒上坏掉什么？
- 节拍契约最少要哪些字段，才能让另一项目的拆拍结果约束 storyboard，同时不取代 fr.sfx → audio.py？
- --hevc 与现有 --vt（H.264 VideoToolbox）应该并存，还是合成一个编码器选择？失败回退到 libx265 还是 libx264？
- 以 4 路并行、PNG image2pipe 估算，什么时长的片子不该走 4K60？
