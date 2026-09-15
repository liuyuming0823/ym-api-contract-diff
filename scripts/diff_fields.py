#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口字段契约检查 - 字段比对脚本（纯标准库，无需安装任何第三方包）。

功能：
  读入两份 JSON（前端样例 / 后端定义，或任意两份结构），扁平化展开为字段路径，
  对字段名做驼峰↔下划线归一化，对类型做「类型族」归一，输出 Markdown 差异报告。

用法：
  python scripts/diff_fields.py a.json b.json
  python scripts/diff_fields.py '{"userId":1}' '{"user_id":1}'
  cat a.json | python scripts/diff_fields.py - b.json

参数：两个位置参数，每个可以是「文件路径」或以 { 或 [ 开头的「内联 JSON」。
      用 - 表示从标准输入读取 JSON。
选项：
  --ignore 字段名   忽略比对（可多次，支持末级字段名匹配）
  --no-risk         关闭高风险项自动探测
"""

import json
import re
import sys
from collections import OrderedDict


# ---------------------------------------------------------------------------
# 类型族归一
# ---------------------------------------------------------------------------
def type_family(value):
    """根据 JSON 取值推断类型族与精确类型。"""
    if isinstance(value, bool):
        return "布尔族", "boolean"
    if isinstance(value, int):
        return "数值族", "integer"
    if isinstance(value, float):
        return "数值族", "float"
    if isinstance(value, str):
        return "字符串族", "string"
    if isinstance(value, list):
        return "数组族", "array"
    if isinstance(value, dict):
        return "对象族", "object"
    if value is None:
        return "空值族", "null"
    return "未知族", type(value).__name__


# ---------------------------------------------------------------------------
# 字段名归一：驼峰 <-> 下划线，统一成下划线形式
# ---------------------------------------------------------------------------
def to_snake(name):
    # 先在大写字母（首个除外）前插下划线
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    # 处理连续大写缩写，如 "ID" -> "id"，但保守处理：仅把整段大写转小写
    s = s.lower()
    # 压缩多余下划线（如已下划线又插入）
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# ---------------------------------------------------------------------------
# 扁平化：object -> 点路径，array 用 [] 表示元素类型容器（不展开下标）
# ---------------------------------------------------------------------------
def flatten(obj, prefix=""):
    """返回 OrderedDict：路径 -> (值, 末级原名)。"""
    out = OrderedDict()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                if not v:  # 空对象仍记录
                    out[path] = (v, k)
                out.update(flatten(v, path))
            elif isinstance(v, list):
                out[path] = (v, k)
                # 展开数组首个元素以探测元素结构
                if v and isinstance(v[0], (dict, list)):
                    out.update(flatten(v[0], f"{path}[]"))
            else:
                out[path] = (v, k)
    else:
        # 顶层不是对象时
        out[prefix or "(root)"] = (obj, prefix or "(root)")
    return out


# ---------------------------------------------------------------------------
# 高风险项探测
# ---------------------------------------------------------------------------
_DATE_HINT = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2})?")


def detect_risk(path, value, family, precise):
    risks = []
    if family == "数值族" and precise == "integer":
        if isinstance(value, int) and abs(value) > 2**53 - 1:
            risks.append("Long/大整数超 JS 安全整数(2^53)，前端精度丢失")
    if family == "数值族" and precise == "float":
        risks.append("浮点类型，金额/比例类字段有精度误差风险")
    if family == "字符串族" and isinstance(value, str):
        if _DATE_HINT.match(value) or "T" in value and re.search(r"\d{2}:\d{2}", value):
            risks.append("疑似日期时间但仅标字符串，格式/时区需明确")
    return risks


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def load_input(arg):
    if arg == "-":
        return json.load(sys.stdin)
    text = arg.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    with open(arg, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opts = [a for a in argv if a.startswith("--")]
    ignore = set()
    no_risk = False
    for o in opts:
        if o.startswith("--ignore="):
            ignore.add(to_snake(o.split("=", 1)[1]))
        elif o == "--no-risk":
            no_risk = True
        elif o == "--ignore":
            pass  # 后跟值的情况简单忽略，由调用方用 --ignore= 形式

    if len(args) < 2:
        sys.stderr.write("用法: python diff_fields.py <a.json|inline> <b.json|inline>\n")
        return 2

    try:
        a = load_input(args[0])
        b = load_input(args[1])
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"读取输入失败: {e}\n")
        return 1

    fa = flatten(a)
    fb = flatten(b)

    # 按归一名归并，保留两侧原名字
    def build(index):
        table = OrderedDict()
        for path, (val, orig) in index.items():
            canon = to_snake(orig)
            fam, prec = type_family(val)
            table.setdefault(canon, {"paths": [], "origs": [], "fam": fam,
                                     "prec": prec, "val": val, "path": path})
            table[canon]["paths"].append(path)
            table[canon]["origs"].append(orig)
        return table

    ta = build(fa)
    tb = build(fb)

    canon_all = list(OrderedDict.fromkeys(list(ta.keys()) + list(tb.keys())))

    lines = []
    lines.append("# 接口字段差异报告（脚本生成）\n")

    # 字段清单
    lines.append("## 字段清单（归一化后）\n")
    lines.append("| 归一名 | A 原字段 | A 类型(族/精确) | B 原字段 | B 类型(族/精确) |")
    lines.append("|---|---|---|---|---|")
    for c in canon_all:
        ainfo = ta.get(c)
        binfo = tb.get(c)
        aorig = "/".join(ainfo["origs"]) if ainfo else "-"
        borig = "/".join(binfo["origs"]) if binfo else "-"
        atype = f'{ainfo["fam"]}/{ainfo["prec"]}' if ainfo else "-"
        btype = f'{binfo["fam"]}/{binfo["prec"]}' if binfo else "-"
        # 忽略字段跳过清单展示但仍可比对，这里直接标忽略
        if c in ignore:
            continue
        lines.append(f"| {c} | {aorig} | {atype} | {borig} | {btype} |")
    lines.append("")

    # 归一化对照表
    mixed = [c for c in canon_all if c in ta and c in tb
             and to_snake("/".join(ta[c]["origs"])) != c or
             (c in ta and c in tb and any(o != c for o in ta[c]["origs"] + tb[c]["origs"]))]
    if mixed:
        lines.append("## 归一化对照表\n")
        lines.append("| A 原字段 | B 原字段 | 归一名 | 说明 |")
        lines.append("|---|---|---|---|")
        for c in mixed:
            if c in ignore:
                continue
            aorig = "/".join(ta[c]["origs"])
            borig = "/".join(tb[c]["origs"])
            note = "驼峰⇄下划线" if aorig != borig else "同名"
            lines.append(f"| {aorig} | {borig} | {c} | {note} |")
        lines.append("")

    # 差异表
    lines.append("## 差异表\n")
    lines.append("| 字段 | 差异类型 | A 侧 | B 侧 |")
    lines.append("|---|---|---|---|")
    diff_count = 0
    for c in canon_all:
        if c in ignore:
            continue
        ainfo = ta.get(c)
        binfo = tb.get(c)
        if ainfo and not binfo:
            lines.append(f"| {c} | 仅A有 | {ainfo['fam']}/{ainfo['prec']} | - |")
            diff_count += 1
        elif binfo and not ainfo:
            lines.append(f"| {c} | 仅B有 | - | {binfo['fam']}/{binfo['prec']} |")
            diff_count += 1
        else:
            # 都在：比类型族
            if ainfo["fam"] != binfo["fam"]:
                lines.append(f"| {c} | 类型不一致 | {ainfo['fam']}/{ainfo['prec']} | {binfo['fam']}/{binfo['prec']} |")
                diff_count += 1
            elif ainfo["prec"] != binfo["prec"]:
                lines.append(f"| {c} | 同族待查(精确类型不同) | {ainfo['prec']} | {binfo['prec']} |")
                diff_count += 1
    if diff_count == 0:
        lines.append("| - | 无差异 | - | - |")
    lines.append("")

    # 高风险项
    if not no_risk:
        risks = []
        for c in canon_all:
            if c in ignore:
                continue
            for side_name, info in (("A", ta.get(c)), ("B", tb.get(c))):
                if not info:
                    continue
                for r in detect_risk(info["path"], info["val"], info["fam"], info["prec"]):
                    risks.append((c, side_name, r))
        if risks:
            lines.append("## 高风险项\n")
            lines.append("| 字段 | 来源 | 风险 |")
            lines.append("|---|---|---|")
            for c, side, r in risks:
                lines.append(f"| {c} | {side} | {r} |")
            lines.append("")

    lines.append("> 脚本仅做字段名/类型族自动比对；必填口径、空值口径、枚举取值需结合接口文档人工核对。")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
