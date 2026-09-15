#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api-contract-diff 依赖安装。

用法:
    python scripts/setup.py

本技能的字段比对脚本 diff_fields.py 仅依赖 Python 标准库 json/re/sys，
无需安装任何第三方包，因此此处无需执行安装。保留本文件以符合技能目录约定。
"""

PACKAGES = []


def main() -> int:
    if not PACKAGES:
        print("无第三方依赖，无需安装。diff_fields.py 仅用 Python 标准库。")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
