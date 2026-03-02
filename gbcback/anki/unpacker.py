# gbcback/anki/unpacker.py

import json
import shutil
import logging
import yaml
from pathlib import Path
from tqdm import tqdm
from typing import Dict, Any

# 引入我们已经重构好的组件
from .parser import AnkiPackage, AnkiMediaExtractor
from .reader import AnkiDatabase


class AnkiUnpacker:
    """
    Anki 解包器。

    职责：
    1. 调用 Parser 将 APKG 解压并标准化。
    2. 调用 Reader 读取 SQLite 数据。
    3. 将数据序列化为 "Git-Friendly" 的文件结构 (JSON/JSONL)。
    """

    def __init__(self, apkg_path: Path, output_dir: Path):
        self.apkg_path = apkg_path
        self.output_dir = output_dir

    def run(self):
        """执行解包流程"""
        print(f"🚀 开始解包: {self.apkg_path.name}")

        # 1. 环境准备
        # 如果目标目录已存在，先清空，确保状态纯净
        if self.output_dir.exists():
            print(f"   - 清理旧目录: {self.output_dir}")
            shutil.rmtree(self.output_dir)

        self.output_dir.mkdir(parents=True)

        # 创建一个临时目录用于存放解压后的原始文件 (SQLite + 数字文件名媒体)
        temp_extract_dir = self.output_dir / ".temp_extract"

        try:
            # 2. 物理层解压 (Zip -> Temp Dir)
            pkg = AnkiPackage(self.apkg_path)
            pkg.extract_to(temp_extract_dir)

            # 3. 媒体层还原 (Temp Dir -> Output/media)
            # AnkiMediaExtractor 负责把 "0" 重命名为 "apple.jpg"
            print("   - 正在还原媒体文件...")
            media_extractor = AnkiMediaExtractor(temp_extract_dir)
            # 显式指定输出目录为项目的 media 子目录
            media_extractor.media_output_dir = self.output_dir / "media"
            media_extractor.organize()

            # 4. 数据层导出 (SQLite -> JSON/JSONL)
            db_path = temp_extract_dir / "collection.anki2"
            if not db_path.exists():
                raise RuntimeError("解压后未找到 collection.anki2 数据库")

            self._dump_database(db_path)

            print(f"✅ 解包成功！项目已生成于: {self.output_dir}")
            print(f"   - 媒体: {self.output_dir / 'media'}")
            print(f"   - 数据: {self.output_dir}/*.jsonl")
            print(f"   - 模板: {self.output_dir / 'templates'}")

        except Exception as e:
            print(f"❌ 解包失败: {e}")
            # 失败时不清理目录，方便调试？或者清理？这里选择不清理以便排查
            raise e
        finally:
            # 5. 清理临时文件
            if temp_extract_dir.exists():
                try:
                    shutil.rmtree(temp_extract_dir)
                except Exception as e:
                    logging.warning(f"无法清理临时目录: {e}")

    def _dump_database(self, db_path: Path):
        """将数据库内容导出为 JSON/JSONL 文件"""
        print("   - 正在导出数据库内容...")

        # 使用只读模式打开数据库
        with AnkiDatabase(db_path) as db:
            # A. 导出全局配置 (collection.json)
            # 包含 Models, Decks, Dconf 等。结构复杂，使用 indent=2 方便阅读。
            col_data = db.get_col_data()

            # 如果 col['models'] 是空的，尝试从 modern 表读取
            if not col_data.get('models'):
                print("   - 检测到现代数据库结构，正在解析 Protobuf 模板...")
                col_data['models'] = db.get_models_from_tables()

            self._write_json(col_data, "collection.json", indent=2)

            # B. 导出笔记 (notes.jsonl)
            # 核心数据
            # 同时生成 JSONL（供机器/备份）和 YAML（供人类编辑）
            # 注意：由于迭代器只能用一次，我们需要转一下
            notes = list(db.iter_notes())
            self._write_jsonl(notes, "notes.jsonl")
            self._write_yaml(notes, "notes.yaml") # <--- 新增

            # C. 导出卡片 (cards.jsonl)
            # 核心调度数据。必须保存，否则进度丢失。
            self._write_jsonl(db.iter_cards(), "cards.jsonl")

            # D. 导出复习日志 (revlog.jsonl)
            # 历史记录。可选，但建议保留以备无患。
            revlog_iter = db.iter_revlog()
            if revlog_iter:
                self._write_jsonl(revlog_iter, "revlog.jsonl")

            # E. 核心优化：可视化模板导出 (CSS/HTML)
            self._extract_visual_templates(col_data['models'])

    def _write_json(self, data: Any, filename: str, indent: int = None):
        """辅助方法：写入单个 JSON 文件"""
        target = self.output_dir / filename
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

    def _write_jsonl(self, iterator, filename: str):
        """辅助方法：写入 JSON Lines 文件"""
        target = self.output_dir / filename
        count = 0
        with open(target, "w", encoding="utf-8") as f:
            for item in tqdm(iterator, desc=f"导出 {filename}", unit="row", leave=False):
                # ensure_ascii=False 保证中文不被转义，减少文件体积且可读
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        print(f"     -> {filename}: {count} 条记录")

    def _extract_visual_templates(self, models: Dict):
        """将模板提取为独立文件，方便 Git 追踪和人类编辑"""
        tmpl_root = self.output_dir / "templates"
        tmpl_root.mkdir(exist_ok=True)

        print(f"   - 正在提取可视化模板到: {tmpl_root.name}/")

        for m_id, model in models.items():
            # 为每个模型创建一个文件夹
            safe_model_name = "".join(c for c in model['name'] if c.isalnum() or c in " _-")
            model_dir = tmpl_root / safe_model_name
            model_dir.mkdir(exist_ok=True)

            # 1. 导出 CSS
            with open(model_dir / "style.css", "w", encoding="utf-8") as f:
                f.write(model.get('css', ''))

            # 2. 导出每个卡片类型的 HTML
            for i, t in enumerate(model.get('tmpls', [])):
                t_name = "".join(c for c in t['name'] if c.isalnum() or c in " _-")
                with open(model_dir / f"{i}_{t_name}_front.html", "w", encoding="utf-8") as f:
                    f.write(t.get('qfmt', ''))
                with open(model_dir / f"{i}_{t_name}_back.html", "w", encoding="utf-8") as f:
                    f.write(t.get('afmt', ''))

    def _write_yaml(self, iterator, filename: str):
        """将数据写入 YAML，优化多行字符串显示"""
        target = self.output_dir / filename

        # 强制让带有换行符的字符串使用 | 语法
        def str_presenter(dumper, data):
            if '\n' in data:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            return dumper.represent_scalar('tag:yaml.org,2002:str', data)

        yaml.add_representer(str, str_presenter)

        # 我们先将所有数据转为列表
        data_list = list(iterator)

        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(
                data_list,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000  # 防止自动折行破坏 HTML
            )
        print(f"     -> {filename}: {len(data_list)} 条记录 (人类友好格式)")