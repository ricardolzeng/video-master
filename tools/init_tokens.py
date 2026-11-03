# -*- coding: utf-8 -*-
"""写出夜曲创作契约。不改 film.js / index.html，也不让片子 fetch tokens。

  python tools/init_tokens.py
      films/_template/tokens.json + storyboard.json
      films/capability_demo/tokens.json + storyboard.json

  python tools/init_tokens.py films/<片名>
      只补该工程的 tokens.json。storyboard.json 已存在则保留
      （capability_demo 与 _template 会写回本脚本里的契约）。

tokens.json 由 render.py 在 goto 前注入 window.VK_TOKENS。
storyboard.json 只描述钩子和分镜。音效仍走 film.js 的 fr.sfx
→ render.py --events → audio.py。
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOTE = (
    "创作契约，不替代 film.js。"
    "音效仍只走 film.js 的 fr.sfx → render.py --events → audio.py，本文件不驱动合成。"
    "禁止 film.js fetch tokens.json；画布契约由 render.py 在 goto 前注入 window.VK_TOKENS。"
)


def tokens():
    canvas = {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "safe": {"left": 0.05, "right": 0.05, "top": 0.04, "bottom": 0.04},
    }
    return {
        "width": canvas["width"],
        "height": canvas["height"],
        "fps": canvas["fps"],
        "canvas": canvas,
        "palette": {
            "ink": "#F8F9F8",
            "sub": "#D9D9D8",
            "en": "#86898C",
            "label": "#879399",
            "gold": "#F8D893",
            "goldLo": "#B09973",
            "ice": "#64E3F6",
            "iceHi": "#94FDFF",
            "iceLo": "#508FA6",
            "rose": "#E84B75",
            "crimson": "#CF3655",
            "deep": "#A21224",
            "violet": "#8477D0",
        },
        "optics": {"grain_opacity": 0.05},
        "typography": {
            "zh": "Noto Serif SC",
            "zhSans": "Noto Sans SC",
            "latin": "Cormorant Garamond",
            "en": "Lora",
            "mono": "JetBrains Mono",
            "typewriter": "Courier Prime",
            "subtitle": {"size": 41, "track": 0.12, "y": 939, "enSize": 29, "enY": 995},
        },
    }


TEMPLATE_BOARD = {
    "title": "",
    "world": "C",
    "duration_s": None,
    "hook": {
        "t0": 0,
        "t1": 3,
        "must_be_concrete": True,
        "beat": "前 2～3 秒必须是观众一眼能认出的具体东西，不能用抽象标题硬开场",
    },
    "beats": [],
    "note": NOTE,
}

DEMO_BOARD = {
    "title": "验收片 · 本机能力演示",
    "world": "C",
    "duration_s": 10,
    "hook": {
        "t0": 0,
        "t1": 3,
        "must_be_concrete": True,
        "beat": "章节标「00 验」与大字「代码成片」逐字点亮",
    },
    "beats": [
        {"t0": 0.0, "t1": 1.8, "on_screen": "章节标「00 验」；一行大字「代码」逐字点亮", "subtitle": None},
        {"t0": 1.8, "t1": 4.2, "on_screen": "接上「成片」；金色光点汇入中央", "subtitle": "这一秒开始，画面全部由代码画出。"},
        {"t0": 4.2, "t1": 7.2, "on_screen": "三条细线节点：选题 · 分镜 · 渲染，依次亮起并连线", "subtitle": "Cursor 在本机完成：选题、分镜、渲染。"},
        {"t0": 7.2, "t1": 10.0, "on_screen": "节点收束成一点；片名卡「视频大师」", "subtitle": "夜曲风格 · 合成配乐 · 本地出片。"},
    ],
    "note": NOTE,
}


def board_for(proj):
    if proj.name == "capability_demo":
        return DEMO_BOARD
    if proj.name == "_template":
        return TEMPLATE_BOARD
    return {
        "title": proj.name,
        "world": "C",
        "duration_s": None,
        "hook": TEMPLATE_BOARD["hook"],
        "beats": [],
        "note": NOTE,
    }


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", path)


def emit(proj, overwrite_board):
    proj = proj.resolve()
    dump(proj / "tokens.json", tokens())
    board = proj / "storyboard.json"
    if overwrite_board or not board.exists():
        dump(board, board_for(proj))
    else:
        print("keep", board)


def resolve(raw):
    p = Path(raw)
    return p.resolve() if p.is_absolute() else (ROOT / raw).resolve()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        emit(ROOT / "films" / "_template", True)
        emit(ROOT / "films" / "capability_demo", True)
    else:
        for raw in args:
            proj = resolve(raw)
            emit(proj, proj.name in ("_template", "capability_demo"))
