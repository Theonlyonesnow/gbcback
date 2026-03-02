# gbcback/anki/verifier.py

import sqlite3
import json
import tempfile
from pathlib import Path
from typing import Dict

# 复用 parser 中的解压逻辑，确保能处理 Zstd 压缩的数据库
from .parser import AnkiPackage


class APKGVerifier:
    def __init__(self, apkg_path: Path):
        self.apkg_path = apkg_path
        if not self.apkg_path.exists():
            raise FileNotFoundError(f"APKG 不存在: {apkg_path}")

    def verify(self):
        """执行全套体检"""
        print(f"🔍 正在自检 APKG: {self.apkg_path.name} ...")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1. 解压检查 (使用 AnkiPackage 以支持 .anki21b)
            try:
                pkg = AnkiPackage(self.apkg_path)
                pkg.extract_to(tmp_path)
            except Exception as e:
                self._fail(f"解压或数据库标准化失败: {e}")

            # 2. 数据库完整性检查
            # parser 会自动将 .anki21b 还原为 collection.anki2
            db_path = tmp_path / "collection.anki2"
            if not db_path.exists():
                self._fail("未找到有效的 collection.anki2 (数据库还原失败)")

            self._verify_database(db_path)

            # 3. 媒体一致性检查
            # 此时所有文件已解压到 tmp_path，直接检查文件是否存在
            self._verify_media(tmp_path)

        print("✅ 自检通过！此 APKG 是健康的。")

    def _verify_database(self, db_path: Path):
        """检查数据库逻辑一致性"""
        # 使用只读模式连接
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        try:
            # A. 检查 Decks 注册表
            cursor = conn.execute("SELECT decks FROM col")
            col_row = cursor.fetchone()
            if not col_row:
                self._fail("col 表为空，严重损坏")

            try:
                decks_json = col_row['decks']
                # 兼容处理：有时是字符串，有时可能已经是解析后的(取决于驱动)，这里假设是原始字符串
                if isinstance(decks_json, str):
                    decks_data = json.loads(decks_json)
                else:
                    decks_data = decks_json  # 极少情况
            except json.JSONDecodeError:
                self._fail("col.decks JSON 解析失败")

            registered_deck_ids = set([int(k) for k in decks_data.keys()])
            print(f"   - 发现注册牌组 ID: {registered_deck_ids}")

            # B. 检查 Cards 归属
            cursor = conn.execute("SELECT DISTINCT did FROM cards")
            used_deck_ids = set([row['did'] for row in cursor])

            if not used_deck_ids:
                # 这是一个非常有用的警告，但不一定是错误（可能是空包）
                print("   ⚠️ 警告：包内没有卡片 (cards 表为空)")
            else:
                # 核心断言：所有卡片的 did 必须在 decks 表里注册过
                ghost_decks = used_deck_ids - registered_deck_ids
                if ghost_decks:
                    self._fail(f"发现幽灵牌组！Cards 指向了未注册的 ID: {ghost_decks}")
                print(f"   - 牌组关联检查通过 (卡片分布在 {len(used_deck_ids)} 个牌组中)")

            # C. 简单的 Notes 检查 (新增)
            cursor = conn.execute("SELECT COUNT(*) FROM notes")
            notes_count = cursor.fetchone()[0]
            print(f"   - 笔记数据检查: 发现 {notes_count} 条笔记")

        finally:
            conn.close()

    def _verify_media(self, base_dir: Path):
        """检查媒体映射表中的文件是否真实存在于解压目录中"""
        media_file = base_dir / "media"
        if not media_file.exists():
            return

        try:
            with open(media_file, 'r', encoding='utf-8') as f:
                media_map = json.load(f)
        except Exception as e:
            self._fail(f"media 文件解析失败: {e}")

        # media_map 格式: {"0": "apple.jpg", "1": "sound.mp3"}
        # 此时 base_dir 下应该有文件名为 "0", "1" 的文件

        missing_files = []
        for key in media_map.keys():
            expected_file = base_dir / key
            if not expected_file.exists():
                missing_files.append(key)

        if missing_files:
            self._fail(
                f"媒体文件丢失！映射表中引用了 {len(missing_files)} 个文件 (如 {missing_files[:3]}...) 但ZIP包中不存在。")

        print(f"   - 媒体一致性检查通过 ({len(media_map)} 个文件)")

    def _fail(self, reason: str):
        print(f"❌ APKG 自检失败: {reason}")
        raise RuntimeError(f"APKG Verification Failed: {reason}")