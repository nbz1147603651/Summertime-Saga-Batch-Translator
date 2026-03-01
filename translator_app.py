"""
Summertime Saga 批量翻译工具
基于 Ren'Py Modding API，通过大模型对游戏对话进行批量翻译
"""

from __future__ import annotations

import json
import os
import pickle
import queue
import re
import shutil
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------
try:
    import customtkinter as ctk
    from customtkinter import CTkFont
except ImportError:
    print("正在安装 customtkinter，请稍候...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter", "-q"])
    import customtkinter as ctk
    from customtkinter import CTkFont

try:
    from openai import OpenAI
except ImportError:
    print("正在安装 openai，请稍候...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openai", "-q"])
    from openai import OpenAI

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# unrpyc 反编译支持（可选，运行时自动安装）
_unrpyc_mod = None
try:
    import unrpyc as _unrpyc_mod  # type: ignore[import]
    HAS_UNRPYC = True
except ImportError:
    HAS_UNRPYC = False

# ---------------------------------------------------------------------------
# RPA 解压模块
# ---------------------------------------------------------------------------

class RPAExtractor:
    """解压 Ren'Py .rpa 存档文件"""

    MAGIC_V3 = b"RPA-3.0 "
    MAGIC_V2 = b"RPA-2.0 "

    def __init__(self, rpa_path: str | Path):
        self.rpa_path = Path(rpa_path)

    def get_index(self) -> dict[str, list[tuple[int, int, bytes]]]:
        with open(self.rpa_path, "rb") as f:
            magic = f.read(8)
            f.seek(0)
            header = f.readline()

        if magic == self.MAGIC_V3:
            return self._index_v3(header)
        elif magic == self.MAGIC_V2:
            return self._index_v2(header)
        else:
            raise ValueError(f"不支持的 RPA 格式: {self.rpa_path.name}")

    def _index_v3(self, header: bytes) -> dict:
        parts = header.split()
        offset = int(parts[1], 16)
        key = int(parts[2], 16)
        with open(self.rpa_path, "rb") as f:
            f.seek(offset)
            data = zlib.decompress(f.read())
        index = pickle.loads(data)
        # 解密偏移量
        result = {}
        for name, entries in index.items():
            decoded = []
            for entry in entries:
                if len(entry) == 2:
                    o, l = entry
                    decoded.append((o ^ key, l ^ key, b""))
                else:
                    o, l, prefix = entry
                    decoded.append((o ^ key, l ^ key, prefix))
            fname = name.decode("utf-8") if isinstance(name, bytes) else name
            result[fname] = decoded
        return result

    def _index_v2(self, header: bytes) -> dict:
        parts = header.split()
        offset = int(parts[1], 16)
        with open(self.rpa_path, "rb") as f:
            f.seek(offset)
            data = zlib.decompress(f.read())
        index = pickle.loads(data)
        result = {}
        for name, entries in index.items():
            fname = name.decode("utf-8") if isinstance(name, bytes) else name
            result[fname] = [(o, l, b"") for o, l in entries]
        return result

    def extract_all(self, dest_dir: str | Path,
                    progress_callback=None) -> list[str]:
        """解压所有文件到目标目录，返回解压的文件路径列表"""
        dest = Path(dest_dir)
        index = self.get_index()
        extracted = []
        total = len(index)

        with open(self.rpa_path, "rb") as f:
            for i, (name, entries) in enumerate(index.items()):
                out_path = dest / name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as out:
                    for offset, length, prefix in entries:
                        out.write(prefix)
                        if length > 0:
                            f.seek(offset)
                            out.write(f.read(length))
                extracted.append(str(out_path))
                if progress_callback:
                    progress_callback(i + 1, total, name)
        return extracted

    def list_files(self) -> list[str]:
        return list(self.get_index().keys())


# ---------------------------------------------------------------------------
# RPY 解析模块
# ---------------------------------------------------------------------------

class Label:
    """表示一个 Ren'Py 标签（对话标签）"""
    __slots__ = ("name", "raw_lines", "dialogues")

    def __init__(self, name: str):
        self.name = name
        self.raw_lines: list[str] = []
        self.dialogues: list[tuple[int, str, str]] = []
        # (在 raw_lines 中的索引, 角色名, 对话文本)


class RPYParser:
    """解析 .rpy 文件，提取对话标签和文本"""

    # 匹配角色名 + 对话字符串，或纯对话字符串
    DIALOGUE_RE = re.compile(
        r'^(\s+)'                     # 缩进
        r'(?:([a-zA-Z_]\w*)\s+)?'     # 可选角色名
        r'"((?:[^"\\]|\\.)*)"'        # 对话文本（双引号，支持转义）
    )
    LABEL_RE = re.compile(r'^label\s+([a-zA-Z_][\w.]*)\s*(\([^)]*\))?\s*:')

    @staticmethod
    def parse_file(rpy_path: str | Path) -> list[Label]:
        path = Path(rpy_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        labels: list[Label] = []
        current: Label | None = None

        for lineno, line in enumerate(text.splitlines()):
            stripped = line.rstrip()

            m_label = RPYParser.LABEL_RE.match(stripped)
            if m_label:
                current = Label(m_label.group(1))
                labels.append(current)
                current.raw_lines.append(stripped)
                continue

            if current is not None:
                current.raw_lines.append(stripped)
                m_dlg = RPYParser.DIALOGUE_RE.match(stripped)
                if m_dlg:
                    char = m_dlg.group(2) or ""
                    text_content = m_dlg.group(3)
                    idx = len(current.raw_lines) - 1
                    current.dialogues.append((idx, char, text_content))

        return labels

    @staticmethod
    def scan_directory(directory: str | Path,
                       filename_filter: str = "dialogues") -> tuple[list[tuple[Path, list[Label]]], dict]:
        """扫描目录，找到所有含对话的 rpy 文件，返回 (结果列表, 诊断信息字典)"""
        directory = Path(directory)
        results = []
        diagnostics = {
            "rpy_found": 0,
            "rpy_with_dialogues": 0,
            "rpyc_found": 0,
            "is_compiled": False,
            "warning": None,
        }
        
        # 检查是否全是编译文件
        rpy_files = list(directory.rglob("*.rpy"))
        rpyc_files = list(directory.rglob("*.rpyc"))
        
        diagnostics["rpy_found"] = len(rpy_files)
        diagnostics["rpyc_found"] = len(rpyc_files)
        
        if rpyc_files and not rpy_files:
            diagnostics["is_compiled"] = True
            diagnostics["warning"] = (
                "检测到的全是编译版本文件（.rpyc）。\n"
                "此版本无法直接翻译。需要源代码版本（.rpy 文件）。\n\n"
                "原因：游戏发布版会被编译成 .rpyc 以保护源代码。\n\n"
                "解决方案：\n"
                "1. 如果你有权限，从官方开发者或源代码仓库获取 .rpy 源代码版本\n"
                "2. 或者使用官方提供的开发工具进行反编译\n"
                "3. 或者手动在游戏内创建翻译 Mod（通过 Ren'Py Modding API）"
            )
            return results, diagnostics
        
        # 扫描 .rpy 文件（排除翻译输出目录）
        for rpy in rpy_files:
            # 跳过位于 translation 子目录中的文件（翻译工具的输出目录，避免 _zh_zh 二次翻译）
            if "translation" in [p.name for p in rpy.parents]:
                continue
            if filename_filter in rpy.stem or filename_filter == "*":
                labels = RPYParser.parse_file(rpy)
                labels_with_dlg = [l for l in labels if l.dialogues]
                if labels_with_dlg:
                    results.append((rpy, labels_with_dlg))
                    diagnostics["rpy_with_dialogues"] += len(labels_with_dlg)
        
        return results, diagnostics

    @staticmethod
    def build_translated_label(label: Label, translations: dict[str, str],
                               lang_code: str) -> str:
        """根据翻译字典生成翻译后的标签代码"""
        lines = list(label.raw_lines)

        # 重命名标签
        lines[0] = RPYParser.LABEL_RE.sub(
            lambda m: f"label {m.group(1)}_{lang_code}{'(' + m.group(2)[1:-1] + ')' if m.group(2) else ''}:",
            lines[0]
        )

        # 替换对话文本
        for idx, char, orig_text in label.dialogues:
            if orig_text in translations:
                translated = translations[orig_text].replace('"', '\\"')
                old_line = lines[idx]
                # 保留缩进和角色名，替换文本
                new_line = re.sub(
                    r'"(?:[^"\\]|\\.)*"',
                    f'"{translated}"',
                    old_line,
                    count=1
                )
                lines[idx] = new_line

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# LLM 翻译引擎
# ---------------------------------------------------------------------------

class TranslationEngine:
    """通过大模型 API 进行文本翻译"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 target_lang: str = "简体中文",
                 batch_size: int = 20,
                 custom_instructions: str = "",
                 term_dict: dict[str, str] | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.target_lang = target_lang
        self.batch_size = batch_size
        self.custom_instructions = custom_instructions.strip()
        self.term_dict = term_dict or {}
        self._client: OpenAI | None = None
        self._failed_texts: set[str] = set()
        self._last_error = ""

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url if self.base_url else None
            )
        return self._client

    def reset_failed(self):
        """重置失败记录，供新一轮翻译前调用"""
        self._failed_texts: set[str] = set()
        self._last_error = ""

    @staticmethod
    def _protect_placeholders(text: str) -> tuple[str, dict]:
        """将 Ren'Py 标签/变量替换为 token，返回 (处理后文本, token->原文 字典)"""
        # 匹配 {tag} {/tag} {tag=val} {#comment} 和 [variable]
        pattern = re.compile(r'\{[^}]+\}|\[[^\]]+\]')
        token_map: dict[str, str] = {}
        counter = [0]
        def _rep(m: re.Match) -> str:
            tok = f"\u27ea{counter[0]}\u27eb"  # ⟨n⟩ 不常见字符，不会被 AI 翻译
            token_map[tok] = m.group(0)
            counter[0] += 1
            return tok
        protected = pattern.sub(_rep, text)
        return protected, token_map

    @staticmethod
    def _restore_placeholders(text: str, token_map: dict) -> str:
        """将 token 还原为原始 Ren'Py 标签/变量"""
        for tok, orig in token_map.items():
            text = text.replace(tok, orig)
        return text

    def _make_prompt(self, texts: list[str]) -> str:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
        # 术语对照表提示
        term_hint = ""
        if self.term_dict:
            term_lines = "\n".join(f"  - {k} → {v}" for k, v in self.term_dict.items())
            term_hint = f"- 术语对照表（请严格按照对应翻译）：\n{term_lines}\n"
        # 自定义风格指令
        style_hint = f"- {self.custom_instructions}\n" if self.custom_instructions else ""
        return (
            f"你是一位专业的游戏本地化翻译员。\n"
            f"请将以下英文游戏对话翻译为{self.target_lang}。\n"
            f"要求：\n"
            f"- 文本中形如 ⟨0⟩ ⟨1⟩ 的标记是占位符，请原样保留，不可翻译或删除\n"
            f"- 保留 \\n 换行符\n"
            f"- 语气自然，符合角色性格\n"
            f"{term_hint}"
            f"{style_hint}"
            f"- 仅输出翻译结果，按原编号返回，格式：序号. 翻译内容\n\n"
            f"{numbered}"
        )

    def translate_batch(self, texts: list[str]) -> dict[str, str]:
        """翻译一批文本，返回 原文->译文 字典"""
        if not texts:
            return {}

        client = self._get_client()
        results = {}

        # 分批处理
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i: i + self.batch_size]

            # ── 占位符保护：先提取 {tag}/[var]，翻译后再还原 ──────────────────
            protected_chunk: list[str] = []
            token_maps: list[dict] = []
            for t in chunk:
                p, tmap = TranslationEngine._protect_placeholders(t)
                protected_chunk.append(p)
                token_maps.append(tmap)

            prompt = self._make_prompt(protected_chunk)

            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                raw = resp.choices[0].message.content or ""
                parsed_protected = self._parse_response(raw, protected_chunk)
                # 还原占位符，并以原文为 key 存入结果
                for orig, (prot, tmap) in zip(chunk, zip(protected_chunk, token_maps)):
                    translated = parsed_protected.get(prot, prot)
                    restored = TranslationEngine._restore_placeholders(translated, tmap)
                    # 术语对照表后处理替换（在译文中直接替换英文术语为目标语言）
                    for en_term, zh_term in self.term_dict.items():
                        restored = re.sub(re.escape(en_term), zh_term, restored, flags=re.IGNORECASE)
                    results[orig] = restored
            except Exception as e:
                # API失败时保留原文，记录到 failed 集合，但不中断后续批次
                for t in chunk:
                    results[t] = t
                    self._failed_texts.add(t)
                self._last_error = str(e)

        return results

    @staticmethod
    def _parse_response(raw: str, originals: list[str]) -> dict[str, str]:
        result = {}
        lines = raw.strip().splitlines()
        # 匹配 "1. 翻译内容"
        pattern = re.compile(r'^(\d+)\.\s*(.*)')
        parsed_map: dict[int, str] = {}
        for line in lines:
            m = pattern.match(line.strip())
            if m:
                idx = int(m.group(1)) - 1
                parsed_map[idx] = m.group(2).strip()
        for i, orig in enumerate(originals):
            if i in parsed_map and parsed_map[i]:
                result[orig] = parsed_map[i]
            else:
                result[orig] = orig
        return result

    def test_connection(self) -> tuple[bool, str]:
        """测试 API 连接"""
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "回复 OK"}],
                max_tokens=10,
            )
            return True, resp.choices[0].message.content or "OK"
        except Exception as e:
            return False, str(e)


# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    """Summertime Saga 游戏翻译工具主界面"""

    # 颜色系统
    ACCENT   = "#7B61FF"
    ACCENT_H = "#9D89FF"
    BG_DARK  = "#0F0F17"
    BG_PANEL = "#1A1A2E"
    BG_CARD  = "#16213E"
    TEXT_PRI = "#E8E8F0"
    TEXT_SEC = "#8888AA"
    SUCCESS  = "#4CAF77"
    WARNING  = "#F5A623"
    DANGER   = "#F04747"

    # ---------------------------------------------------------------------------
    # 初始化
    # ---------------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Summertime Saga 翻译工具 v1.0")
        self.geometry("1200x760")
        self.minsize(960, 640)
        self.configure(fg_color=self.BG_DARK)

        # 状态变量
        self.game_dir        = ctk.StringVar(value="")
        self.extract_dir     = ctk.StringVar(value="")
        self.api_key         = ctk.StringVar(value="")
        self.api_base        = ctk.StringVar(value="https://api.openai.com/v1")
        self.api_model       = ctk.StringVar(value="gpt-4o-mini")
        self.lang_code       = ctk.StringVar(value="zh")
        self.lang_name       = ctk.StringVar(value="简体中文")
        self.batch_size      = ctk.IntVar(value=20)
        self.file_filter     = ctk.StringVar(value="dialogues")
        self.renpy_sdk_dir   = ctk.StringVar(value="")
        self.custom_instructions = ctk.StringVar(value="")  # 翻译风格指令
        self.is_translating  = False
        self._stop_flag      = False
        self._decompiling    = False
        self._log_queue: queue.Queue = queue.Queue()   # items: (textbox_widget, text)
        self._progress_queue: queue.Queue = queue.Queue()  # items: (cur, total, msg)

        self._scanned_files: list[tuple[Path, list[Label]]] = []
        self._file_vars: list[tuple[ctk.BooleanVar, Path, list[Label]]] = []
        self._total_dialogues = 0
        self._translated_count = 0

        # 暫停/继续控制
        self._pause_event = threading.Event()
        self._pause_event.set()  # 默认运行状态

        # 补翻修复状态
        self._repair_dir       = ctk.StringVar(value="")
        self._is_repairing     = False
        self._repair_results: list[tuple[str, int]] = []  # [(filename, untranslated_count)]

        self._build_ui()
        self._load_config()
        self._start_queue_polling()

    # ---------------------------------------------------------------------------
    # UI 构建
    # ---------------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        # 内容区
        self.content_frame = ctk.CTkFrame(self, fg_color=self.BG_DARK, corner_radius=0)
        self.content_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 0))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(1, weight=0)

        # 页面容器
        self.page_frame = ctk.CTkFrame(self.content_frame, fg_color=self.BG_DARK, corner_radius=0)
        self.page_frame.grid(row=0, column=0, sticky="nsew")
        self.page_frame.grid_columnconfigure(0, weight=1)
        self.page_frame.grid_rowconfigure(0, weight=1)

        # 底部状态栏
        self._build_statusbar()

        # 所有页面
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_page_home()
        self._build_page_extract()
        self._build_page_scan()
        self._build_page_settings()
        self._build_page_translate()
        self._build_page_repair()

        self._show_page("home")

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=self.BG_PANEL, corner_radius=0, width=220)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(10, weight=1)

        # Logo / 标题
        logo_frame = ctk.CTkFrame(sidebar, fg_color="#0D0D1A", corner_radius=0, height=80)
        logo_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        logo_frame.grid_propagate(False)
        ctk.CTkLabel(
            logo_frame,
            text="✦ STS 翻译工具",
            font=CTkFont(size=16, weight="bold"),
            text_color=self.ACCENT_H,
        ).place(relx=0.5, rely=0.5, anchor="center")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("home",      "🏠  首页"),
            ("extract",   "📦  解压存档"),
            ("scan",      "🔍  扫描文本"),
            ("settings",  "⚙️  API 设置"),
            ("translate", "🚀  开始翻译"),
            ("repair",    "🔄  补翻修复"),
        ]
        for i, (key, label) in enumerate(nav_items):
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                font=CTkFont(size=13),
                fg_color="transparent",
                hover_color=self.BG_CARD,
                text_color=self.TEXT_SEC,
                corner_radius=8,
                height=44,
                command=lambda k=key: self._show_page(k),
            )
            btn.grid(row=i + 1, column=0, sticky="ew", padx=10, pady=3)
            self.nav_buttons[key] = btn

        # 版本标签
        ctk.CTkLabel(
            sidebar,
            text="v1.0  •  Powered by LLM",
            font=CTkFont(size=11),
            text_color="#555577",
        ).grid(row=11, column=0, pady=12)

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.content_frame, fg_color=self.BG_PANEL,
                           corner_radius=0, height=56)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            bar, text="就绪",
            font=CTkFont(size=12),
            text_color=self.TEXT_SEC,
        )
        self.status_label.grid(row=0, column=0, padx=16, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            bar, mode="determinate",
            progress_color=self.ACCENT,
            height=8,
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=(0, 16), sticky="ew")

        self.progress_label = ctk.CTkLabel(
            bar, text="0 / 0",
            font=CTkFont(size=12),
            text_color=self.TEXT_SEC,
            width=80,
        )
        self.progress_label.grid(row=0, column=2, padx=(0, 16))

    # ── 首页 ──────────────────────────────────────────────────────────────────

    def _build_page_home(self):
        page = ctk.CTkScrollableFrame(self.page_frame, fg_color=self.BG_DARK,
                                      corner_radius=0)
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            page,
            text="Summertime Saga 批量翻译工具",
            font=CTkFont(size=24, weight="bold"),
            text_color=self.TEXT_PRI,
        ).pack(padx=30, pady=(30, 4))

        ctk.CTkLabel(
            page,
            text="基于 Ren'Py Modding API，通过大语言模型实现游戏对话全自动汉化",
            font=CTkFont(size=13),
            text_color=self.TEXT_SEC,
        ).pack(padx=30, pady=(0, 24))

        # 工作流程卡片
        steps = [
            ("1", "📦 解压存档", "将 src.rpa 解压到本地，获取可编辑的 .rpy 脚本文件"),
            ("2", "🔍 扫描文本", "扫描对话文件，列出所有含英文对话的标签"),
            ("3", "⚙️ 配置 API",  "填入 OpenAI / DeepSeek / 其他兼容接口的密钥与参数"),
            ("4", "🚀 开始翻译", "一键批量翻译，自动生成符合 Modding API 规范的汉化文件"),
        ]

        for num, title, desc in steps:
            card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
            card.pack(fill="x", padx=30, pady=6)
            card.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                card,
                text=num,
                font=CTkFont(size=20, weight="bold"),
                text_color=self.ACCENT,
                width=50,
            ).grid(row=0, column=0, rowspan=2, padx=16, pady=14, sticky="ns")

            ctk.CTkLabel(
                card, text=title,
                font=CTkFont(size=14, weight="bold"),
                text_color=self.TEXT_PRI, anchor="w",
            ).grid(row=0, column=1, sticky="w", padx=8, pady=(12, 2))

            ctk.CTkLabel(
                card, text=desc,
                font=CTkFont(size=12),
                text_color=self.TEXT_SEC, anchor="w",
            ).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 12))

        # 输出说明
        info = ctk.CTkFrame(page, fg_color="#1A1A35", corner_radius=12,
                            border_width=1, border_color=self.ACCENT)
        info.pack(fill="x", padx=30, pady=16)
        ctk.CTkLabel(
            info,
            text="📌  翻译输出说明",
            font=CTkFont(size=13, weight="bold"),
            text_color=self.ACCENT_H, anchor="w",
        ).pack(padx=16, pady=(12, 4), anchor="w")
        ctk.CTkLabel(
            info,
            text=(
                "• 每个对话标签（如 bank_liu_account_info）将生成对应语言标签"
                "（如 bank_liu_account_info_zh）\n"
                "• 同时生成 set_language.rpy，设置 Game.language = \"zh\"\n"
                "• 若包含过场动画文本，还将生成 text_filter.rpy（config.say_menu_text_filter）\n"
                "• 所有输出文件放置于游戏目录 game/scripts/translation/ 下，直接运行即可生效"
            ),
            font=CTkFont(size=12),
            text_color=self.TEXT_SEC,
            anchor="w",
            justify="left",
            wraplength=700,
        ).pack(padx=16, pady=(0, 12), anchor="w")

        self.pages["home"] = page

    # ── 解压存档页 ─────────────────────────────────────────────────────────────

    def _build_page_extract(self):
        page = ctk.CTkFrame(self.page_frame, fg_color=self.BG_DARK, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        self._section_title(page, "📦 解压 RPA 存档", row=0)

        # 游戏目录
        card = self._card(page, row=1)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="游戏根目录", font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI).grid(row=0, column=0, columnspan=3,
                                                    sticky="w", padx=16, pady=(14, 6))
        ctk.CTkLabel(card, text="包含 game/ 文件夹的游戏安装目录",
                     font=CTkFont(size=11), text_color=self.TEXT_SEC
                     ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16)

        entry = ctk.CTkEntry(card, textvariable=self.game_dir,
                             placeholder_text="例如：D:/Games/summertimesaga",
                             font=CTkFont(size=12), height=36)
        entry.grid(row=2, column=0, columnspan=2, sticky="ew",
                   padx=(16, 8), pady=10)
        ctk.CTkButton(card, text="浏览", width=80, height=36,
                      command=self._browse_game_dir,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      ).grid(row=2, column=2, padx=(0, 16), pady=10)

        ctk.CTkLabel(card, text="解压输出目录", font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI).grid(row=3, column=0, columnspan=3,
                                                    sticky="w", padx=16, pady=(6, 4))
        entry2 = ctk.CTkEntry(card, textvariable=self.extract_dir,
                              placeholder_text="默认与游戏目录相同（留空则放在 game/ 内）",
                              font=CTkFont(size=12), height=36)
        entry2.grid(row=4, column=0, columnspan=2, sticky="ew",
                    padx=(16, 8), pady=(0, 14))
        ctk.CTkButton(card, text="浏览", width=80, height=36,
                      command=self._browse_extract_dir,
                      fg_color=self.BG_CARD, hover_color="#2A2A4E",
                      ).grid(row=4, column=2, padx=(0, 16), pady=(0, 14))

        # 存档列表
        card2 = self._card(page, row=2)
        card2.grid_columnconfigure(0, weight=1)
        card2.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card2, fg_color="transparent", corner_radius=0)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 6))
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="检测到的 .rpa 存档",
                     font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(hdr, text="🔄 刷新", width=80, height=30,
                      command=self._refresh_rpa_list,
                      fg_color=self.BG_CARD, hover_color="#2A2A4E",
                      font=CTkFont(size=12),
                      ).grid(row=0, column=1)

        self.rpa_list_frame = ctk.CTkScrollableFrame(
            card2, fg_color="#0D0D1A", corner_radius=8, height=140)
        self.rpa_list_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                                 padx=16, pady=(0, 12))
        self.rpa_list_frame.grid_columnconfigure(0, weight=1)

        self.rpa_vars: dict[str, ctk.BooleanVar] = {}
        self._rpa_rows: list = []

        # 日志 + 按钮
        log_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        log_card.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 12))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        btn_bar = ctk.CTkFrame(log_card, fg_color="transparent")
        btn_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        btn_bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(btn_bar, text="解压日志", font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(btn_bar, text="🚀  开始解压", height=34,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      font=CTkFont(size=13, weight="bold"),
                      command=self._start_extract,
                      ).grid(row=0, column=1, padx=4)

        self.extract_log = ctk.CTkTextbox(
            log_card, fg_color="#0D0D1A", text_color=self.TEXT_SEC,
            font=CTkFont(family="Consolas", size=11), corner_radius=8)
        self.extract_log.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))

        self.pages["extract"] = page

    # ── 扫描文本页 ─────────────────────────────────────────────────────────────

    def _build_page_scan(self):
        page = ctk.CTkFrame(self.page_frame, fg_color=self.BG_DARK, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        self._section_title(page, "🔍 扫描对话文本", row=0)

        top_card = self._card(page, row=1)
        top_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(top_card, text="脚本目录",
                     text_color=self.TEXT_PRI, font=CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(top_card, text="（src.rpa 解压后的目录，包含 scripts/ 子目录）",
                     text_color=self.TEXT_SEC, font=CTkFont(size=11)
                     ).grid(row=0, column=1, padx=4, pady=(12, 2), sticky="w")

        self.scan_dir_var = ctk.StringVar(value="")
        scan_entry = ctk.CTkEntry(top_card, textvariable=self.scan_dir_var,
                                  placeholder_text="解压目录路径",
                                  font=CTkFont(size=12), height=36)
        scan_entry.grid(row=1, column=0, columnspan=2, sticky="ew",
                        padx=(16, 8), pady=6)
        ctk.CTkButton(top_card, text="浏览", width=80, height=36,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      command=self._browse_scan_dir,
                      ).grid(row=1, column=2, padx=(0, 16))

        ctk.CTkLabel(top_card, text="文件名过滤",
                     text_color=self.TEXT_PRI, font=CTkFont(size=13, weight="bold")
                     ).grid(row=2, column=0, padx=16, pady=(10, 2), sticky="w")
        ctk.CTkLabel(top_card, text="只处理文件名包含该关键词的 .rpy 文件（填 * 表示全部）",
                     text_color=self.TEXT_SEC, font=CTkFont(size=11)
                     ).grid(row=2, column=1, columnspan=2, padx=4, pady=(10, 2), sticky="w")

        filter_row = ctk.CTkFrame(top_card, fg_color="transparent")
        filter_row.grid(row=3, column=0, columnspan=3, sticky="ew",
                        padx=16, pady=(0, 14))
        filter_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(filter_row, textvariable=self.file_filter,
                     font=CTkFont(size=12), height=36
                     ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(filter_row, text="🔍  扫描", height=36,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      font=CTkFont(size=13, weight="bold"),
                      command=self._start_scan
                      ).grid(row=0, column=1)

        # 文件列表
        list_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        list_card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        list_card.grid_columnconfigure(0, weight=1)
        list_card.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(list_card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 6))
        hdr.grid_columnconfigure(0, weight=1)

        self.scan_summary = ctk.CTkLabel(
            hdr, text="尚未扫描",
            font=CTkFont(size=12), text_color=self.TEXT_SEC)
        self.scan_summary.grid(row=0, column=0, sticky="w")

        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.grid(row=0, column=1)
        ctk.CTkButton(btn_row, text="全选", width=60, height=28,
                      fg_color=self.BG_DARK, hover_color="#2A2A4E",
                      font=CTkFont(size=12),
                      command=lambda: self._select_all_files(True)
                      ).grid(row=0, column=0, padx=2)
        ctk.CTkButton(btn_row, text="取消", width=60, height=28,
                      fg_color=self.BG_DARK, hover_color="#2A2A4E",
                      font=CTkFont(size=12),
                      command=lambda: self._select_all_files(False)
                      ).grid(row=0, column=1, padx=2)

        self.file_list_frame = ctk.CTkScrollableFrame(
            list_card, fg_color="#0D0D1A", corner_radius=8)
        self.file_list_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.file_list_frame.grid_columnconfigure(0, weight=1)

        self.pages["scan"] = page

    # ── API 设置页 ──────────────────────────────────────────────────────────────

    def _build_page_settings(self):
        page = ctk.CTkScrollableFrame(self.page_frame, fg_color=self.BG_DARK, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)

        self._section_title(page, "⚙️ API 设置", pack=True)

        # API 参数卡片
        card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        card.pack(fill="x", padx=20, pady=6)
        card.grid_columnconfigure(1, weight=1)

        fields = [
            ("API Key",    self.api_key,   "sk-...（OpenAI / DeepSeek / 其他兼容接口）", False),
            ("Base URL",   self.api_base,  "https://api.openai.com/v1",                  False),
            ("模型名称",   self.api_model, "gpt-4o-mini / deepseek-chat / ...",          False),
        ]
        for i, (label, var, hint, is_pw) in enumerate(fields):
            ctk.CTkLabel(card, text=label, font=CTkFont(size=13, weight="bold"),
                         text_color=self.TEXT_PRI, anchor="w", width=100
                         ).grid(row=i, column=0, padx=(16, 8), pady=10, sticky="w")
            ctk.CTkEntry(card, textvariable=var, placeholder_text=hint,
                         font=CTkFont(size=12), height=36,
                         show="●" if is_pw else "",
                         ).grid(row=i, column=1, sticky="ew", padx=(0, 16), pady=10)

        # 翻译参数
        card2 = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        card2.pack(fill="x", padx=20, pady=6)
        card2.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card2, text="翻译参数",
                     font=CTkFont(size=14, weight="bold"),
                     text_color=self.TEXT_PRI
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 6))

        params = [
            ("目标语言名称", self.lang_name, "简体中文 / 繁體中文 / 日本語 / ..."),
            ("语言代码",     self.lang_code, "zh / tw / ja / ko / ...（标签后缀）"),
        ]
        for i, (label, var, hint) in enumerate(params):
            ctk.CTkLabel(card2, text=label, font=CTkFont(size=13, weight="bold"),
                         text_color=self.TEXT_PRI, anchor="w", width=120
                         ).grid(row=i + 1, column=0, padx=(16, 8), pady=8, sticky="w")
            ctk.CTkEntry(card2, textvariable=var, placeholder_text=hint,
                         font=CTkFont(size=12), height=36,
                         ).grid(row=i + 1, column=1, sticky="ew", padx=(0, 16), pady=8)

        ctk.CTkLabel(card2, text=f"每批翻译数量",
                     font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI, anchor="w", width=120
                     ).grid(row=3, column=0, padx=(16, 8), pady=8, sticky="w")
        ctk.CTkSlider(card2, from_=5, to=50, number_of_steps=9,
                      variable=self.batch_size,
                      progress_color=self.ACCENT,
                      button_color=self.ACCENT,
                      ).grid(row=3, column=1, sticky="ew", padx=(0, 16), pady=8)

        # 说明卡片：支持的 API 服务
        info_card = ctk.CTkFrame(page, fg_color="#1A1A35", corner_radius=12,
                                 border_width=1, border_color=self.ACCENT)
        info_card.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(info_card, text="✅  支持的 API 平台",
                     font=CTkFont(size=13, weight="bold"),
                     text_color=self.ACCENT_H, anchor="w"
                     ).pack(padx=16, pady=(12, 4), anchor="w")
        platforms = [
            ("OpenAI",      "https://api.openai.com/v1",            "gpt-4o-mini / gpt-4o"),
            ("DeepSeek",    "https://api.deepseek.com/v1",          "deepseek-chat"),
            ("Claude (via OpenAI compat)", "https://api.anthropic.com/v1", "claude-3-haiku"),
            ("本地 Ollama",  "http://localhost:11434/v1",            "qwen2.5 / llama3"),
        ]
        for name, url, model in platforms:
            row = ctk.CTkFrame(info_card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(row, text=f"• {name}",
                         font=CTkFont(size=12, weight="bold"),
                         text_color=self.TEXT_PRI, width=180, anchor="w"
                         ).pack(side="left")
            ctk.CTkLabel(row, text=url,
                         font=CTkFont(family="Consolas", size=11),
                         text_color=self.SUCCESS, anchor="w"
                         ).pack(side="left", padx=8)

        # Ren'Py SDK 路径卡片
        sdk_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        sdk_card.pack(fill="x", padx=20, pady=6)
        sdk_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(sdk_card, text="🛠  Ren'Py SDK 路径",
                     font=CTkFont(size=14, weight="bold"),
                     text_color=self.TEXT_PRI
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            sdk_card,
            text=(
                "用于反编译 .rpyc。填入安装目录（包含 renpy.exe 的文件夹）\n"
                "例：D:/Work/SoftwareInstall/renpy-8.5.2-sdk"
            ),
            font=CTkFont(size=11), text_color=self.TEXT_SEC, anchor="w", justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 6))

        sdk_entry = ctk.CTkEntry(sdk_card, textvariable=self.renpy_sdk_dir,
                                  placeholder_text="例：D:/Work/SoftwareInstall/renpy-8.5.2-sdk",
                                  font=CTkFont(size=12), height=36)
        sdk_entry.grid(row=2, column=0, columnspan=2, sticky="ew",
                       padx=(16, 8), pady=(0, 14))
        ctk.CTkButton(sdk_card, text="浏览", width=80, height=36,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      command=self._browse_renpy_sdk,
                      ).grid(row=2, column=2, padx=(0, 16), pady=(0, 14))

        # 测试连接按钮
        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=8)
        btn_row.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(btn_row, text="💾  保存配置", height=40,
                      fg_color=self.BG_CARD, hover_color="#2A2A4E",
                      font=CTkFont(size=13),
                      command=self._save_config
                      ).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="🔌  测试连接", height=40,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      font=CTkFont(size=13, weight="bold"),
                      command=self._test_connection
                      ).pack(side="left", padx=4)

        self.conn_status = ctk.CTkLabel(btn_row, text="",
                                        font=CTkFont(size=12), text_color=self.TEXT_SEC)
        self.conn_status.pack(side="left", padx=12)

        # ── 翻译风格指令卡 ─────────────────────────────────────────────────────
        style_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        style_card.pack(fill="x", padx=20, pady=6)

        ctk.CTkLabel(style_card, text="🎨  翻译风格指令",
                     font=CTkFont(size=14, weight="bold"),
                     text_color=self.TEXT_PRI,
                     ).pack(padx=16, pady=(12, 2), anchor="w")
        ctk.CTkLabel(
            style_card,
            text="追加到提示词中，指导 AI 的翻译语气/风格。留空则不附加。",
            font=CTkFont(size=11), text_color=self.TEXT_SEC, anchor="w",
        ).pack(padx=16, pady=(0, 4), anchor="w")
        ctk.CTkEntry(
            style_card, textvariable=self.custom_instructions,
            placeholder_text="例：使用更大胆、露骨的成人用语，不要委婉。保持角色的调皮个性。",
            font=CTkFont(size=12), height=36,
        ).pack(fill="x", padx=16, pady=(0, 14))

        # ── 术语对照表卡 ───────────────────────────────────────────────────────
        term_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        term_card.pack(fill="x", padx=20, pady=6)

        ctk.CTkLabel(term_card, text="📝  术语对照表",
                     font=CTkFont(size=14, weight="bold"),
                     text_color=self.TEXT_PRI,
                     ).pack(padx=16, pady=(12, 2), anchor="w")
        ctk.CTkLabel(
            term_card,
            text="每行一条，格式：英文=中文。以 # 开头的行为注释。AI 提示词和译文后处理双重保障。",
            font=CTkFont(size=11), text_color=self.TEXT_SEC, anchor="w",
        ).pack(padx=16, pady=(0, 4), anchor="w")
        self.term_glossary_box = ctk.CTkTextbox(
            term_card, height=110, font=CTkFont(family="Consolas", size=12),
            fg_color="#0D0D1A", text_color=self.TEXT_PRI, corner_radius=8,
        )
        self.term_glossary_box.pack(fill="x", padx=16, pady=(0, 4))
        self.term_glossary_box.insert("1.0",
            "# 示例（删除 # 即生效）：\n"
            "# landlord=妈妈\n"
            "# MC=小明"
        )
        ctk.CTkLabel(
            term_card,
            text="提示：术语会注入 AI 提示词，译文完成后还会对全文做正则替换，确保准确性。",
            font=CTkFont(size=10), text_color=self.TEXT_SEC, anchor="w",
        ).pack(padx=16, pady=(0, 12), anchor="w")

        self.pages["settings"] = page

    # ── 翻译主页 ──────────────────────────────────────────────────────────────

    def _build_page_translate(self):
        page = ctk.CTkFrame(self.page_frame, fg_color=self.BG_DARK, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        self._section_title(page, "🚀 批量翻译", row=0)

        # 统计信息
        stats_card = self._card(page, row=1)
        stats_card.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_labels: dict[str, ctk.CTkLabel] = {}
        for col, (key, icon, title) in enumerate([
            ("files",      "📄", "待翻译文件"),
            ("labels",     "🏷️", "对话标签"),
            ("dialogues",  "💬", "对话条数"),
            ("done",       "✅", "已完成"),
        ]):
            f = ctk.CTkFrame(stats_card, fg_color="#0D0D1A", corner_radius=10)
            f.grid(row=0, column=col, padx=10, pady=14, sticky="ew")
            ctk.CTkLabel(f, text=icon, font=CTkFont(size=22),
                         ).pack(pady=(10, 2))
            lbl = ctk.CTkLabel(f, text="0", font=CTkFont(size=22, weight="bold"),
                               text_color=self.ACCENT)
            lbl.pack()
            ctk.CTkLabel(f, text=title, font=CTkFont(size=11),
                         text_color=self.TEXT_SEC).pack(pady=(2, 10))
            self.stat_labels[key] = lbl

        # 日志 + 控制
        log_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        log_card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctrl = ctk.CTkFrame(log_card, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        ctrl.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(ctrl, text="翻译日志",
                     font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI
                     ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(ctrl, text="🗑️ 清空", width=70, height=30,
                      fg_color=self.BG_DARK, hover_color="#2A2A4E",
                      font=CTkFont(size=12),
                      command=self._clear_translate_log
                      ).grid(row=0, column=1, padx=4)

        self.stop_btn = ctk.CTkButton(
            ctrl, text="⏹ 停止", width=70, height=30,
            fg_color="#4A1A1A", hover_color="#6A2A2A",
            font=CTkFont(size=12),
            command=self._stop_translation,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=2, padx=4)

        self.pause_btn = ctk.CTkButton(
            ctrl, text="⏸ 暂停", width=70, height=30,
            fg_color="#3A3A1A", hover_color="#5A5A2A",
            font=CTkFont(size=12),
            command=self._toggle_pause,
            state="disabled",
        )
        self.pause_btn.grid(row=0, column=3, padx=4)

        self.start_btn = ctk.CTkButton(
            ctrl, text="🚀  开始翻译", height=30,
            fg_color=self.ACCENT, hover_color=self.ACCENT_H,
            font=CTkFont(size=13, weight="bold"),
            command=self._start_translation,
        )
        self.start_btn.grid(row=0, column=4, padx=4)

        self.translate_log = ctk.CTkTextbox(
            log_card, fg_color="#0D0D1A",
            text_color=self.TEXT_SEC,
            font=CTkFont(family="Consolas", size=11),
            corner_radius=8,
        )
        self.translate_log.grid(row=1, column=0, sticky="nsew",
                                padx=16, pady=(0, 12))

        self.pages["translate"] = page

    # ── 补翻修复页 ────────────────────────────────────────────────────────────

    def _build_page_repair(self):
        page = ctk.CTkFrame(self.page_frame, fg_color=self.BG_DARK, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        self._section_title(page, "🔄 补翻修复", row=0)

        # 目录选择卡
        dir_card = self._card(page, row=1)
        dir_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(dir_card, text="翻译输出目录",
                     font=CTkFont(size=13, weight="bold"),
                     text_color=self.TEXT_PRI
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(dir_card,
                     text="选择上次翻译生成的 translation/ 目录，程序将扫描并补翻其中残留的英文",
                     font=CTkFont(size=11), text_color=self.TEXT_SEC, anchor="w"
                     ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 6))

        repair_entry = ctk.CTkEntry(dir_card, textvariable=self._repair_dir,
                                    placeholder_text="例：D:/Download/.../game/scripts/translation",
                                    font=CTkFont(size=12), height=36)
        repair_entry.grid(row=2, column=0, columnspan=2, sticky="ew",
                          padx=(16, 8), pady=(0, 14))
        ctk.CTkButton(dir_card, text="浏览", width=80, height=36,
                      fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                      command=self._browse_repair_dir,
                      ).grid(row=2, column=2, padx=(0, 16), pady=(0, 14))

        # 统计 + 控制卡
        result_card = ctk.CTkFrame(page, fg_color=self.BG_CARD, corner_radius=12)
        result_card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        result_card.grid_columnconfigure(0, weight=1)
        result_card.grid_rowconfigure(2, weight=1)
        result_card.grid_rowconfigure(3, weight=2)

        ctrl2 = ctk.CTkFrame(result_card, fg_color="transparent")
        ctrl2.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctrl2.grid_columnconfigure(0, weight=1)

        self.repair_summary = ctk.CTkLabel(
            ctrl2, text="请先选择目录并点击【扫描】",
            font=CTkFont(size=12), text_color=self.TEXT_SEC, anchor="w")
        self.repair_summary.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(ctrl2, text="🔍 扫描未翻译", width=110, height=32,
                      fg_color=self.BG_DARK, hover_color="#2A2A4E",
                      font=CTkFont(size=12),
                      command=self._start_scan_untranslated,
                      ).grid(row=0, column=1, padx=4)

        self.repair_stop_btn = ctk.CTkButton(
            ctrl2, text="⏹ 停止", width=70, height=32,
            fg_color="#4A1A1A", hover_color="#6A2A2A",
            font=CTkFont(size=12),
            command=lambda: setattr(self, "_stop_flag", True),
            state="disabled",
        )
        self.repair_stop_btn.grid(row=0, column=2, padx=4)

        self.repair_btn = ctk.CTkButton(
            ctrl2, text="🔄 开始补翻", width=100, height=32,
            fg_color=self.ACCENT, hover_color=self.ACCENT_H,
            font=CTkFont(size=13, weight="bold"),
            command=self._start_repair,
            state="disabled",
        )
        self.repair_btn.grid(row=0, column=3, padx=4)

        # 进度条行
        prog_row = ctk.CTkFrame(result_card, fg_color="transparent")
        prog_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))
        prog_row.grid_columnconfigure(0, weight=1)

        self.repair_progress = ctk.CTkProgressBar(
            prog_row, height=8, corner_radius=4,
            progress_color=self.ACCENT, fg_color="#1A1A30")
        self.repair_progress.set(0)
        self.repair_progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.repair_progress_label = ctk.CTkLabel(
            prog_row, text="", width=130,
            font=CTkFont(size=11), text_color=self.TEXT_SEC, anchor="e")
        self.repair_progress_label.grid(row=0, column=1)

        # 文件列表 + 日志(上下分割)
        self.repair_file_frame = ctk.CTkScrollableFrame(
            result_card, fg_color="#0D0D1A", corner_radius=8, height=160)
        self.repair_file_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 6))
        self.repair_file_frame.grid_columnconfigure(0, weight=1)

        self.repair_log = ctk.CTkTextbox(
            result_card, fg_color="#0D0D1A",
            text_color=self.TEXT_SEC,
            font=CTkFont(family="Consolas", size=11),
            corner_radius=8,
        )
        self.repair_log.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 12))

        self.pages["repair"] = page

    # ---------------------------------------------------------------------------
    # 辅助 UI 方法
    # ---------------------------------------------------------------------------

    def _section_title(self, parent, text: str, row: int = 0, pack: bool = False):
        lbl = ctk.CTkLabel(parent, text=text,
                           font=CTkFont(size=18, weight="bold"),
                           text_color=self.TEXT_PRI)
        if pack:
            lbl.pack(padx=28, pady=(24, 8), anchor="w")
        else:
            lbl.grid(row=row, column=0, sticky="w", padx=28, pady=(20, 8))

    def _card(self, parent, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=self.BG_CARD, corner_radius=12)
        card.grid(row=row, column=0, sticky="ew", padx=20, pady=6)
        return card

    # ---------------------------------------------------------------------------
    # 导航
    # ---------------------------------------------------------------------------

    def _show_page(self, key: str):
        for name, page in self.pages.items():
            page.grid_remove() if hasattr(page, "grid_remove") else page.pack_forget()

        page = self.pages[key]
        try:
            page.grid(row=0, column=0, sticky="nsew")
        except Exception:
            page.pack(fill="both", expand=True)

        for name, btn in self.nav_buttons.items():
            if name == key:
                btn.configure(text_color=self.TEXT_PRI,
                              fg_color=self.BG_CARD,
                              font=CTkFont(size=13, weight="bold"))
            else:
                btn.configure(text_color=self.TEXT_SEC,
                              fg_color="transparent",
                              font=CTkFont(size=13))

    # ---------------------------------------------------------------------------
    # 配置保存/加载
    # ---------------------------------------------------------------------------

    CONFIG_PATH = Path(__file__).parent / "config.json"

    def _save_config(self):
        data = {
            "api_key":   self.api_key.get(),
            "api_base":  self.api_base.get(),
            "api_model": self.api_model.get(),
            "lang_code": self.lang_code.get(),
            "lang_name": self.lang_name.get(),
            "batch_size": self.batch_size.get(),
            "game_dir":    self.game_dir.get(),
            "extract_dir": self.extract_dir.get(),
            "renpy_sdk_dir": self.renpy_sdk_dir.get(),
        }
        self.CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
        self._set_status("配置已保存", self.SUCCESS)

    def _load_config(self):
        if not self.CONFIG_PATH.exists():
            return
        try:
            data = json.loads(self.CONFIG_PATH.read_text(encoding="utf-8"))
            self.api_key.set(data.get("api_key", ""))
            self.api_base.set(data.get("api_base", "https://api.openai.com/v1"))
            self.api_model.set(data.get("api_model", "gpt-4o-mini"))
            self.lang_code.set(data.get("lang_code", "zh"))
            self.lang_name.set(data.get("lang_name", "简体中文"))
            self.batch_size.set(data.get("batch_size", 20))
            self.game_dir.set(data.get("game_dir", ""))
            self.extract_dir.set(data.get("extract_dir", ""))
            self.renpy_sdk_dir.set(data.get("renpy_sdk_dir", ""))
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # 文件浏览
    # ---------------------------------------------------------------------------

    def _browse_game_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择游戏根目录")
        if d:
            self.game_dir.set(d)
            if not self.extract_dir.get():
                self.extract_dir.set(d)
            self._refresh_rpa_list()

    def _browse_extract_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择解压输出目录")
        if d:
            self.extract_dir.set(d)

    def _browse_scan_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择解压后的脚本目录")
        if d:
            self.scan_dir_var.set(d)

    def _browse_renpy_sdk(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择 Ren'Py SDK 目录（包含 renpy.exe 的文件夹）")
        if d:
            self.renpy_sdk_dir.set(d)

    # ---------------------------------------------------------------------------
    # RPA 操作
    # ---------------------------------------------------------------------------

    def _refresh_rpa_list(self):
        for w in self.rpa_list_frame.winfo_children():
            w.destroy()
        self.rpa_vars.clear()

        game_dir = self.game_dir.get()
        if not game_dir or not Path(game_dir).exists():
            ctk.CTkLabel(self.rpa_list_frame,
                         text="⚠ 请先设置有效的游戏根目录",
                         text_color=self.WARNING,
                         font=CTkFont(size=12)).pack(pady=8)
            return

        rpa_files = list(Path(game_dir).rglob("*.rpa"))
        if not rpa_files:
            ctk.CTkLabel(self.rpa_list_frame,
                         text="未找到 .rpa 文件",
                         text_color=self.TEXT_SEC,
                         font=CTkFont(size=12)).pack(pady=8)
            return

        for rpa in rpa_files:
            var = ctk.BooleanVar(value=True)
            self.rpa_vars[str(rpa)] = var
            row = ctk.CTkFrame(self.rpa_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkCheckBox(row, text=rpa.name,
                            variable=var,
                            font=CTkFont(family="Consolas", size=12),
                            text_color=self.TEXT_PRI,
                            checkbox_width=18, checkbox_height=18,
                            ).pack(side="left", padx=4)
            size_mb = rpa.stat().st_size / 1024 / 1024
            ctk.CTkLabel(row, text=f"{size_mb:.1f} MB",
                         font=CTkFont(size=11), text_color=self.TEXT_SEC
                         ).pack(side="right", padx=8)

    def _start_extract(self):
        selected = [p for p, v in self.rpa_vars.items() if v.get()]
        if not selected:
            self._append_log(self.extract_log, "⚠ 未选择任何 .rpa 文件")
            return
        dest = self.extract_dir.get() or self.game_dir.get()
        if not dest:
            self._append_log(self.extract_log, "⚠ 请设置游戏根目录或解压目标目录")
            return

        threading.Thread(
            target=self._extract_worker,
            args=(selected, dest),
            daemon=True,
        ).start()

    def _extract_worker(self, rpa_paths: list[str], dest: str):
        for rpa_path in rpa_paths:
            self._append_log(self.extract_log, f"\n📦 解压: {Path(rpa_path).name}")
            try:
                extractor = RPAExtractor(rpa_path)
                files = extractor.extract_all(
                    dest,
                    progress_callback=lambda cur, tot, name: self._progress_queue.put(
                        (cur, tot, f"解压 {name}")
                    )
                )
                self._append_log(self.extract_log,
                                 f"  ✅ 完成，共解压 {len(files)} 个文件")
            except Exception as e:
                self._append_log(self.extract_log, f"  ❌ 错误: {e}")

        self._append_log(self.extract_log, "\n✅ 解压任务完成！")
        self._set_status("解压完成", self.SUCCESS)
        self._progress_queue.put((1, 1, "解压完成"))

    # ---------------------------------------------------------------------------
    # 扫描操作
    # ---------------------------------------------------------------------------

    def _start_scan(self):
        scan_dir = self.scan_dir_var.get()
        if not scan_dir:
            # 尝试从 extract_dir 或 game_dir 推断
            base = self.extract_dir.get() or self.game_dir.get()
            if base:
                scan_dir = base
                self.scan_dir_var.set(scan_dir)

        if not scan_dir or not Path(scan_dir).exists():
            self.scan_summary.configure(text="⚠ 目录不存在", text_color=self.WARNING)
            return

        self.scan_summary.configure(text="扫描中...", text_color=self.TEXT_SEC)
        threading.Thread(
            target=self._scan_worker,
            args=(scan_dir, self.file_filter.get()),
            daemon=True,
        ).start()

    def _scan_worker(self, scan_dir: str, ffilter: str):
        results, diagnostics = RPYParser.scan_directory(scan_dir, ffilter)
        self._scanned_files = results
        total_labels = sum(len(ls) for _, ls in results)
        total_dlg = sum(len(l.dialogues) for _, ls in results for l in ls)
        self._total_dialogues = total_dlg
        self.after(0, lambda: self._render_scan_results(results, total_labels, total_dlg, diagnostics))

    def _render_scan_results(self, results, total_labels, total_dlg, diagnostics=None):
        for w in self.file_list_frame.winfo_children():
            w.destroy()
        self._file_vars.clear()

        if diagnostics is None:
            diagnostics = {}

        # 如果是编译版本，显示诊断信息 + 反编译按钮
        if diagnostics.get("is_compiled"):
            warning_box = ctk.CTkFrame(self.file_list_frame, fg_color="#3A1A1A",
                                      corner_radius=8, border_width=1,
                                      border_color=self.DANGER)
            warning_box.pack(fill="both", expand=True, padx=8, pady=8)

            ctk.CTkLabel(warning_box, text="⚠️  检测到编译版本（.rpyc）",
                        font=CTkFont(size=13, weight="bold"),
                        text_color=self.DANGER).pack(padx=16, pady=(12, 4), anchor="w")

            ctk.CTkLabel(
                warning_box,
                text=(
                    f"找到 {diagnostics['rpyc_found']} 个 .rpyc 文件，无 .rpy 源码。\n"
                    "官方翻译方法（来自 wiki.summertimesaga.com/Modding）：\n"
                    " • 通过 unrpyc 反编译 .rpyc → .rpy，再正常扫描、翻译\n"
                    " • 或直接创建符合 Modding API 规范的翻译 Mod（标签 + text_filter）\n\n"
                    "点击下方按钮自动安装 unrpyc 并反编译"
                ),
                font=CTkFont(size=12),
                text_color=self.TEXT_SEC,
                anchor="w", justify="left", wraplength=680
            ).pack(padx=16, pady=(0, 8), anchor="w")

            btn_row = ctk.CTkFrame(warning_box, fg_color="transparent")
            btn_row.pack(padx=16, pady=(0, 14), anchor="w")

            self._decompile_status_lbl = ctk.CTkLabel(
                btn_row, text="", font=CTkFont(size=12), text_color=self.TEXT_SEC)

            ctk.CTkButton(
                btn_row,
                text="🔧  安装 unrpyc 并反编译 .rpyc",
                height=34,
                fg_color=self.ACCENT, hover_color=self.ACCENT_H,
                font=CTkFont(size=13, weight="bold"),
                command=lambda: self._try_decompile_rpyc(
                    self.scan_dir_var.get(), self._decompile_status_lbl
                ),
            ).pack(side="left", padx=(0, 12))

            self._decompile_status_lbl.pack(side="left")

            self.scan_summary.configure(
                text=f"检测到 {diagnostics['rpyc_found']} 个编译文件 — 请先反编译",
                text_color=self.DANGER
            )
            return

        if not results:
            ctk.CTkLabel(self.file_list_frame,
                         text="未找到含对话的 .rpy 文件，请检查目录和过滤关键词",
                         text_color=self.WARNING,
                         font=CTkFont(size=12)).pack(pady=12)
            self.scan_summary.configure(text="未找到文件", text_color=self.WARNING)
            return

        scan_root = Path(self.scan_dir_var.get())

        for path, labels in results:
            var = ctk.BooleanVar(value=True)
            dlg_count = sum(len(l.dialogues) for l in labels)

            row = ctk.CTkFrame(self.file_list_frame, fg_color="#0D0D1A", corner_radius=6)
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkCheckBox(row, text="",
                            variable=var,
                            checkbox_width=16, checkbox_height=16,
                            ).grid(row=0, column=0, padx=(8, 4), pady=8)

            try:
                rel = path.relative_to(scan_root)
            except ValueError:
                rel = path

            ctk.CTkLabel(row, text=str(rel),
                         font=CTkFont(family="Consolas", size=11),
                         text_color=self.TEXT_PRI, anchor="w"
                         ).grid(row=0, column=1, sticky="w", padx=4)

            ctk.CTkLabel(row,
                         text=f"{len(labels)} 标签  {dlg_count} 条对话",
                         font=CTkFont(size=11),
                         text_color=self.TEXT_SEC
                         ).grid(row=0, column=2, padx=12, pady=8)

            self._file_vars.append((var, path, labels))

        self.scan_summary.configure(
            text=f"共 {len(results)} 个文件 | {total_labels} 个标签 | {total_dlg} 条对话",
            text_color=self.SUCCESS
        )
        self._update_stats()

    def _select_all_files(self, value: bool):
        for var, _, _ in self._file_vars:
            var.set(value)

    # ---------------------------------------------------------------------------
    # 反编译 .rpyc
    # ---------------------------------------------------------------------------

    def _try_decompile_rpyc(self, scan_dir: str, status_lbl: ctk.CTkLabel):
        """安装 unrpyc（若未安装）后批量反编译 .rpyc → .rpy"""
        if self._decompiling:
            return
        if not scan_dir or not Path(scan_dir).exists():
            status_lbl.configure(text="⚠ 请先设置扫描目录", text_color=self.WARNING)
            return

        self._decompiling = True
        status_lbl.configure(text="准备中...", text_color=self.WARNING)

        threading.Thread(
            target=self._decompile_worker,
            args=(scan_dir, status_lbl),
            daemon=True,
        ).start()

    @staticmethod
    def _find_sdk_python(sdk_dir: str) -> str | None:
        """在 Ren'Py SDK 目录中定位配套 Python 解释器"""
        if not sdk_dir:
            return None
        sdk = Path(sdk_dir)
        # Windows: lib/py3-windows-x86_64/python.exe 或 lib/windows-x86_64/python.exe
        candidates = [
            sdk / "lib" / "py3-windows-x86_64" / "python.exe",
            sdk / "lib" / "windows-x86_64" / "python.exe",
            sdk / "lib" / "py3-windows-i686" / "python.exe",
            sdk / "lib" / "windows-i686" / "python.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    # unrpyc 本地路径（优先用解压好的 unrpyc-master，其次尝试同目录 unrpyc.py，最后从 GitHub 下载）
    UNRPYC_SCRIPT_URL = (
        "https://raw.githubusercontent.com/CensoredUsername/unrpyc/master/unrpyc.py"
    )

    @classmethod
    def _find_unrpyc_script(cls) -> Path | None:
        """按优先级查找 unrpyc.py 脚本位置"""
        base = Path(__file__).parent
        candidates = [
            # 双层解压（GitHub zip 解压后的典型结构）
            base / "unrpyc-master" / "unrpyc-master" / "unrpyc.py",
            # 单层解压
            base / "unrpyc-master" / "unrpyc.py",
            # 直接放在 translator/ 目录
            base / "unrpyc.py",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def _ensure_unrpyc_script(self) -> tuple[bool, str]:
        """确保本地有 unrpyc.py，没有则从 GitHub 下载。返回 (success, errmsg)"""
        if self._find_unrpyc_script() is not None:
            return True, ""
        download_target = Path(__file__).parent / "unrpyc.py"
        try:
            import urllib.request as _req
            with _req.urlopen(self.UNRPYC_SCRIPT_URL, timeout=30) as resp:
                data = resp.read()
            download_target.write_bytes(data)
            return True, ""
        except Exception as e:
            return False, str(e)

    def _decompile_worker(self, scan_dir: str, status_lbl: ctk.CTkLabel):
        import subprocess as _sp

        def upd(msg, color=None):
            c = color or self.WARNING
            self.after(0, lambda: status_lbl.configure(text=msg, text_color=c))

        python_exe = sys.executable

        # 1. 确保 unrpyc.py 脚本存在
        script_path = self._find_unrpyc_script()
        if script_path is None:
            upd("未找到本地 unrpyc.py，正在从 GitHub 下载 ...")
            ok, err_msg = self._ensure_unrpyc_script()
            script_path = self._find_unrpyc_script()
            if not ok or script_path is None:
                upd(
                    f"❌ 下载失败: {err_msg}\n"
                    f"请将 unrpyc-master 解压到 translator/ 目录",
                    self.DANGER,
                )
                self._decompiling = False
                return
            upd("✅ unrpyc.py 准备完成")

        unrpyc_script = str(script_path)

        # 2. 找所有 .rpyc 文件
        rpyc_files = list(Path(scan_dir).rglob("*.rpyc"))
        if not rpyc_files:
            upd("⚠ 未找到 .rpyc 文件", self.WARNING)
            self._decompiling = False
            return

        upd(f"反编译中... 0 / {len(rpyc_files)}")
        ok = err = 0

        for i, rpyc in enumerate(rpyc_files):
            rpy_out = rpyc.with_suffix(".rpy")
            if rpy_out.exists():
                ok += 1
                upd(f"反编译中... {i+1} / {len(rpyc_files)}")
                continue
            try:
                result = _sp.run(
                    [python_exe, unrpyc_script, str(rpyc)],
                    capture_output=True, text=True,
                    cwd=str(rpyc.parent),
                )
                if result.returncode == 0:
                    ok += 1
                else:
                    err += 1
            except Exception:
                err += 1
            upd(f"反编译中... {i+1} / {len(rpyc_files)}")

        self._decompiling = False

        if ok > 0:
            upd(f"✅ 反编译完成：{ok} 成功 / {err} 失败 — 请重新扫描", self.SUCCESS)
            self.after(500, self._start_scan)
        else:
            upd(f"❌ 全部失败（{err} 个）", self.DANGER)

    # ---------------------------------------------------------------------------
    # 翻译操作
    # ---------------------------------------------------------------------------

    def _update_stats(self):
        selected_files = [p for v, p, _ in self._file_vars if v.get()]
        selected_labels = [ls for v, _, ls in self._file_vars if v.get()]
        total_l = sum(len(ls) for ls in selected_labels)
        total_d = sum(len(l.dialogues) for ls in selected_labels for l in ls)
        self.stat_labels["files"].configure(text=str(len(selected_files)))
        self.stat_labels["labels"].configure(text=str(total_l))
        self.stat_labels["dialogues"].configure(text=str(total_d))
        self.stat_labels["done"].configure(text=str(self._translated_count))

    def _start_translation(self):
        if self.is_translating:
            return

        if not self.api_key.get():
            self._append_log(self.translate_log, "❌ 请先在 API 设置页填写 API Key")
            self._show_page("settings")
            return

        selected = [(v, p, ls) for v, p, ls in self._file_vars if v.get()]
        if not selected:
            self._append_log(self.translate_log, "❌ 没有选中任何文件，请先到扫描页选择文件")
            return

        self.is_translating = True
        self._stop_flag = False
        self._pause_event.set()  # 确保处于运行状态
        self._translated_count = 0
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.pause_btn.configure(state="normal", text="⏸ 暂停",
                                 fg_color="#3A3A1A", hover_color="#5A5A2A")
        self._update_stats()

        engine = TranslationEngine(
            api_key=self.api_key.get(),
            base_url=self.api_base.get(),
            model=self.api_model.get(),
            target_lang=self.lang_name.get(),
            batch_size=self.batch_size.get(),
            custom_instructions=self.custom_instructions.get(),
            term_dict=self._parse_term_glossary(),
        )

        threading.Thread(
            target=self._translate_worker,
            args=(selected, engine),
            daemon=True,
        ).start()

    def _parse_term_glossary(self) -> dict[str, str]:
        """解析术语对照表文本框，返回 { 英文: 中文 } 字典"""
        if not hasattr(self, "term_glossary_box"):
            return {}
        raw = self.term_glossary_box.get("1.0", "end")
        result: dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and v:
                    result[k] = v
        return result

    def _stop_translation(self):
        self._stop_flag = True
        self._pause_event.set()  # 如果处于暂停状态先解除阻塞
        self._append_log(self.translate_log, "\n⏹  正在停止翻译...")
        self.pause_btn.configure(state="disabled", text="⏸ 暂停")

    def _toggle_pause(self):
        if self._pause_event.is_set():
            # 当前运行中 → 暂停
            self._pause_event.clear()
            self.pause_btn.configure(text="▶ 继续",
                                     fg_color="#1A3A1A", hover_color="#2A5A2A")
            self._append_log(self.translate_log, "\n⏸  已暂停，点击《继续》恢复...")
            self._set_status("已暂停", self.WARNING)
        else:
            # 当前暂停中 → 继续
            self._pause_event.set()
            self.pause_btn.configure(text="⏸ 暂停",
                                     fg_color="#3A3A1A", hover_color="#5A5A2A")
            self._append_log(self.translate_log, "\n▶  继续翻译...")

    def _clear_translate_log(self):
        """清空翻译日志。"""
        try:
            self.translate_log.delete("1.0", "end")
        except Exception:
            pass

    def _translate_worker(self, selected: list, engine: TranslationEngine):
        try:
            self._translate_worker_impl(selected, engine)
        except Exception as exc:  # noqa: BLE001
            import traceback
            tb = traceback.format_exc()
            self._append_log(self.translate_log,
                             f"\n❌ 翻译线程发生未处理异常：\n{tb}")
            self._set_status("翻译异常终止", self.DANGER)
        finally:
            self.is_translating = False
            self._pause_event.set()
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.stop_btn.configure(state="disabled"))
            self.after(0, lambda: self.pause_btn.configure(
                state="disabled", text="⏸ 暂停",
                fg_color="#3A3A1A", hover_color="#5A5A2A"))

    def _translate_worker_impl(self, selected: list, engine: TranslationEngine):
        lang_code = self.lang_code.get()
        lang_name = self.lang_name.get()
        scan_dir  = self.scan_dir_var.get() or self.extract_dir.get() or self.game_dir.get()
        output_dir = Path(scan_dir) / "game" / "scripts" / "translation"

        # 若 scan_dir 已经是 game/ 下，调整一下
        scan_path = Path(scan_dir)
        if (scan_path / "scripts").exists():
            output_dir = scan_path / "scripts" / "translation"
        elif (scan_path / "game" / "scripts").exists():
            output_dir = scan_path / "game" / "scripts" / "translation"

        # Mod 名称（官方规范：只含字母数字下划线）
        mod_name = f"sts_{lang_code}_translation"

        output_dir.mkdir(parents=True, exist_ok=True)

        # 确保 scripts/data/ 目录存在（用于清单文件）
        data_dir = output_dir.parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        self._append_log(self.translate_log,
                         f"📁 输出目录: {output_dir}\n")

        all_texts_for_filter: dict[str, str] = {}
        total_files = len(selected)

        for fi, (_, path, labels) in enumerate(selected):
            if self._stop_flag:
                break

            out_file = output_dir / f"{path.stem}_{lang_code}.rpy"

            # ── 已存在则跳过，直接读取已有译文加入 filter 字典 ──────────────
            if out_file.exists():
                self._append_log(self.translate_log,
                                 f"\n[{fi+1}/{total_files}] ⏭ {path.name}  "
                                 f"（已存在 {out_file.name}，跳过）")
                # 从已有文件中读取译文，用于 text_filter
                existing = out_file.read_text(encoding="utf-8", errors="ignore")
                dlg_re = re.compile(r'"((?:[^"\\]|\\.)+)"')
                for m in dlg_re.finditer(existing):
                    t = m.group(1)
                    if t and not App._is_untranslated(t):
                        all_texts_for_filter[t] = t
                dlg_cnt = sum(len(l.dialogues) for l in labels)
                self._translated_count += dlg_cnt
                self.after(0, self._update_stats)
                self._progress_queue.put(
                    (self._translated_count, self._total_dialogues, f"跳过 {path.name}"))
                continue

            self._append_log(self.translate_log,
                             f"\n[{fi+1}/{total_files}] 📄 {path.name}")
            self._set_status(f"翻译中 {path.name}...", self.WARNING)

            # 收集本文件所有对话文本（去重）
            texts = list({t for l in labels for _, _, t in l.dialogues})
            translated_map: dict[str, str] = {}

            # 分批翻译
            for bi in range(0, len(texts), engine.batch_size):
                if self._stop_flag:
                    break
                # 暂停检查（在每批前等待，不中断已开始的请求）
                self._pause_event.wait()
                if self._stop_flag:
                    break
                chunk = texts[bi: bi + engine.batch_size]
                batch_num = bi // engine.batch_size + 1
                self._append_log(self.translate_log,
                                 f"  🌐 翻译第 {batch_num} 批（{len(chunk)} 条）...")
                batch_result = engine.translate_batch(chunk)
                # 记录 API 失败的条目
                if engine._failed_texts:
                    fail_cnt = sum(1 for t in chunk if t in engine._failed_texts)
                    if fail_cnt:
                        self._append_log(self.translate_log,
                                         f"  ⚠ 第 {batch_num} 批有 {fail_cnt} 条 API 失败，已保留原文")
                translated_map.update(batch_result)
                self._translated_count += len(chunk)
                self.after(0, self._update_stats)
                self._progress_queue.put(
                    (self._translated_count, self._total_dialogues, f"翻译 {path.name}")
                )

            all_texts_for_filter.update(translated_map)

            # 生成翻译标签文件
            out_lines = [
                f"# 翻译文件 - {lang_name}",
                f"# 源文件: {path}",
                f"# 语言代码: {lang_code}",
                f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
            ]
            for label in labels:
                out_lines.append(
                    RPYParser.build_translated_label(label, translated_map, lang_code)
                )

            out_file = output_dir / f"{path.stem}_{lang_code}.rpy"
            out_file.write_text("\n".join(out_lines), encoding="utf-8")
            self._append_log(self.translate_log,
                             f"  ✅ 已保存 → {out_file.name}")

        if not self._stop_flag:
            # ── 1. set_language.rpy（Game.language）────────────────────────────
            # 官方方式：init 1 python: Game.language = "zh"
            set_lang = output_dir / "set_language.rpy"
            set_lang.write_text(
                f"# 设置游戏语言为 {lang_name}\n"
                f"# 官方翻译 API：wiki.summertimesaga.com/Modding#Translating_the_game\n"
                f"# 由翻译工具自动生成\n\n"
                f"init 1 python:\n"
                f"    Game.language = \"{lang_code}\"\n",
                encoding="utf-8"
            )

            # ── 2. text_filter.rpy（过场/小游戏文字）────────────────────────────
            # 官方方式：config.say_menu_text_filter + elif 链避免大字典
            if all_texts_for_filter:
                filter_code = self._build_filter_code(
                    all_texts_for_filter, lang_code, lang_name)
                (output_dir / "text_filter.rpy").write_text(filter_code, encoding="utf-8")

            # ── 3. mod_init.rpy（翻译初始化）──────────────────────────────────
            # Ren'Py 内置翻译系统：只需 translate 块存在即可自动生效，无需 ModManager
            mod_init_code = (
                f"# 汉化翻译初始化\n"
                f"# 由翻译工具自动生成\n"
                f"# Ren'Py 内置翻译系统：translate 块自动生效，无需额外注册\n\n"
                f"## 如需游戏启动时自动切换为中文，取消下方注释：\n"
                f"# init python:\n"
                f"#     config.language = \"{lang_code}\"\n"
            )
            (output_dir / "mod_init.rpy").write_text(mod_init_code, encoding="utf-8")

            # ── 4. 清单文件 scripts/data/modname_manifest.json ─────────────────
            # 官方要求：scripts/data/<modname>_manifest.json
            manifest = {
                "name": mod_name,
                "version": "1.0.0",
                "text_filter": f"{lang_code}_text_filter",
            }
            manifest_path = data_dir / f"{mod_name}_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            self._append_log(
                self.translate_log,
                f"\n✅ 翻译完成！\n"
                f"   输出目录: {output_dir}\n"
                f"   共翻译 {self._translated_count} 条对话\n"
                f"\n已生成以下文件（按官方 Modding API 规范）：\n"
                f"   • 各对话标签翻译文件（*_{lang_code}.rpy）\n"
                f"     - 通过 Game.language=\"{lang_code}\" 自动调用\n"
                f"   • set_language.rpy\n"
                f"     - init 1 python: Game.language = \"{lang_code}\"\n"
                f"   • text_filter.rpy\n"
                f"     - config.say_menu_text_filter（过场/小游戏文字）\n"
                f"   • mod_init.rpy\n"
                f"     - ModManager.register(\"{mod_name}\")\n"
                f"   • {manifest_path.name}\n"
                f"     - 放置于 scripts/data/ 供 ModManager 读取\n"
                f"\n部署方式：\n"
                f"   将 translation/ 目录放入 game/scripts/ 下\n"
                f"   将 {manifest_path.name} 放入 game/scripts/data/ 下",
            )
            self._set_status("翻译完成！", self.SUCCESS)
            self.after(0, self._update_stats)

    # ---------------------------------------------------------------------------
    # 补翻修复
    # ---------------------------------------------------------------------------

    def _browse_repair_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择翻译输出目录（translation/）")
        if d:
            self._repair_dir.set(d)

    @staticmethod
    def _is_untranslated(text: str) -> bool:
        """判断一段文本是否仍为英文（未翻译）"""
        if not text.strip():
            return False
        # 含有中文字符则认为已翻译
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
                  or '\u3400' <= c <= '\u4dbf'
                  or '\uff00' <= c <= '\uffef')
        if cjk > 0:
            return False
        # 含有英文字母超过2个则认为未翻译（覆盖 Huh? Oh! 等短文本）
        latin = sum(1 for c in text if c.isalpha() and c.isascii())
        return latin >= 2

    @staticmethod
    def _extract_untranslated_from_file(rpy_path: Path) -> list[tuple[int, str]]:
        """从翻译后的 .rpy 文件中提取仍为英文的对话行，返回 [(行号, 原始文本)]"""
        # 匹配行中任意位置的 "..." 对话文本（兼容带 @ 表情标记、多空格等格式）
        dlg_re = re.compile(r'"((?:[^"\\]|\\.)+)"')
        # 跳过注释行和 label 行
        skip_re = re.compile(r'^\s*(#|label\s|translate\s)')
        results = []
        lines = rpy_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for lineno, line in enumerate(lines, 1):
            if skip_re.match(line):
                continue
            m = dlg_re.search(line)
            if m:
                content = m.group(1)
                if App._is_untranslated(content):
                    results.append((lineno, content))
        return results

    def _start_scan_untranslated(self):
        repair_dir = self._repair_dir.get()
        if not repair_dir or not Path(repair_dir).exists():
            self.repair_summary.configure(
                text="⚠ 请先选择翻译输出目录", text_color=self.WARNING)
            return
        self.repair_summary.configure(text="扫描中...", text_color=self.TEXT_SEC)
        self.repair_btn.configure(state="disabled")
        for w in self.repair_file_frame.winfo_children():
            w.destroy()
        self._repair_file_vars: list[tuple[ctk.BooleanVar, Path, list[tuple[int, str]]]] = []

        threading.Thread(
            target=self._scan_untranslated_worker,
            args=(repair_dir,), daemon=True).start()

    def _scan_untranslated_worker(self, repair_dir: str):
        rpy_files = sorted(Path(repair_dir).glob("*_*.rpy"))
        # 排除系统文件
        skip = {"set_language.rpy", "text_filter.rpy", "mod_init.rpy"}
        rpy_files = [f for f in rpy_files if f.name not in skip]

        results: list[tuple[Path, list[tuple[int, str]]]] = []
        for f in rpy_files:
            untrans = self._extract_untranslated_from_file(f)
            if untrans:
                results.append((f, untrans))

        total_items = sum(len(u) for _, u in results)
        self.after(0, lambda: self._render_repair_results(results, total_items))

    def _render_repair_results(self, results, total_items):
        for w in self.repair_file_frame.winfo_children():
            w.destroy()
        self._repair_file_vars = []

        if not results:
            ctk.CTkLabel(self.repair_file_frame,
                         text="✅ 未发现未翻译内容，全部已翻译！",
                         text_color=self.SUCCESS,
                         font=CTkFont(size=12)).pack(pady=8)
            self.repair_summary.configure(
                text="✅ 未发现未翻译内容", text_color=self.SUCCESS)
            return

        for fpath, untrans_lines in results:
            var = ctk.BooleanVar(value=True)
            self._repair_file_vars.append((var, fpath, untrans_lines))
            row = ctk.CTkFrame(self.repair_file_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkCheckBox(row, text="", variable=var,
                            checkbox_width=16, checkbox_height=16,
                            ).grid(row=0, column=0, padx=(6, 4), pady=4)
            ctk.CTkLabel(row, text=fpath.name,
                         font=CTkFont(family="Consolas", size=11),
                         text_color=self.TEXT_PRI, anchor="w"
                         ).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text=f"{len(untrans_lines)} 条未翻译",
                         font=CTkFont(size=11), text_color=self.WARNING
                         ).grid(row=0, column=2, padx=10)

        self.repair_summary.configure(
            text=f"发现 {len(results)} 个文件共 {total_items} 条未翻译，勾选后点击【开始补翻】",
            text_color=self.WARNING)
        self.repair_btn.configure(state="normal")

    def _start_repair(self):
        if self._is_repairing:
            return
        if not self.api_key.get():
            self._append_log(self.repair_log, "❌ 请先在 API 设置页填写 API Key")
            return
        selected = [(v, p, u) for v, p, u in self._repair_file_vars if v.get()]
        if not selected:
            self._append_log(self.repair_log, "⚠ 请至少勾选一个文件")
            return

        self._is_repairing = True
        self._stop_flag = False
        self._pause_event.set()
        self.repair_btn.configure(state="disabled")
        self.repair_stop_btn.configure(state="normal")

        engine = TranslationEngine(
            api_key=self.api_key.get(),
            base_url=self.api_base.get(),
            model=self.api_model.get(),
            target_lang=self.lang_name.get(),
            batch_size=self.batch_size.get(),
            custom_instructions=self.custom_instructions.get(),
            term_dict=self._parse_term_glossary(),
        )
        threading.Thread(
            target=self._repair_worker,
            args=(selected, engine), daemon=True).start()

    def _repair_worker(self, selected, engine: TranslationEngine):
        total_files = len(selected)
        total_items = sum(len(lines) for _, _, lines in selected)
        done_files = 0
        done_items = 0

        def _upd_progress():
            pct = done_items / total_items if total_items else 0
            self.repair_progress.set(pct)
            self.repair_progress_label.configure(
                text=f"{done_items}/{total_items} 条  {done_files}/{total_files} 文件")

        self.after(0, _upd_progress)

        for var, fpath, untrans_lines in selected:
            if self._stop_flag:
                break
            self._pause_event.wait()
            if self._stop_flag:
                break

            texts = [t for _, t in untrans_lines]
            self._append_log(self.repair_log,
                             f"\n📄 [{done_files+1}/{total_files}] {fpath.name}  ({len(texts)} 条)")

            # 分批翻译
            trans_map: dict[str, str] = {}
            for bi in range(0, len(texts), engine.batch_size):
                if self._stop_flag:
                    break
                self._pause_event.wait()
                chunk = texts[bi: bi + engine.batch_size]
                self._append_log(self.repair_log,
                                 f"  🌐 翻译第 {bi//engine.batch_size+1} 批（{len(chunk)} 条）...")
                batch = engine.translate_batch(chunk)
                trans_map.update(batch)
                done_items += len(chunk)
                self.after(0, _upd_progress)

            if self._stop_flag:
                break

            # 替换文件中的英文行（只替换仍为英文的行，中文行不动）
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            dlg_re = re.compile(r'(")((?:[^"\\]|\\.)+)(")')

            def replacer(m: re.Match) -> str:
                orig = m.group(2)
                if orig in trans_map and trans_map[orig] != orig:
                    return m.group(1) + trans_map[orig] + m.group(3)
                return m.group(0)

            new_content = dlg_re.sub(replacer, content)
            fpath.write_text(new_content, encoding="utf-8")

            replaced = sum(1 for t in texts if trans_map.get(t, t) != t)
            self._append_log(self.repair_log,
                             f"  ✅ 已替换 {replaced}/{len(texts)} 条 → {fpath.name}")
            done_files += 1
            self.after(0, _upd_progress)

        self._is_repairing = False
        self._pause_event.set()
        # 进度条置满或归零
        final_pct = 1.0 if not self._stop_flag else (done_items / total_items if total_items else 0)
        self.after(0, lambda: self.repair_progress.set(final_pct))
        self.after(0, lambda: self.repair_btn.configure(state="normal"))
        self.after(0, lambda: self.repair_stop_btn.configure(state="disabled"))
        if not self._stop_flag:
            self._append_log(self.repair_log, f"\n✅ 补翻完成，共处理 {done_files} 个文件")
            self.after(0, lambda: self.repair_summary.configure(
                text=f"✅ 补翻完成，处理 {done_files} 个文件", text_color=self.SUCCESS))

    @staticmethod
    def _build_filter_code(trans_map: dict[str, str],
                           lang_code: str, lang_name: str) -> str:
        # 将翻译字典拆分为 500 条一组，避免超大字典
        items = list(trans_map.items())
        chunks = [items[i:i+500] for i in range(0, len(items), 500)]

        lines = [
            f"# 过场动画/小游戏文本过滤器 - {lang_name}",
            f"# 官方方式：wiki.summertimesaga.com/Modding#Cutscenes_and_minigame_instructions",
            f"# 将该文件名点入 manifest.json 的 text_filter 字段，",
            f"# ModManager 会自动読取并注册到 config.say_menu_text_filter",
            f"# 由翻译工具自动生成",
            "",
            "init 10 python:",
        ]

        for ci, chunk in enumerate(chunks):
            lines.append(f"    _translations_{lang_code}_{ci} = {{")
            for orig, translated in chunk:
                orig_esc = orig.replace("\\", "\\\\").replace('"', '\\"')
                trans_esc = translated.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'        "{orig_esc}": "{trans_esc}",')
            lines.append("    }")
            lines.append("")

        # 函数名与 manifest.json 中的 text_filter 字段一致（无下划线前缀）
        func_name = f"{lang_code}_text_filter"
        lines.append(f"    def {func_name}(text):")
        for ci in range(len(chunks)):
            key = f"_translations_{lang_code}_{ci}"
            if ci == 0:
                lines.append(f"        if text in {key}.keys():")
                lines.append(f"            return {key}[text]")
            else:
                lines.append(f"        elif text in {key}.keys():")
                lines.append(f"            return {key}[text]")
        lines.append("        else:")
        lines.append("            return text")
        lines.append("")
        lines.append(f"    config.say_menu_text_filter = {func_name}")

        return "\n".join(lines) + "\n"

    # ---------------------------------------------------------------------------
    # 测试连接
    # ---------------------------------------------------------------------------

    def _test_connection(self):
        self.conn_status.configure(text="连接中...", text_color=self.WARNING)
        self._save_config()

        def worker():
            engine = TranslationEngine(
                api_key=self.api_key.get(),
                base_url=self.api_base.get(),
                model=self.api_model.get(),
            )
            ok, msg = engine.test_connection()
            if ok:
                self.after(0, lambda: self.conn_status.configure(
                    text=f"✅ 连接成功: {msg[:40]}", text_color=self.SUCCESS))
            else:
                self.after(0, lambda: self.conn_status.configure(
                    text=f"❌ {msg[:60]}", text_color=self.DANGER))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------------------------
    # 日志 / 状态
    # ---------------------------------------------------------------------------

    def _append_log(self, textbox: ctk.CTkTextbox, text: str):
        """线程安全的日志写入，通过 after() 在主线程执行。"""
        def _do_insert():
            try:
                textbox.insert("end", text + "\n")
                textbox.see("end")
            except Exception:
                pass
        self.after(0, _do_insert)

    def _set_status(self, text: str, color: str = None):
        color = color or self.TEXT_SEC
        self.after(0, lambda: self.status_label.configure(
            text=text, text_color=color))

    def _start_queue_polling(self):
        def poll():
            # 排空进度队列（由主线程安全操作进度条）
            while not self._progress_queue.empty():
                try:
                    cur, total, msg = self._progress_queue.get_nowait()
                    if total > 0:
                        self.progress_bar.set(cur / total)
                        self.progress_label.configure(text=f"{cur} / {total}")
                except Exception:
                    pass
            self.after(200, poll)
        self.after(200, poll)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
