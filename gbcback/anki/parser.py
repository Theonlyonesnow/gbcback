# gbcback/anki/parser.py

import zipfile
import shutil
import json
import logging
from pathlib import Path
from typing import Dict
from tqdm import tqdm
from .proto import anki_pb2

# 尝试导入 zstandard，处理新版 Anki 的压缩数据库
try:
    import zstandard as zstd

    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    print("⚠️ 未检测到 zstandard 库。如果你的 APKG 是由新版 Anki 生成的，可能会解压失败。请运行 `pip install zstandard`")

ZSTD_HEADER = b'\x28\xb5\x2f\xfd'


class AnkiPackage:
    """
    负责处理 .apkg 文件的物理层：解压 ZIP 和处理内部的 Zstd 压缩。
    """

    def __init__(self, apkg_path: Path):
        self.path = apkg_path
        if not apkg_path.exists():
            raise FileNotFoundError(f"文件不存在：{apkg_path}")

    def extract_to(self, output_dir: Path):
        """将 APKG 解压到指定目录，并确保 collection.anki2 数据库可用"""
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"📦 正在解压 ZIP: {self.path.name} ...")
        with zipfile.ZipFile(self.path, "r") as zf:
            zf.extractall(output_dir)

        # 处理数据库文件可能的不同命名和压缩状态
        self._normalize_database(output_dir)

    def _normalize_database(self, base_dir: Path):
        """
        处理 collection.anki21b (Zstd) 或 collection.anki21 (SQLite)
        统一还原为 collection.anki2 以便后续读取。
        """
        db_legacy = base_dir / "collection.anki2"
        db_v21 = base_dir / "collection.anki21"
        db_compressed = base_dir / "collection.anki21b"

        # 策略 A: 现代版 (Zstd 压缩)
        if db_compressed.exists():
            if not ZSTD_AVAILABLE:
                raise RuntimeError("发现压缩数据库 (collection.anki21b)，但缺少 zstandard 库，无法解压。")

            print(f"🔓 正在解压 Zstd 数据库 ({db_compressed.name})...")
            self._decompress_zstd(db_compressed, db_legacy)
            # 解压后删除源文件以节省空间？或者保留作为备份，这里选择保留

        # 策略 B: 过渡版 (Anki 2.1 SQLite)
        elif db_v21.exists():
            print(f"🔄 正在迁移 V2.1 数据库 ({db_v21.name})...")
            # 这是一个标准的 SQLite，直接把它覆盖成 collection.anki2
            if db_legacy.exists():
                db_legacy.unlink()
            shutil.move(str(db_v21), str(db_legacy))

        # 策略 C: 传统版
        elif db_legacy.exists():
            # 已经是标准格式，无需操作
            pass

        else:
            raise FileNotFoundError("❌ 严重错误：ZIP 包中未找到任何有效的数据库文件！")

    @staticmethod
    def _decompress_zstd(input_file: Path, output_file: Path):
        dctx = zstd.ZstdDecompressor()
        with input_file.open("rb") as f_in, output_file.open("wb") as f_out:
            dctx.copy_stream(f_in, f_out)


class AnkiMediaExtractor:
    """
    负责处理 'media' 映射文件，将 ZIP 中的数字文件名还原为真实文件名。
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.media_map_file = base_dir / "media"
        self.media_output_dir = base_dir / "media"

    def organize(self):
        """执行重命名和移动操作"""
        if not self.media_map_file.exists():
            logging.warning("未找到 media 映射文件，跳过媒体处理。")
            return

        self.media_output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 智能读取映射表 (处理可能的 Zstd 压缩)
        try:
            with open(self.media_map_file, "rb") as f:
                raw_data = f.read()

            # 检查是否是 Zstd 压缩
            if raw_data.startswith(ZSTD_HEADER):
                if not ZSTD_AVAILABLE:
                    raise RuntimeError("检测到压缩的 media 映射文件，但缺少 zstandard 库。")

                # 解压数据到内存
                dctx = zstd.ZstdDecompressor()
                raw_data = dctx.decompress(raw_data)

            # 2. 尝试解析 (先 JSON，后 Protobuf)
            media_map = {}
            try:
                # 方案 A: JSON
                media_map = json.loads(raw_data.decode("utf-8"))
                print("   - 媒体索引格式: JSON")
            except (UnicodeDecodeError, json.JSONDecodeError):
                # 方案 B: Protobuf (新版 Anki)
                print("   - 媒体索引格式: Protobuf")
                entries = anki_pb2.MediaEntries()
                entries.ParseFromString(raw_data)
                # Protobuf 中 media 是个列表，下标对应文件名 "0", "1", "2"...
                for i, entry in enumerate(entries.entries):
                    media_map[str(i)] = entry.name

        except Exception as e:
            logging.error(f"❌ 解析 media 映射文件失败: {e}")
            return

        # 2. 遍历并重命名 (移动文件)
        print(f"📂 正在整理 {len(media_map)} 个媒体文件...")
        count = 0
        for zip_name, real_name in tqdm(media_map.items(), desc="还原媒体", unit="file"):
            src = self.base_dir / zip_name
            dst = self.media_output_dir / real_name

            if src.exists():
                # 安全性检查：确保目标在媒体目录下
                if dst.parent != self.media_output_dir:
                    continue

                # 移动文件
                shutil.move(str(src), str(dst))
                count += 1

        # 3. 清理 media 映射文件
        self.media_map_file.unlink()
        print(f"✅ 媒体整理完成，共还原 {count} 个文件。")