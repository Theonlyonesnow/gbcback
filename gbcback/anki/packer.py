# gbcback/anki/packer.py

import sqlite3
import json
import zipfile
import shutil
import time
import os
import yaml
from pathlib import Path
from tqdm import tqdm
from typing import Dict, Any, List


class AnkiPacker:
    """
    Anki 打包器。

    职责：
    1. 创建新的 SQLite 数据库 (collection.anki2)。
    2. 执行 Anki 标准 Schema (创建表结构)。
    3. 从 JSON/JSONL 读取数据并注入数据库 (保持 ID 不变)。
    4. 打包媒体文件并生成 media 映射表。
    5. 生成最终的 .apkg 文件。
    """

    def __init__(self, project_dir: Path, output_apkg: Path):
        self.project_dir = project_dir
        self.output_apkg = output_apkg

        if not (self.project_dir / "collection.json").exists():
            raise FileNotFoundError(f"项目目录无效 (缺少 collection.json): {project_dir}")

    def run(self):
        """执行打包流程"""
        print(f"📦 开始打包: {self.project_dir.name} -> {self.output_apkg.name}")

        # 1. 准备临时工作区
        temp_dir = self.project_dir / ".temp_pack"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True)

        try:
            # 2. 创建并填充数据库
            db_path = temp_dir / "collection.anki2"
            self._create_database(db_path)

            # 3. 准备媒体映射
            media_map = self._prepare_media_map()

            # 4. 生成最终 Zip (.apkg)
            self._zip_package(db_path, media_map, temp_dir)

            print(f"✅ 打包成功！文件已生成: {self.output_apkg}")

        except Exception as e:
            print(f"❌ 打包失败: {e}")
            raise e
        finally:
            # 5. 清理临时文件
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    def _create_database(self, db_path: Path):
        """创建 SQLite 数据库并注入数据"""
        print("   - 正在构建数据库...")

        # 连接数据库
        conn = sqlite3.connect(str(db_path))

        # A. 初始化表结构 (Schema)
        # 这是 Anki 2.1 的标准 Schema。直接执行 SQL 最稳妥。
        self._init_schema(conn)

        # B. 注入全局配置 (col 表)
        col_file = self.project_dir / "collection.json"
        with open(col_file, "r", encoding="utf-8") as f:
            col_data = json.load(f)
            # 自动从 templates/ 同步 HTML/CSS 修改
            self._sync_templates_to_col(col_data)
            self._insert_col(conn, col_data)

        # C. 注入笔记 (notes 表)
        # --- 核心改进：智能探测笔记来源 ---
        yaml_notes = self.project_dir / "notes.yaml"
        jsonl_notes = self.project_dir / "notes.jsonl"

        source_to_use = None

        # 判定逻辑：MECE 原则展开
        if yaml_notes.exists() and jsonl_notes.exists():
            # 两个都存在，对比修改时间
            yaml_time = yaml_notes.stat().st_mtime
            jsonl_time = jsonl_notes.stat().st_mtime

            if yaml_time >= jsonl_time:
                source_to_use = "YAML"
            else:
                source_to_use = "JSONL"

            print(f"   - 💡 检测到双重数据源: 优先选择更新的版本 [{source_to_use}]")
        elif yaml_notes.exists():
            source_to_use = "YAML"
        elif jsonl_notes.exists():
            source_to_use = "JSONL"
        else:
            raise FileNotFoundError("❌ 错误: 项目中缺失 notes.yaml 或 notes.jsonl")


        # 执行注入
        if source_to_use == "YAML":
            print("   - 发现 notes.yaml 较新，正在从 YAML 注入笔记...")
            self._insert_notes_from_yaml(conn, yaml_notes)
        else:
            print("   - 发现 notes.jsonl 较新，正在从 JSONL 注入笔记...")
            self._insert_rows(conn, "notes", jsonl_notes)

        # D. 注入卡片 (cards 表)
        cards_file = self.project_dir / "cards.jsonl"
        self._insert_rows(conn, "cards", cards_file)

        # E. 注入复习日志 (revlog 表) - 可选
        revlog_file = self.project_dir / "revlog.jsonl"
        if revlog_file.exists():
            self._insert_rows(conn, "revlog", revlog_file)

        # 提交并关闭
        conn.commit()
        conn.close()

    def _init_schema(self, conn: sqlite3.Connection):
        """执行 Anki 标准 Schema SQL"""
        # 这些 SQL 语句来自 Anki 源码或逆向工程，确保兼容性
        schema = """
        CREATE TABLE col (
            id              integer primary key,
            crt             integer not null,
            mod             integer not null,
            scm             integer not null,
            ver             integer not null,
            dty             integer not null,
            usn             integer not null,
            ls              integer not null,
            conf            text not null,
            models          text not null,
            decks           text not null,
            dconf           text not null,
            tags            text not null
        );
        CREATE TABLE notes (
            id              integer primary key,
            guid            text not null,
            mid             integer not null,
            mod             integer not null,
            usn             integer not null,
            tags            text not null,
            flds            text not null,
            sfld            integer not null,
            csum            integer not null,
            flags           integer not null,
            data            text not null
        );
        CREATE TABLE cards (
            id              integer primary key,
            nid             integer not null,
            did             integer not null,
            ord             integer not null,
            mod             integer not null,
            usn             integer not null,
            type            integer not null,
            queue           integer not null,
            due             integer not null,
            ivl             integer not null,
            factor          integer not null,
            reps            integer not null,
            lapses          integer not null,
            left            integer not null,
            odue            integer not null,
            odid            integer not null,
            flags           integer not null,
            data            text not null
        );
        CREATE TABLE revlog (
            id              integer primary key,
            cid             integer not null,
            usn             integer not null,
            ease            integer not null,
            ivl             integer not null,
            lastIvl         integer not null,
            factor          integer not null,
            time            integer not null,
            type            integer not null
        );
        CREATE TABLE graves (
            usn             integer not null,
            oid             integer not null,
            type            integer not null
        );
        CREATE INDEX ix_notes_usn on notes (usn);
        CREATE INDEX ix_cards_usn on cards (usn);
        CREATE INDEX ix_revlog_usn on revlog (usn);
        CREATE INDEX ix_cards_nid on cards (nid);
        CREATE INDEX ix_cards_sched on cards (did, queue, due);
        CREATE INDEX ix_revlog_cid on revlog (cid);
        CREATE INDEX ix_notes_csum on notes (csum);
        """
        conn.executescript(schema)

    def _insert_col(self, conn: sqlite3.Connection, data: Dict[str, Any]):
        """插入 col 表数据"""
        """插入 col 表数据，并在插入前同步 templates 文件夹的修改"""
        models = data.get('models', {})
        tmpl_root = self.project_dir / "templates"

        if tmpl_root.exists():
            print("   - 正在同步 templates/ 文件夹中的模板修改...")
            for model_id_str, model in models.items():
                # 根据模型名称寻找文件夹
                safe_model_name = "".join(c for c in model['name'] if c.isalnum() or c in " _-")
                model_dir = tmpl_root / safe_model_name

                if model_dir.exists():
                    # 1. 同步 CSS
                    css_file = model_dir / "style.css"
                    if css_file.exists():
                        model['css'] = css_file.read_text(encoding="utf-8")

                    # 2. 同步 HTML 模板 (qfmt, afmt)
                    for i, t in enumerate(model.get('tmpls', [])):
                        t_name = "".join(c for c in t['name'] if c.isalnum() or c in " _-")
                        front_file = model_dir / f"{i}_{t_name}_front.html"
                        back_file = model_dir / f"{i}_{t_name}_back.html"

                        if front_file.exists():
                            t['qfmt'] = front_file.read_text(encoding="utf-8")
                        if back_file.exists():
                            t['afmt'] = back_file.read_text(encoding="utf-8")

        # 需要把 JSON 对象重新序列化为字符串
        for field in ['models', 'decks', 'dconf', 'conf']:
            if field in data and not isinstance(data[field], str):
                data[field] = json.dumps(data[field], ensure_ascii=False)

        # 构造 INSERT 语句
        placeholders = ", ".join(["?"] * len(data))
        columns = ", ".join(data.keys())
        sql = f"INSERT INTO col ({columns}) VALUES ({placeholders})"
        conn.execute(sql, list(data.values()))

    def _insert_rows(self, conn: sqlite3.Connection, table: str, jsonl_path: Path):
        """通用方法：读取 JSONL 并批量插入"""
        if not jsonl_path.exists():
            return

        print(f"     -> 正在注入 {table}...")


        # 读取第一行以确定列名
        with open(jsonl_path, "r", encoding="utf-8") as f:
            first_line = f.readline()
            if not first_line:
                return
            first_row = json.loads(first_line)
            columns = list(first_row.keys())

        # 准备 SQL
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

        # 批量读取并插入
        batch = []
        batch_size = 1000

        # 统计行数以便显示百分比（可选，如果文件巨大可以跳过统计直接显示进度）
        total_lines = sum(1 for _ in open(jsonl_path, 'r', encoding='utf-8'))

        with open(jsonl_path, "r", encoding="utf-8") as f:

            # 包装文件对象进行迭代
            pbar = tqdm(total=total_lines, desc=f"注入 {table}", unit="row", leave=False)
            for line in f:
                row = json.loads(line)

                # 特殊处理：notes 表的 flds 字段
                if table == 'notes' and 'flds' in row and isinstance(row['flds'], list):
                    # 重新组合为 \x1f 分隔的字符串
                    row['flds'] = "\x1f".join(row['flds'])

                # 确保值的顺序与列名一致
                values = [row.get(col) for col in columns]
                batch.append(values)

                if len(batch) >= batch_size:
                    conn.executemany(sql, batch)
                    batch = []

                pbar.update(1)
            pbar.close()

            # 插入剩余的
            if batch:
                conn.executemany(sql, batch)

    def _prepare_media_map(self) -> Dict[str, str]:
        """准备媒体映射表：真实文件名 -> 数字ID"""
        media_dir = self.project_dir / "media"
        if not media_dir.exists():
            return {}

        media_map = {}  # {"0": "apple.jpg", "1": "sound.mp3"}

        # 遍历所有媒体文件
        idx = 0
        for file in media_dir.iterdir():
            if file.is_file() and not file.name.startswith("."):
                media_map[str(idx)] = file.name
                idx += 1

        return media_map

    def _zip_package(self, db_path: Path, media_map: Dict[str, str], temp_dir: Path):
        """生成最终的 .apkg Zip 包"""
        print("   - 正在压缩 .apkg ...")

        with zipfile.ZipFile(self.output_apkg, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. 添加数据库
            zf.write(db_path, "collection.anki2")

            # 2. 添加媒体映射文件 (media)
            # 注意：Anki 的 media 文件是反向映射 {"0": "apple.jpg"}
            zf.writestr("media", json.dumps(media_map))

            # 3. 添加媒体文件
            # 必须使用映射表中的 Key (数字) 作为 Zip 内的文件名
            media_dir = self.project_dir / "media"
            for zip_name, real_name in tqdm(media_map.items(), desc="压缩媒体", unit="file"):
                src_file = media_dir / real_name
                if src_file.exists():
                    zf.write(src_file, zip_name)

    def _sync_templates_to_col(self, col_data: Dict):
        """从文件系统同步模板修改到 col 对象中"""
        tmpl_root = self.project_dir / "templates"
        if not tmpl_root.exists(): return

        print("   - 正在同步 templates/ 中的可视化模板...")
        models = col_data.get('models', {})
        for m_id, model in models.items():
            safe_name = "".join(c for c in model['name'] if c.isalnum() or c in " _-")
            model_dir = tmpl_root / safe_name
            if not model_dir.exists(): continue

            # 同步 CSS
            css_path = model_dir / "style.css"
            if css_path.exists():
                model['css'] = css_path.read_text(encoding="utf-8")

            # 同步 HTML
            for i, t in enumerate(model.get('tmpls', [])):
                t_safe_name = "".join(c for c in t['name'] if c.isalnum() or c in " _-")
                f_path = model_dir / f"{i}_{t_safe_name}_front.html"
                b_path = model_dir / f"{i}_{t_safe_name}_back.html"
                if f_path.exists(): t['qfmt'] = f_path.read_text(encoding="utf-8")
                if b_path.exists(): t['afmt'] = b_path.read_text(encoding="utf-8")

    def _insert_notes_from_yaml(self, conn, yaml_path):
        """解析 YAML 笔记并注入数据库"""
        with open(yaml_path, "r", encoding="utf-8") as f:
            notes = yaml.safe_load(f)

        if not notes: return

        # 准备 SQL
        columns = list(notes[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO notes ({', '.join(columns)}) VALUES ({placeholders})"

        batch = []
        for n in notes:
            # 转换 flds 列表回 \x1f 字符串
            if isinstance(n.get('flds'), list):
                n['flds'] = "\x1f".join(n['flds'])
            batch.append([n.get(col) for col in columns])

        conn.executemany(sql, batch)
        print(f"     -> 注入了 {len(batch)} 条来自 YAML 的笔记")