# 🎮 STS 翻译工具 v1.0

**Summertime Saga 批量翻译工具** — 基于 Ren'Py Modding API，通过大语言模型实现游戏对话全自动汉化。

---

## 🚀 快速开始

### 安装

1. **进入 translator 文件夹**
   ```bash
   cd translator/
   ```

2. **运行启动脚本**（三选一）

   **Windows（最简单）**
   ```bash
   双击 run_translator.bat
   ```

   **PowerShell**
   ```powershell
   .\run_translator.ps1
   ```

   **创建桌面快捷方式**
   ```powershell
   .\create_shortcut.ps1
   ```

3. **等待依赖安装**
   - 首次运行会自动安装 `customtkinter`、`openai`、`requests`
   - 大约 1-2 分钟

---

## 📖 使用流程

### 第 1 步：📦 解压存档

![Decompress](https://via.placeholder.com/400x200?text=Step+1%3A+Extract)

1. 在侧栏点击 **"📦 解压存档"**
2. **设置游戏根目录**
   - 填入包含 `game/` 文件夹的游戏路径
   - 例如：`D:\Games\SummerTimeSaga`
   - 点击"浏览"按钮快速选择

3. **设置解压输出目录**（可选）
   - 默认与游戏目录相同
   - 如需自定义，点击"浏览"

4. **选择要解压的 .rpa 文件**
   - 通常包括 `src.rpa`（核心脚本）、`lib.rpa`（库文件）等
   - 默认全选，可取消不需要的

5. **点击 🚀 开始解压**
   - 日志显示进度
   - 完成后会显示解压的文件数

> ⚠️ **重要**：需要解压出源代码文件（`.rpy`），如果只有 `.rpyc`，请参考 [理解编译版本.md](理解编译版本.md)

---

### 第 2 步：🔍 扫描文本

![Scan](https://via.placeholder.com/400x200?text=Step+2%3A+Scan)

1. 在侧栏点击 **"🔍 扫描文本"**
2. **设置脚本目录**
   - 指向解压后的目录（通常自动填充）
   - 应包含 `scripts/` 子目录或直接包含 `.rpy` 文件

3. **设置文件过滤**
   - `dialogues` = 只处理包含"dialogues"的文件
   - `*` = 处理所有 `.rpy` 文件

4. **点击 🔍 扫描**
   - 工具会递归扫描所有 `.rpy` 文件
   - 自动提取包含对话的标签

5. **查看扫描结果**
   - 显示找到的文件数、标签数、对话条数
   - 每个文件可单独勾选
   - 点击"全选"/"取消"快速操作

> 💡 **提示**：扫描可能需要几秒到十几秒，取决于文件数量

---

### 第 3 步：⚙️ API 设置

![Settings](https://via.placeholder.com/400x200?text=Step+3%3A+Settings)

1. 在侧栏点击 **"⚙️ API 设置"**
2. **填写 API 信息**
   - **API Key**：从支持的平台获取（下方列表）
   - **Base URL**：API 端点（通常预设无需修改）
   - **模型名称**：选择要使用的模型

3. **选择翻译参数**
   - **目标语言名称**：例如"简体中文"、"繁體中文"等
   - **语言代码**：仅英文字母或数字，用作文件后缀（例如 `zh`、`tw`）
   - **每批翻译数量**：分批调用 API，避免超时（默认 20）

4. **点击 🔌 测试连接**
   - 验证 API 密钥和网络连接
   - 连接成功后显示绿色 ✅

5. **点击 💾 保存配置**
   - 下次启动时自动加载

---

### ⚡ 支持的 API 平台

| 平台 | Base URL | 推荐模型 | 备注 |
|------|----------|--------|------|
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` | 需付费，质量最好 |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | 成本低，效果不错 |
| **Anthropic Claude** | `https://api.anthropic.com/v1` | `claude-3-haiku` | Claude 系列 |
| **本地 Ollama** | `http://localhost:11434/v1` | `qwen2.5` | 免费，需本地部署 |

**获取 API Key 的步骤**

1. **OpenAI / DeepSeek / Claude**
   - 访问官方网站注册账号
   - 在账户设置中生成 API Key
   - 确保账户有余额（除非是免费额度）

2. **本地 Ollama（完全免费）**
   - 下载安装 [Ollama](https://ollama.ai)
   - 运行：`ollama pull qwen2.5`
   - 运行：`ollama serve`
   - 工具连接到 `http://localhost:11434/v1`

---

### 第 4 步：🚀 开始翻译

![Translate](https://via.placeholder.com/400x200?text=Step+4%3A+Translate)

1. 在侧栏点击 **"🚀 开始翻译"**
2. **查看统计信息**
   - 📄 待翻译文件
   - 🏷️ 对话标签
   - 💬 对话条数
   - ✅ 已完成数

3. **点击 🚀 开始翻译**（前提：至少选中一个文件）
   - 工具开始调用 LLM API
   - 逐批翻译对话文本
   - 进度条显示翻译进度

4. **等待完成**
   - 日志窗口显示实时进度
   - 翻译速度取决于文件数量和 API 响应速度
   - 大约 100 条对话需要 1-2 分钟

5. **查看输出**
   - 翻译完成后显示"✅ 翻译完成"
   - 日志显示输出目录路径

---

## 📂 输出文件结构

翻译完成后，工具会生成以下文件到 `game/scripts/translation/` 目录：

```
game/scripts/translation/
├── set_language.rpy              # ← 设置游戏语言为目标语言
├── text_filter.rpy               # ← 过场动画/UI 文本过滤器
├── dialogues_zh.rpy              # ← 对话标签翻译（例：中文）
├── characters_dialogue_zh.rpy     # ← 角色对话翻译
└── ... 其他翻译文件
```

---

## 💾 将翻译文件集成到游戏

### 方式 A：直接放入游戏目录（推荐）

1. 核对输出路径：`game/scripts/translation/`
2. 将整个 `translation/` 文件夹复制到游戏的 `game/scripts/` 目录
3. **重启游戏** ✓
4. 游戏会自动加载翻译文件（因为 `set_language.rpy` 会设置 `Game.language`）

### 方式 B：通过 Ren'Py Modding API 创建 Mod

参考 [理解编译版本.md](理解编译版本.md) 中的"方案 B"。

---

## ⚙️ 高级设置 & 常见问题

### Q: 翻译质量如何保证？

A: 
- 工具使用专业的游戏翻译 Prompt
- 保留 Ren'Py 标签（如 `{b}`, `{i}` ）、变量占位符
- 保留换行符格式
- 建议选用高质量模型（如 OpenAI GPT-4）或多语言模型（如 Claude）

### Q: 翻译成本高吗？

A:
- **OpenAI gpt-4o-mini**：~$0.01 美元/1K tokens（100 条对话通常 1K tokens）
- **DeepSeek**：约 1/10 的价格
- **本地 Ollama**：完全免费（需本地部署）

建议先用少量有代表性的对话测试成本，再决定是否全量翻译。

### Q: 支持其他语言吗？

A: 完全支持任何兼容 OpenAI API 的语言：
- 中文（简体/繁体）
- 日语、韩语
- 西班牙语、法语、德语
- 俄语、阿拉伯语等

只需在"API 设置"中修改"目标语言名称"即可。

### Q: 翻译出错了怎么办？

A:
1. **检查 API 错误**
   - 查看"翻译"页面的日志
   - 常见原因：API Key 无效、余额不足、网络问题

2. **重新翻译某些文件**
   - API 调用失败的文件可在"扫描文本"页面重新选中
   - 再次点击"开始翻译"即可

3. **调整批量大小**
   - 如果 API 超时，降低"每批翻译数量"（在"API 设置"中）

### Q: 能否手动编辑翻译？

A: 可以！生成的 `.rpy` 文件是纯文本，可用任何文本编辑器修改：
```python
label bank_liu_account_info_zh:  # ← 标签名（zh = 中文）
    "你好，今天有什么我可以帮助的吗？"  # ← 修改这里的翻译
    return
```

### Q: 如何更新翻译？

A:
1. 修改输出的 `.rpy` 文件
2. **或** 重新扫描和翻译，会覆盖旧文件
3. 重启游戏加载新翻译

---

## 🐛 故障排查

| 症状 | 原因 | 解决方案 |
|------|------|--------|
| 解压卡住 | RPA 文件太大 | 等待或重启；检查磁盘空间 |
| 扫描无结果 | `.rpyc` 编译文件 | 参考 [理解编译版本.md](理解编译版本.md) |
| API 连接失败 | API Key 无效 | 检查 Key、Base URL、网络 |
| 翻译无反应 | API 超时 | 减小批量大小；切换 API |
| 游戏无法运行翻译 | 文件路径错误 | 确保文件在 `game/scripts/translation/` |

---

## 📝 技术细节

### 翻译流程

1. **扫描** → 提取标签和对话文本（去重）
2. **分批** → 按"每批翻译数量"拆分成多个请求
3. **翻译** → 逐批调用 LLM API
4. **生成** → 根据原始标签生成翻译文件（后缀为语言代码）
5. **输出** → 生成 `set_language.rpy` 和 `text_filter.rpy`

### 符合的 Ren'Py 规范

- ✅ [Modding API](https://wiki.summertimesaga.com/Modding)
- ✅ 标签命名：`原标签_语言代码`
- ✅ 语言设置：`Game.language = "代码"`
- ✅ 文本过滤：`config.say_menu_text_filter`

---

## 📜 许可证

本工具基于 Python 和相关开源库。

- **customtkinter** - MIT
- **openai** - MIT
- **requests** - Apache 2.0

游戏翻译需尊重游戏的原始许可证和版权。

---

## 🤝 反馈 & 改进

如有建议或发现 Bug，欢迎反馈：

- 📧 Email：[support@example.com]
- 🐙 GitHub Issues：[link]
- 💬 Discord：[link]

---

**祝你翻译顺利！** 🎮✨

**Version 1.0** | Last Updated: 2026-03-01
