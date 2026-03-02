# 📦 GBCBack (Anki Lossless Engineering Suite)

**GBCBack** 是一款为 Anki 深度玩家、翻译者和牌组开发者设计的无损工程化工具。

它能将黑盒般的 `.apkg` 文件拆解为透明、可读、**Git 友好**的工程目录。你可以在 VS Code 中直接编写 CSS/HTML 模板，像写 Markdown 一样编辑笔记，并 100% 无损地打包回 Anki，保留所有复习进度。

---

## ✨ 核心特性

*   **🛡️ 100% 无损循环 (Lossless Round-trip)**：不仅仅是内容，连卡片的复习间隔、易度系数、到期时间等调度数据也完整保留。
*   **📝 人性化笔记编辑 (`notes.yaml`)**：
    *   支持 YAML 格式导出。利用 YAML 的块状标量（`|`），你可以直接编写多行 HTML 笔记，无需处理烦人的 `\n` 转义。
*   **🎨 模板即文件 (Template-as-File)**：
    *   自动提取 CSS 和 HTML 模板到 `templates/` 目录。
    *   **双向同步**：在打包时，工具会自动检测文件夹中的样式和布局修改并同步回牌组。
*   **🚀 深度兼容与高性能**：
    *   原生支持 **Zstandard (Zstd)** 压缩和 **Protobuf** 媒体索引（兼容 Anki 2.1.50+）。
    *   内置进度条，处理上万张卡片时依然游刃有余。

---

## 🛠️ 安装

本项目使用 [Poetry](https://python-poetry.org/) 进行依赖管理。

```bash
# 克隆仓库
git clone https://github.com/YourUsername/gbcback.git
cd gbcback

# 安装核心依赖 (确保安装了 zstandard 和 pyyaml)
poetry install
```

---

## 📖 快速上手

### 1. 解包 (Unpack)
将 `.apkg` 转化为可编辑的项目工程。

```bash
poetry run gbcback unpack my_deck.apkg -o my_project
```

### 2. 编辑与开发

解包后的工程结构如下：

```text
my_project/
├── templates/           # ✨ 模板开发区
│   └── NotetypeName/
│       ├── style.css    # 直接修改 CSS 样式
│       ├── 0_front.html # 修改卡片正面布局
│       └── 0_back.html  # 修改卡片背面布局
├── notes.yaml           # ✨ 笔记编辑区 (推荐：像写 Markdown 一样翻译内容)
├── media/               # 真实文件名的媒体库
├── collection.json      # 全局配置 (牌组选项、元数据)
├── notes.jsonl          # 笔记备份 (机器友好)
└── cards.jsonl          # 调度数据 (请勿手动修改)
```

### 3. 打包 (Pack)
将修改后的项目重新封装。打包器会自动检测 `templates/` 中的改动以及 `notes.yaml` 和 `notes.jsonl` 两者修改时间状态，优先使用最新文件。

```bash
poetry run gbcback pack my_project -o updated_deck.apkg
```

---

## 💡 高级工作流

### 像写代码一样管理记忆
我们强烈建议在项目目录运行 `git init`。
1.  **版本追踪**：通过 `git diff` 检查你的翻译改动或 CSS 调整。
2.  **安全回滚**：如果批量正则替换搞砸了 HTML 标签，只需 `git checkout notes.yaml` 即可瞬间恢复。
3.  **多人协作**：可以通过 GitHub 团队协作翻译大型牌组，最后由一人统一打包。

### 处理大型牌组
对于超过 10,000 条记录的超大型牌组，读取 `notes.yaml` 可能会稍慢。此时你可以删除 `notes.yaml`，直接修改 `notes.jsonl`（虽然可读性略差，但处理速度极快），打包器会自动切换到 JSONL 模式。

---

## ⚠️ 开发注意事项

*   **ID 唯一性**：请务必保持 `notes.yaml` 和 `cards.jsonl` 中的 `"id"` 和 `"guid"` 不变，这是 Anki 识别卡片身份的唯一凭证。
*   **YAML 格式**：编辑 `notes.yaml` 时请确保缩进正确。
*   **媒体引用**：如果你替换了 `media/` 下的文件，请确保其文件名与笔记中的引用保持一致。

---

## 📜 许可证

[MIT License](LICENSE)

---

## 🧠 设计哲学

> "Memory is data, and data should be free."
> 
> GBCBack 诞生的初衷是消除 Anki 数据存储的黑盒化，让每一位学习者都能拥有对自己学习记录的绝对控制权。
