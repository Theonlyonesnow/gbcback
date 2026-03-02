# gbcback/anki/reader.py

import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, Generator, Optional
from .proto import anki_pb2


class AnkiDatabase:
    """
    Anki 数据库 (collection.anki2) 的只读适配器。

    职责：
    1. 建立只读连接。
    2. 提供流式接口 (Generator) 读取核心表：notes, cards, col。
    3. 负责将数据库中的 JSON 字符串字段展开为 Python 对象。
    """

    def __init__(self, db_path: Path):
        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在：{db_path}")

        self.db_path = db_path
        # 使用 mode=ro (Read-Only) 防止意外修改数据
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        # 使用 Row 工厂，使结果可以像字典一样访问
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def __enter__(self) -> "AnkiDatabase":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_col_data(self) -> Dict[str, Any]:
        """
        获取全局配置 (col 表)。
        这里包含了 Models (笔记类型), Decks (牌组配置), Dconf (牌组选项) 等核心元数据。
        """
        cursor = self.conn.execute("SELECT * FROM col LIMIT 1")
        row = cursor.fetchone()
        if not row:
            raise ValueError("数据库损坏：col 表为空")

        data = dict(row)

        # Anki 在 col 表中存储了大量的 JSON 字符串
        # 我们在这里将它们解析为 Python 对象，以便存入 JSON 文件时是展开的结构
        json_fields = ['models', 'decks', 'dconf', 'conf']
        for field in json_fields:
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = json.loads(data[field])
                except json.JSONDecodeError:
                    # 如果解析失败，保留原字符串（防御性编程）
                    pass

        return data

    def iter_notes(self) -> Generator[Dict[str, Any], None, None]:
        """
        流式读取所有笔记 (notes 表)。
        返回包含所有字段的字典。
        特殊处理：将 flds 字段（\x1f 分隔的字符串）转换为列表。
        """
        cursor = self.conn.execute("SELECT * FROM notes")
        for row in cursor:
            note = dict(row)
            # Anki 使用 0x1f (Unit Separator) 分隔字段
            # 转换为列表方便 JSON 序列化和 Git Diff
            if 'flds' in note and isinstance(note['flds'], str):
                note['flds'] = note['flds'].split('\x1f')
            yield note

    def iter_cards(self) -> Generator[Dict[str, Any], None, None]:
        """
        流式读取所有卡片 (cards 表)。
        这是复习进度（调度算法数据）的核心存储位置。
        必须完整保留 ivl, factor, reps, due, odue 等字段。
        """
        cursor = self.conn.execute("SELECT * FROM cards")
        for row in cursor:
            yield dict(row)

    def iter_revlog(self) -> Generator[Dict[str, Any], None, None]:
        """
        (可选) 流式读取复习日志 (revlog 表)。
        如果你想备份详细的复习历史（哪天复习了哪张卡），就需要导出这个表。
        """
        # 检查表是否存在（有些极简的 APKG 可能删除了 revlog）
        try:
            cursor = self.conn.execute("SELECT * FROM revlog")
            for row in cursor:
                yield dict(row)
        except sqlite3.OperationalError:
            return

    def get_models_from_tables(self) -> Dict[int, Any]:
        """
        从现代数据库表 (notetypes, templates) 中提取模型。
        这是对 get_col_data() 的补充，如果 col 表里没有 models，就从这里拿。
        """
        models = {}
        # 1. 检查是否有 notetypes 表
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notetypes'")
        if not cursor.fetchone():
            return {}

        # 2. 读取所有笔记类型
        nt_cursor = self.conn.execute("SELECT id, name, config FROM notetypes")
        for nt_row in nt_cursor:
            nt_id, nt_name, nt_config_blob = nt_row

            # 解析 Protobuf Config
            nt_config = anki_pb2.NotetypeConfig()
            nt_config.ParseFromString(nt_config_blob)

            # 3. 读取该类型下的所有模板
            tmpls = []
            t_cursor = self.conn.execute("SELECT name, config FROM templates WHERE ntid = ?", (nt_id,))
            for t_row in t_cursor:
                t_name, t_config_blob = t_row
                t_config = anki_pb2.TemplateConfig()
                t_config.ParseFromString(t_config_blob)

                tmpls.append({
                    "name": t_name,
                    "qfmt": t_config.q_format,
                    "afmt": t_config.a_format
                })

            models[nt_id] = {
                "id": nt_id,
                "name": nt_name,
                "css": nt_config.css,
                "tmpls": tmpls
            }
        return models