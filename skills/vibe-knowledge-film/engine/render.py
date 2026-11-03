# -*- coding: utf-8 -*-
"""逐帧 seek → 截图 → 管道进 ffmpeg。画面是 t 的纯函数，所以可以只渲一段、只截几帧、乱序截。

  python render.py <工程>                       全片 → <工程>/renders/raw.mp4（无声，默认 4 路）
  python render.py <工程> --jobs 4              与默认相同
  python render.py <工程> --jobs 1              强制单路
  python render.py <工程> --gpu                 macOS：ANGLE/Metal 光栅化（不用 d3d11）；启动失败则去掉这些参数重试
  python render.py <工程> --vt                  macOS：H.264 VideoToolbox；失败回退 libx264 -crf 14
  python render.py <工程> --hevc                HEVC（libx265）；与 --vt 正交：--vt --hevc → hevc_videotoolbox，失败退 x265（禁止静默回 H.264）
  python render.py <工程> --scale 2             逻辑 1080p ×2 → 3840×2160（注入 VK_RENDER，不写 tokens）
  python render.py <工程> --aspect 9:16        逻辑画布 1080×1920；配 --scale 2 → 2160×3840（竖屏）
  python render.py <工程> --aspect 9:16 --safe --sheet …   叠加平台安全区遮挡示意（只调试用，不进成片）
  python render.py <工程> --fps 60              交付帧率（注入 VK_RENDER）
  python render.py <工程> --spec uhd60          ≡ --scale 2 --fps 60 --hevc --vt
  python render.py <工程> --stills 2.5 8.5 21   只截几帧 → <工程>/review/s_0002.50.png
  python render.py <工程> --sheet 16            全片均匀取 16 帧拼一张 → review/sheet.jpg（开工后先看这个，再渲染）
  python render.py <工程> --sheet 3.5 9 21.5    指定时刻拼一张
  python render.py <工程> --motion 8.2 10.6     一段时间里均匀取 12 帧拼一张 → review/motion_8.2-10.6.jpg（看转场、看动作；后面可以再跟帧数）
  python render.py <工程> --clip 0 12 [名字]    只渲一段 → renders/<名字或_clip>.mp4（始终单路）
  python render.py <工程> --events              导出音效事件表 → audio/events.json（给 audio.py）
  python render.py <工程> --det                 确定性自检：同一批时刻乱序再截一遍，逐字节比
  python render.py <工程> --serve               起本地预览：浏览器开 http://127.0.0.1:8765/?play（←/→ 无，改完刷新）

工程目录里只需要 index.html + film.js。若有 tokens.json，在 goto 前注入 window.VK_TOKENS（film.js 不要 fetch）。
交付规格另注 window.VK_RENDER={scale,fps}，与 tokens 无关。
引擎（vk.js、vk-kit.js、fonts/）留在本文件所在目录，
由内置的小服务器挂到 /engine/ 下 —— 不用往每个工程里拷 40MB 字体，也没有 file:// 的跨目录字体限制。
"""
import hashlib, http.server, io, json, random, shutil, subprocess, sys, threading
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
REPO = ENGINE.parents[2]
GPU_ARGS = ["--use-angle=metal", "--enable-gpu", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"]
BASE_ARGS = ["--disable-lcd-text", "--run-all-compositor-stages-before-draw", "--force-color-profile=srgb"]
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
SAFE_OVERLAY = False  # --safe：竖屏安全区调试叠加，只配合 sheet/stills
X264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "medium"]
VT_H264 = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-pix_fmt", "yuv420p", "-b:v", "20M", "-maxrate", "24M", "-bufsize", "40M", "-allow_sw", "1"]
X265 = ["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-b:v", "50M", "-maxrate", "60M", "-bufsize", "100M", "-x265-params", "log-level=error"]
# constant_bit_rate：否则 VT 常落到数 Mbps；frames_* 由 encode_span 在分段时追加
VT_HEVC = ["-c:v", "hevc_videotoolbox", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-b:v", "50M", "-maxrate", "60M", "-bufsize", "100M", "-allow_sw", "1", "-constant_bit_rate", "true"]

class Handler(http.server.SimpleHTTPRequestHandler):
    proj = None
    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if p.startswith("/engine/"): return str(ENGINE / p[len("/engine/"):])
        return str(self.proj / p.lstrip("/")) if p != "/" else str(self.proj / "index.html")
    def do_GET(self):
        if self.path.startswith("/favicon"): self.send_response(204); self.end_headers(); return
        super().do_GET()
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()
    def log_message(self, *a): pass

def serve(proj, port=0):
    h = type("H", (Handler,), {"proj": proj})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"

def ffmpeg_bin():
    found = shutil.which("ffmpeg")
    if found: return found
    cand = REPO / "bin" / "ffmpeg"
    if cand.is_file(): return str(cand)
    sys.exit("找不到 ffmpeg。把仓库 bin/ 放进 PATH，或安装 ffmpeg。")

def probe_encoders():
    ff = ffmpeg_bin()
    try:
        out = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True)
        return (out.stdout or "") + (out.stderr or "")
    except OSError as e:
        return f"__error__:{e}"

def color_args(scale, hevc):
    # 默认档不顺手改 bt709（已知问题）；新档（scale>1 或 hevc）显式标记
    return list(BT709) if (scale > 1 or hevc) else []

def encoder_args(use_vt, use_hevc, scale=1):
    """返回 (ffmpeg_v_args, soft_fallback_args_or_None, label)。
    soft_fallback 仅用于「同编码族」回退：H.264 VT→x264，或 HEVC VT→x265。
    HEVC 路径禁止回退到 H.264。"""
    text = probe_encoders()
    color = color_args(scale, use_hevc)
    if use_hevc:
        if use_vt:
            if "hevc_videotoolbox" in text and not text.startswith("__error__"):
                print("[hevc] hevc_videotoolbox", flush=True)
                return VT_HEVC + color, X265 + color, "hevc_vt"
            print("[hevc] 未找到 hevc_videotoolbox，用 libx265", flush=True)
        else:
            print("[hevc] libx265", flush=True)
        if "libx265" not in text or text.startswith("__error__"):
            sys.exit("需要 libx265 或 hevc_videotoolbox，本机 ffmpeg 都没有。禁止静默回退 H.264。")
        return X265 + color, None, "x265"
    if use_vt:
        if text.startswith("__error__"):
            print(f"[vt] 无法探测编码器，回退 libx264 -crf 14：{text.split(':',1)[-1]}", flush=True)
            return X264 + color, None, "x264"
        if "h264_videotoolbox" not in text:
            print("[vt] 未找到 h264_videotoolbox，回退 libx264 -crf 14", flush=True)
            return X264 + color, None, "x264"
        print("[vt] h264_videotoolbox", flush=True)
        return VT_H264 + color, X264 + color, "h264_vt"
    return X264 + color, None, "x264"

def inject_tokens(pg, proj):
    p = proj / "tokens.json"
    if not p.exists(): return
    try: data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e: sys.exit(f"{p} 不是合法 JSON：{e}")
    pg.add_init_script("window.VK_TOKENS = " + json.dumps(data, ensure_ascii=True) + ";")

def inject_render(pg, scale, fps, aspect):
    payload = {"scale": int(scale)}
    if fps is not None:
        payload["fps"] = float(fps)
    if aspect:
        payload["aspect"] = aspect
    if SAFE_OVERLAY:
        payload["safe"] = "1"
    pg.add_init_script("window.VK_RENDER = " + json.dumps(payload, ensure_ascii=True) + ";")

def open_page(p, url, proj, gpu=False, scale=1, fps=None, aspect=None):
    def launch(args):
        return p.chromium.launch(channel="chrome", args=args)
    try:
        b = launch(BASE_ARGS + (GPU_ARGS if gpu else []))
    except Exception as e:
        if not gpu: raise
        print(f"[gpu] Chrome 带 Metal 光栅化启动失败，改回默认参数：{e}", flush=True)
        b = launch(BASE_ARGS)
    if aspect == "9:16":
        vw, vh = 1080 * scale, 1920 * scale
    else:
        vw, vh = 1920 * scale, 1080 * scale
    pg = b.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=1)
    pg.on("console", lambda m: m.type in ("error", "warning") and print("[page]", m.text))
    pg.on("pageerror", lambda e: print("[pageerror]", e))
    inject_render(pg, scale, fps, aspect)   # 必须在 tokens 与 goto 前
    inject_tokens(pg, proj)
    pg.goto(url)
    pg.wait_for_function("window.READY === true", timeout=180000)
    return b, pg

def shot(pg, t):
    pg.evaluate(f"seek({t})")
    return pg.screenshot(type="png", timeout=60000)

def with_page(proj, fn, gpu=False, scale=1, fps=None, aspect=None):
    from playwright.sync_api import sync_playwright
    srv, url = serve(proj)
    try:
        with sync_playwright() as p:
            b, pg = open_page(p, url, proj, gpu=gpu, scale=scale, fps=fps, aspect=aspect)
            try: return fn(pg)
            finally: b.close()
    finally: srv.shutdown()

def check_tokens(pg, proj):
    if not (proj / "tokens.json").exists(): return
    info = pg.evaluate("""() => {
        const t = window.VK_TOKENS;
        return t ? {width: t.width, height: t.height, fps: t.fps} : null;
    }""")
    width = info and info.get("width")
    print(f"VK_TOKENS.width === {width} height={info and info.get('height')} fps={info and info.get('fps')}", flush=True)
    if not info or info.get("width") != 1920 or info.get("height") != 1080 or info.get("fps") != 30:
        sys.exit(f"VK_TOKENS 不是 1920×1080×30：{info}")

def stills(proj, ts, gpu=False, scale=1, fps=None, aspect=None):
    (proj / "review").mkdir(exist_ok=True)
    def go(pg):
        check_tokens(pg, proj)
        for t in ts: (proj / f"review/s_{t:07.2f}.png").write_bytes(shot(pg, t))
    with_page(proj, go, gpu=gpu, scale=scale, fps=fps, aspect=aspect); print("stills:", len(ts))

def sheet(proj, args, name="sheet", gpu=False, scale=1, fps=None, aspect=None):
    from PIL import Image, ImageDraw, ImageFont
    (proj / "review").mkdir(exist_ok=True)
    def go(pg):
        end = pg.evaluate("END")
        ts = [float(x) for x in args] if len(args) > 1 else [round((i + .5) * end / int(args[0] if args else 16), 2) for i in range(int(args[0] if args else 16))]
        if aspect == "9:16":
            tw = 1080 // (1 if len(ts) <= 1 else 2); th = tw * 16 // 9; cols = 1 if len(ts) <= 1 else 2
        else:
            cols = 4 if len(ts) > 6 else 2 if len(ts) > 1 else 1; tw = 1920 // cols; th = tw * 9 // 16
        out = Image.new("RGB", (cols * tw, -(-len(ts) // cols) * th), (20, 20, 20)); d = ImageDraw.Draw(out)
        try: font = ImageFont.truetype(str(ENGINE / "fonts/JetBrainsMono.ttf"), 18)
        except Exception: font = ImageFont.load_default()
        for i, t in enumerate(ts):
            im = Image.open(io.BytesIO(shot(pg, t))).convert("RGB").resize((tw, th), Image.LANCZOS)
            x, y = (i % cols) * tw, (i // cols) * th; out.paste(im, (x, y))
            d.rectangle([x, y + th - 24, x + 78, y + th], fill=(0, 0, 0)); d.text((x + 5, y + th - 22), f"{t:.2f}", font=font, fill=(255, 230, 0))
        out.save(proj / f"review/{name}.jpg", quality=90); print("sheet:", proj / f"review/{name}.jpg", len(ts))
    with_page(proj, go, gpu=gpu, scale=scale, fps=fps, aspect=aspect)

def encode_span(pg, out, fps, n0, n1, enc, hevc_concat_hints=None):
    enc_use = list(enc)
    if hevc_concat_hints:
        enc_use += hevc_concat_hints
    ff = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
                           *enc_use, "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    try:
        for i in range(n0, n1):
            ff.stdin.write(shot(pg, i / fps))
            if (i - n0) % 150 == 0: print(f"  {i - n0}/{n1 - n0}", flush=True)
        ff.stdin.close()
    except BrokenPipeError:
        try: ff.stdin.close()
        except Exception: pass
    return ff.wait()

def frames(proj, out, a=0.0, b=None, gpu=False, vt=False, hevc=False, scale=1, fps_override=None, hevc_concat_hints=None, aspect=None):
    enc, fallback, label = encoder_args(vt, hevc, scale=scale)
    def go(pg):
        end, fps = pg.evaluate("END"), pg.evaluate("FPS")
        bb = end if b is None else min(b, end)
        n0, n1 = round(a * fps), round(bb * fps)
        hints = hevc_concat_hints if (hevc and vt) else None
        code = encode_span(pg, out, fps, n0, n1, enc, hevc_concat_hints=hints)
        if code != 0 and fallback is not None:
            kind = "hevc VideoToolbox → libx265" if hevc else "VideoToolbox → libx264 -crf 14"
            print(f"[enc] {label} 失败，回退 {kind}", flush=True)
            if out.exists(): out.unlink()
            code = encode_span(pg, out, fps, n0, n1, fallback)
        if code != 0:
            if hevc:
                sys.exit(f"ffmpeg HEVC 失败：{out}（不会回退 H.264）")
            sys.exit(f"ffmpeg 失败：{out}")
        print("done", out, f"{bb - a:.2f}s", f"fps={fps}", f"scale={scale}", label)
    with_page(proj, go, gpu=gpu, scale=scale, fps=fps_override, aspect=aspect)

def flag_extra(gpu, vt, hevc, scale, fps_override, aspect=None):
    extra = []
    if gpu: extra.append("--gpu")
    if vt: extra.append("--vt")
    if hevc: extra.append("--hevc")
    if scale != 1: extra += ["--scale", str(scale)]
    if fps_override is not None: extra += ["--fps", str(fps_override)]
    if aspect: extra += ["--aspect", aspect]
    if SAFE_OVERLAY: extra.append("--safe")
    return extra

def frames_parallel(proj, out, jobs, gpu=False, vt=False, hevc=False, scale=1, fps_override=None, aspect=None):
    """把全片切成 jobs 段，各开一个进程渲，再用 concat 无损拼接（每段编码参数相同、都从关键帧起）。"""
    end, fps = with_page(proj, lambda pg: (pg.evaluate("END"), pg.evaluate("FPS")), gpu=gpu, scale=scale, fps=fps_override, aspect=aspect)
    total = round(end * fps); cuts = [round(total * i / jobs) for i in range(jobs + 1)]
    spans = [(cuts[i], cuts[i + 1]) for i in range(jobs) if cuts[i + 1] > cuts[i]]
    if not spans: sys.exit("没有可渲的帧")
    parts, procs = [], []
    extra = flag_extra(gpu, vt, hevc, scale, fps_override, aspect)
    for i, (c0, c1) in enumerate(spans):
        name = f"_part{i:02d}"; parts.append(proj / f"renders/{name}.mp4")
        hints = []
        if hevc and vt:
            if i > 0: hints += ["--frames-before"]
            if i < len(spans) - 1: hints += ["--frames-after"]
        cmd = [sys.executable, str(Path(__file__).resolve()), str(proj), "--clip", repr(c0 / fps), repr(c1 / fps), name, *extra, *hints]
        procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL if i else None))
    if any(p.wait() for p in procs): sys.exit("有一段渲染失败了，先单独跑 --clip 看报错")
    lst = proj / "renders/_parts.txt"; lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    for p in parts + [lst]: p.unlink()
    print("done", out, f"{end:.2f}s", f"({len(spans)} 路并行)", f"fps={fps}", f"scale={scale}")

def events(proj, gpu=False, scale=1, aspect=None):
    (proj / "audio").mkdir(exist_ok=True)
    def go(pg):
        ev = pg.evaluate("events()"); m = pg.evaluate("({end: END, fps: FPS, meta: META})")
        # events() 内部按 spec.fps 采样；表头 fps 仍写交付 FPS 供参考，但时刻是秒
        json.dump({"end": m["end"], "fps": m["fps"], "meta": m["meta"], "events": ev}, open(proj / "audio/events.json", "w", encoding="utf-8"), ensure_ascii=False)
        print("events:", len(ev))
    with_page(proj, go, gpu=gpu, scale=scale, fps=None, aspect=aspect)

def det(proj, n=12, gpu=False, scale=1, fps=None, aspect=None):
    def go(pg):
        end = pg.evaluate("END"); r = random.Random(7); ts = [round(r.uniform(0, end), 3) for _ in range(n)]
        h1 = {t: hashlib.md5(shot(pg, t)).hexdigest() for t in ts}
        order = ts[:]; r.shuffle(order)
        bad = [t for t in order if hashlib.md5(shot(pg, t)).hexdigest() != h1[t]]
        print("deterministic" if not bad else f"NOT deterministic at {bad} —— 有东西在跨帧存状态或用了 Math.random()")
    with_page(proj, go, gpu=gpu, scale=scale, fps=fps, aspect=aspect)

def raw_out_name(scale, fps, hevc, spec_name=None, aspect=None):
    if spec_name == "uhd60":
        return "raw_uhd60.mp4"
    if scale == 1 and (fps is None or float(fps) == 30) and not hevc and not aspect:
        return "raw.mp4"
    fps_s = "30" if fps is None else str(int(float(fps)) if float(fps) == int(float(fps)) else fps)
    asp = "_916" if aspect == "9:16" else ""
    return f"raw_s{scale}_f{fps_s}{asp}{'_hevc' if hevc else ''}.mp4"

def parse_args(argv):
    gpu, vt, hevc, jobs = False, False, False, None
    scale, fps, spec_name = 1, None, None
    aspect = None
    frames_before, frames_after = False, False
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--gpu": gpu = True
        elif argv[i] == "--vt": vt = True
        elif argv[i] == "--hevc": hevc = True
        elif argv[i] == "--frames-before": frames_before = True
        elif argv[i] == "--frames-after": frames_after = True
        elif argv[i] == "--nvenc": sys.exit("本机没有 NVENC。需要硬编请用 --vt（VideoToolbox）。")
        elif argv[i] == "--spec":
            if i + 1 >= len(argv): sys.exit("--spec 需要名字，目前支持 uhd60")
            spec_name = argv[i + 1]; i += 1
            if spec_name == "uhd60":
                scale, fps, hevc, vt = 2, 60.0, True, True
            else:
                sys.exit(f"未知 --spec {spec_name}（目前只有 uhd60）")
        elif argv[i] == "--scale":
            if i + 1 >= len(argv): sys.exit("--scale 需要 1 或 2")
            scale = int(argv[i + 1]); i += 1
            if scale not in (1, 2): sys.exit("--scale 只能是 1 或 2")
        elif argv[i] == "--fps":
            if i + 1 >= len(argv): sys.exit("--fps 需要一个数字")
            fps = float(argv[i + 1]); i += 1
            if fps <= 0: sys.exit("--fps 必须 > 0")
        elif argv[i] == "--aspect":
            if i + 1 >= len(argv): sys.exit("--aspect 需要 16:9 或 9:16")
            aspect = argv[i + 1]; i += 1
            if aspect not in ("16:9", "9:16"): sys.exit("--aspect 只能是 16:9 或 9:16")
            if aspect == "16:9": aspect = None
        elif argv[i] == "--safe": pass  # 全局标志，main 里置位
        elif argv[i] == "--jobs":
            if i + 1 >= len(argv): sys.exit("--jobs 需要一个数字")
            jobs = int(argv[i + 1]); i += 1
            if jobs < 1: sys.exit("--jobs 至少为 1")
        else: rest.append(argv[i])
        i += 1
    return rest, gpu, vt, hevc, jobs, scale, fps, spec_name, frames_before, frames_after, aspect

if __name__ == "__main__":
    raw = sys.argv[1:]
    if not raw: sys.exit(__doc__)
    a, gpu, vt, hevc, jobs, scale, fps, spec_name, frames_before, frames_after, aspect = parse_args(raw)
    if "--safe" in raw:
        SAFE_OVERLAY = True
    if not a: sys.exit(__doc__)
    proj = Path(a[0]).resolve()
    if not (proj / "film.js").exists(): sys.exit(f"{proj} 里没有 film.js")
    (proj / "renders").mkdir(exist_ok=True)
    hevc_hints = []
    if frames_before: hevc_hints += ["-frames_before", "true"]
    if frames_after: hevc_hints += ["-frames_after", "true"]
    if "--serve" in a:
        srv, url = serve(proj, 8765); print("预览:", url + "?play", "（Ctrl+C 结束）")
        try: threading.Event().wait()
        except KeyboardInterrupt: pass
    elif "--stills" in a: stills(proj, [float(x) for x in a[a.index("--stills") + 1:]], gpu=gpu, scale=scale, fps=fps, aspect=aspect)
    elif "--sheet" in a: sheet(proj, a[a.index("--sheet") + 1:], gpu=gpu, scale=scale, fps=fps, aspect=aspect)
    elif "--motion" in a:
        i = a.index("--motion"); t0, t1 = float(a[i + 1]), float(a[i + 2]); n = int(a[i + 3]) if len(a) > i + 3 else 12
        sheet(proj, [repr(round(t0 + (t1 - t0) * k / (n - 1), 3)) for k in range(n)], f"motion_{t0:g}-{t1:g}", gpu=gpu, scale=scale, fps=fps, aspect=aspect)
    elif "--clip" in a:
        i = a.index("--clip"); name = a[i + 3] if len(a) > i + 3 and not str(a[i + 3]).startswith("--") else "_clip"
        frames(proj, proj / f"renders/{name}.mp4", float(a[i + 1]), float(a[i + 2]), gpu=gpu, vt=vt, hevc=hevc, scale=scale, fps_override=fps, hevc_concat_hints=hevc_hints or None, aspect=aspect)
    elif "--events" in a: events(proj, gpu=gpu, scale=1, aspect=aspect)
    elif "--det" in a: det(proj, gpu=gpu, scale=scale, fps=fps, aspect=aspect)
    else:
        out = proj / "renders" / raw_out_name(scale, fps, hevc, spec_name, aspect)
        njobs = 4 if jobs is None else jobs
        if njobs <= 1:
            frames(proj, out, gpu=gpu, vt=vt, hevc=hevc, scale=scale, fps_override=fps, aspect=aspect)
        else:
            frames_parallel(proj, out, njobs, gpu=gpu, vt=vt, hevc=hevc, scale=scale, fps_override=fps, aspect=aspect)
