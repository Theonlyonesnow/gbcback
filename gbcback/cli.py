# gbcback/cli.py

import argparse
import sys
import logging
from pathlib import Path
from textwrap import dedent
from colorama import Fore, Style, init

# 初始化颜色（Windows 支持）
init(autoreset=True)

from .anki.unpacker import AnkiUnpacker
from .anki.packer import AnkiPacker
from .anki.verifier import APKGVerifier


def cmd_unpack(args):
    apkg_path = Path(args.input_file)
    output_dir = args.output_dir or Path(apkg_path.stem)

    print(f"\n{Fore.CYAN}📂 模式: 解包 (APKG -> Project)")
    print(f"{Fore.YELLOW}输入: {apkg_path}")
    print(f"{Fore.YELLOW}输出: {output_dir}\n")

    try:
        unpacker = AnkiUnpacker(apkg_path, output_dir)
        unpacker.run()
        print(f"\n{Fore.GREEN}✨ 解包成功！你可以现在去修改项目文件了。")
    except Exception as e:
        print(f"\n{Fore.RED}💥 错误: {e}")
        # sys.exit(1)


def cmd_pack(args):
    project_dir = Path(args.project_dir)
    output_file = args.output_file or Path(f"{project_dir.name}_rebuilt.apkg")

    print(f"\n{Fore.CYAN}📦 模式: 打包 (Project -> APKG)")
    print(f"{Fore.YELLOW}源目录: {project_dir}")
    print(f"{Fore.YELLOW}输出文件: {output_file}\n")

    try:
        packer = AnkiPacker(project_dir, output_file)
        packer.run()

        if args.verify:
            print(f"\n{Fore.CYAN}🔍 正在验证生成的包...")
            verifier = APKGVerifier(output_file)
            verifier.verify()

        print(f"\n{Fore.GREEN}🚀 全部完成！你可以将 {output_file.name} 导入 Anki 了。")
    except Exception as e:
        print(f"\n{Fore.RED}💥 打包失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="gbcback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=dedent(f"""
            {Fore.BLUE}GBCBack - Anki 无损解包/打包工具 (Pro Edition)
            ------------------------------------------------
            此工具可以将 Anki 牌组转换为可编辑的 JSON/HTML/CSS 格式，
            修改后再原样打包回 Anki，确保复习进度 100% 完整。
        """))

    subparsers = parser.add_subparsers(dest="command", required=True)

    # unpack
    p_unpack = subparsers.add_parser("unpack", help="解包 APKG 到文件夹")
    p_unpack.add_argument("input_file", help="输入的 .apkg 文件")
    p_unpack.add_argument("-o", "--output-dir", type=Path, help="输出项目目录")
    p_unpack.set_defaults(func=cmd_unpack)

    # pack
    p_pack = subparsers.add_parser("pack", help="从文件夹打包回 APKG")
    p_pack.add_argument("project_dir", help="项目文件夹")
    p_pack.add_argument("-o", "--output-file", type=Path, help="生成的 .apkg 文件名")
    p_pack.add_argument("--no-verify", dest="verify", action="store_false", help="打包后跳过自检")
    p_pack.set_defaults(func=cmd_pack, verify=True)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()