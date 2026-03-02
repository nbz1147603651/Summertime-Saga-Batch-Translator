# STS Translation Tool v1.0

**Summertime Saga Batch Translation Tool** — fully automates Chinese localization of game dialogues using a Large Language Model (LLM), directly modifying `.rpy` source files without relying on the deprecated `Game.language` API, and compatible with the new v21.0.0 architecture.

---

## Feature Overview

| Feature Module                | Description                                                                                          |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| 📦 Archive Extraction         | Supports RPA v2 / v3 formats and extracts `.rpa` archives into editable source files                 |
| 🔍 Text Scanning              | Recursively scans `.rpy` files in a directory and automatically extracts labels containing dialogues |
| ⚙️ API Settings               | Compatible with OpenAI / DeepSeek / Ollama and other OpenAI-compatible interfaces                    |
| 🚀 Batch Translation          | Multithreaded translation with pause/resume/stop support, and automatic backup of original files     |
| 🔄 Missing Translation Repair | Scans translated files for remaining English dialogue and performs a second-pass translation         |
| 🛡️ Backup & Restore          | Check backup status and restore all original files with one click                                    |

---

## Quick Start

### Option A: Run Directly (Python Required)

1. Make sure **Python 3.8+** is installed ([Download](https://www.python.org/downloads/))
2. Enter the `translator/` directory and run the main program directly:

   ```bash
   python translator_app.py
   ```

   On first launch, required dependencies (`customtkinter`, `openai`, `requests`) will be installed automatically. This takes about 1–2 minutes.

### Option B: Package as a Standalone `.exe` (Recommended for Distribution)

1. Make sure **Python 3.8+** is installed
2. Double-click **`build.bat`** or run it from the command line:

   ```bat
   build.bat
   ```
3. Wait 2–5 minutes. After packaging is complete, the output will be in `dist\STS翻译工具\`
4. Distribute the entire `dist\STS翻译工具\` folder to others. They can run it by double-clicking `STS翻译工具.exe` (no Python installation required)

---

## 📖 Usage Workflow

### Step 1: 📦 Extract Archives

![Decompress](https://via.placeholder.com/400x200?text=Step+1%3A+Extract)

1. Click **"📦 Extract Archives"** in the sidebar

2. **Set the game root directory**

   * Enter the game path that contains the `game/` folder
   * Example: `D:\Games\SummerTimeSaga`
   * Click the "Browse" button for quick selection

3. **Set the extraction output directory** (optional)

   * Defaults to the same directory as the game
   * If you want to customize it, click "Browse"

4. **Select the `.rpa` files to extract**

   * Usually includes `src.rpa` (core scripts), `lib.rpa` (library files), etc.
   * All are selected by default; uncheck any you do not need

5. **Click 🚀 Start Extraction**

   * The log shows progress
   * After completion, it will display the number of extracted files

> ⚠️ **Important**: You need to extract source code files (`.rpy`). If you only have `.rpyc`, please refer to [Understanding Compiled Builds.md](理解编译版本.md)

---

### Step 2: 🔍 Scan Text

![Scan](https://via.placeholder.com/400x200?text=Step+2%3A+Scan)

1. Click **"🔍 Scan Text"** in the sidebar

2. **Set the script directory**

   * Point it to the extracted directory (usually auto-filled)
   * It should contain a `scripts/` subdirectory or directly contain `.rpy` files

3. **Set file filtering**

   * `dialogues` = process only files containing "dialogues"
   * `*` = process all `.rpy` files

4. **Click 🔍 Scan**

   * The tool will recursively scan all `.rpy` files
   * It will automatically extract labels containing dialogue

5. **View scan results**

   * Displays the number of files found, labels, and dialogue lines
   * Each file can be selected individually
   * Click "Select All" / "Deselect" for quick operations

> 💡 **Tip**: Scanning may take a few seconds to over ten seconds, depending on the number of files

---

### Step 3: ⚙️ API Settings

![Settings](https://via.placeholder.com/400x200?text=Step+3%3A+Settings)

1. Click **"⚙️ API Settings"** in the sidebar

2. **Enter API information**

   * **API Key**: Obtain it from a supported platform (see list below)
   * **Base URL**: API endpoint (usually preset and does not need modification)
   * **Model Name**: Select the model you want to use

3. **Choose translation parameters**

   * **Target Language Name**: e.g., "Simplified Chinese", "Traditional Chinese", etc.
   * **Language Code**: letters/numbers only, used as the file suffix (e.g., `zh`, `tw`)
   * **Batch Size**: number of entries per API request to avoid timeout (default: 20)

4. **Click 🔌 Test Connection**

   * Verifies the API key and network connection
   * A green ✅ will appear if the connection succeeds

5. **Click 💾 Save Configuration**

   * It will be loaded automatically the next time you start the tool

---

### ⚡ Supported API Platforms

| Platform             | Base URL                       | Recommended Model | Notes                           |
| -------------------- | ------------------------------ | ----------------- | ------------------------------- |
| **OpenAI**           | `https://api.openai.com/v1`    | `gpt-4o-mini`     | Paid, best quality              |
| **DeepSeek**         | `https://api.deepseek.com/v1`  | `deepseek-chat`   | Low cost, good results          |
| **Anthropic Claude** | `https://api.anthropic.com/v1` | `claude-3-haiku`  | Claude family                   |
| **Local Ollama**     | `http://localhost:11434/v1`    | `qwen2.5`         | Free, requires local deployment |

**Steps to get an API Key**

1. **OpenAI / DeepSeek / Claude**

   * Visit the official website and register an account
   * Generate an API Key in account settings
   * Make sure your account has credit/balance (unless free quota is available)

2. **Local Ollama (Completely Free)**

   * Download and install [Ollama](https://ollama.ai)
   * Run: `ollama pull qwen2.5`
   * Run: `ollama serve`
   * Configure the tool to connect to `http://localhost:11434/v1`

---

### Step 4: 🚀 Start Translation

![Translate](https://via.placeholder.com/400x200?text=Step+4%3A+Translate)

1. Click **"🚀 Start Translation"** in the sidebar

2. **Check statistics**

   * 📄 Files to translate
   * 🏷️ Dialogue labels
   * 💬 Dialogue lines
   * ✅ Completed count

3. **Click 🚀 Start Translation** (Prerequisite: at least one file must be selected)

   * The tool starts calling the LLM API
   * Dialogue text is translated batch by batch
   * The progress bar displays translation progress

4. **Wait for completion**

   * The log window shows real-time progress
   * Translation speed depends on the number of files and API response speed
   * Roughly 100 dialogue lines take 1–2 minutes

5. **Check output**

   * After completion, it shows "✅ Translation Completed"
   * The log displays the output directory path

---

## 📂 Output File Structure

After translation is complete, the tool generates the following files in the `game/scripts/translation/` directory:

```text
game/scripts/translation/
├── set_language.rpy               # ← Set game language to target language
├── text_filter.rpy                # ← Cutscene/UI text filter
├── dialogues_zh.rpy               # ← Dialogue label translations (example: Chinese)
├── characters_dialogue_zh.rpy     # ← Character dialogue translations
└── ... other translation files
```

---

## 💾 Integrating Translation Files into the Game

### Option A: Put Them Directly into the Game Directory (Recommended)

1. Verify the output path: `game/scripts/translation/`
2. Copy the entire `translation/` folder into the game's `game/scripts/` directory
3. **Restart the game** ✓
4. The game will automatically load translation files (because `set_language.rpy` sets `Game.language`)

### Option B: Create a Mod via the Ren'Py Modding API

Refer to **"Option B"** in [Understanding Compiled Builds.md](理解编译版本.md).

---

## ⚙️ Advanced Settings & FAQ

### Q: How is translation quality ensured?

A:

* The tool uses a professional game-translation prompt
* Preserves Ren'Py tags (such as `{b}`, `{i}`) and variable placeholders
* Preserves line break formatting
* It is recommended to use high-quality models (such as OpenAI GPT-4) or multilingual models (such as Claude)

### Q: Is translation expensive?

A:

* **OpenAI gpt-4o-mini**: ~$0.01 USD / 1K tokens (100 dialogue lines are usually around 1K tokens)
* **DeepSeek**: about 1/10 of the price
* **Local Ollama**: completely free (requires local deployment)

It is recommended to test costs with a small but representative set of dialogue first, then decide whether to translate everything.

### Q: Does it support other languages?

A: Fully supports any language supported by OpenAI-compatible APIs:

* Chinese (Simplified / Traditional)
* Japanese, Korean
* Spanish, French, German
* Russian, Arabic, etc.

You only need to modify the **Target Language Name** in **"API Settings"**.

### Q: What if translation fails?

A:

1. **Check API errors**

   * View logs on the "Translation" page
   * Common causes: invalid API Key, insufficient balance, network issues

2. **Retranslate certain files**

   * Files that failed API calls can be reselected on the "Scan Text" page
   * Click "Start Translation" again

3. **Adjust batch size**

   * If the API times out, reduce the **Batch Size** (in "API Settings")

### Q: Can I manually edit the translations?

A: Yes! The generated `.rpy` files are plain text and can be edited with any text editor:

```python
label bank_liu_account_info_zh:  # ← Label name (zh = Chinese)
    "Hello, what can I help you with today?"  # ← Edit the translation here
    return
```

### Q: How do I update translations?

A:

1. Edit the output `.rpy` files
2. **Or** rescan and retranslate (this will overwrite old files)
3. Restart the game to load the new translations

---

## 🐛 Troubleshooting

| Symptom                        | Cause                       | Solution                                               |
| ------------------------------ | --------------------------- | ------------------------------------------------------ |
| Extraction freezes             | RPA file is too large       | Wait or restart; check disk space                      |
| No scan results                | `.rpyc` compiled files only | Refer to [Understanding Compiled Builds.md](理解编译版本.md) |
| API connection failed          | Invalid API Key             | Check Key, Base URL, and network                       |
| No response during translation | API timeout                 | Reduce batch size; switch API                          |
| Game cannot load translation   | Incorrect file path         | Ensure files are in `game/scripts/translation/`        |

---

## 📝 Technical Details

### Translation Workflow

1. **Scan** → Extract labels and dialogue text (deduplicated)
2. **Batching** → Split into multiple requests according to "Batch Size"
3. **Translate** → Call the LLM API batch by batch
4. **Generate** → Generate translation files based on original labels (suffix = language code)
5. **Output** → Generate `set_language.rpy` and `text_filter.rpy`

### Ren'Py Conventions Followed

* ✅ [Modding API](https://wiki.summertimesaga.com/Modding)
* ✅ Label naming: `original_label_languagecode`
* ✅ Language setting: `Game.language = "code"`
* ✅ Text filter: `config.say_menu_text_filter`

---

## 📜 License

This tool is built with Python and related open-source libraries.

* **customtkinter** - MIT
* **openai** - MIT
* **requests** - Apache 2.0

Game translation must respect the original license and copyright of the game.

---

## 🤝 Feedback & Improvements

If you have suggestions or find a bug, feel free to reach out:

* 📧 Email: [[support@example.com](mailto:support@example.com)]
* 🐙 GitHub Issues: [link]
* 💬 Discord: [link]

---

**Happy translating!** 🎮✨

**Version 1.0** | Last Updated: 2026-03-01
