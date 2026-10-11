#!/usr/bin/env python3
"""OSS 构建补丁：给小组件的小/中尺寸补上「更新于 hh:mm」。

背景（2026-10-11）：
  组件数据来自「上一次刷新时刻」（自取数是组件刷新那刻的滚动 24h，回退值是 App 上次刷新
  写入的快照），iOS 的刷新预算还会让它更滞后；但只有请求地形的大尺寸显示了
  「更新于 hh:mm」，小/中尺寸看不出来，观感上就是"和 App 里对不上"。这里补到：
    - 域名指标（小、中）
    - 请求地形（中）
    - 账号总览（小；其中尺寸本来就有 snapshot.updatedAt）

  锚点用「Text + 它自己的修饰符」整块匹配，插到整块之后 —— 不能只匹配 Text 那一行，
  否则新插入的行会插到 Text 与它的修饰符之间，把原 label 的样式挪到时间戳上。

只在构建工作区改，源码树保持与上游一致。
幂等：按「锚点整块 + 插入块」是否存在判断；锚点匹配数不为 1 时打 warning 跳过那一处。
"""

from __future__ import annotations

import pathlib
import re
import sys

ZONE_WIDGETS = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/ZoneWidgets.swift"
)
ZONE_STATUS = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/ZoneStatusWidget.swift"
)

MARK = "// OSS 补丁 · 更新于时间戳"


def block(indent: str, source: str) -> str:
    pad = indent + "    "
    return (
        f"{indent}{MARK}（.github/oss-patches/widget-updated-at.py）\n"
        f'{indent}Text("更新于 \\({source}, format: .dateTime.hour().minute())")\n'
        f"{pad}.font(.system(size: 8))\n"
        f"{pad}.foregroundStyle(.tertiary)\n"
        f"{pad}.monospacedDigit()\n"
        f"{pad}.lineLimit(1)\n"
        f"{pad}.minimumScaleFactor(0.8)"
    )


# (文件, 锚点正则(整块), 缩进, 时间来源, 说明)
EDITS = [
    (
        ZONE_WIDGETS,
        r"^            Text\(entry\.metric\.label\)\n"
        r"                \.font\(\.caption2\)\n"
        r"                \.foregroundStyle\(\.secondary\)\n"
        r"                \.lineLimit\(1\)$",
        "            ",
        "zone.updatedAt",
        "域名指标 · 小",
    ),
    (
        ZONE_WIDGETS,
        r"^                    Text\(entry\.metric\.label\)\n"
        r"                        \.font\(\.caption2\)\n"
        r"                        \.foregroundStyle\(\.secondary\)$",
        "                    ",
        "zone.updatedAt",
        "域名指标 · 中",
    ),
    (
        ZONE_WIDGETS,
        r'^                    Text\("总请求 · 过去 24 小时"\)\n'
        r"                        \.font\(\.caption2\)\n"
        r"                        \.foregroundStyle\(\.secondary\)$",
        "                    ",
        "zone.updatedAt",
        "请求地形 · 中",
    ),
    (
        ZONE_STATUS,
        r"^            HorizonScene\(date: entry\.date\)$",
        "            ",
        "snapshot.updatedAt",
        "账号总览 · 小",
    ),
]


def main() -> int:
    applied: list[str] = []
    skipped: list[str] = []

    for path, pattern, indent, source, label in EDITS:
        if not path.exists():
            print(f"::warning::补丁目标不存在：{path}", file=sys.stderr)
            skipped.append(label)
            continue

        src = path.read_text(encoding="utf-8")
        rx = re.compile(pattern, re.MULTILINE)
        hits = rx.findall(src)
        insert = block(indent, source)

        if len(hits) == 1 and (hits[0] + "\n" + insert) in src:
            skipped.append(f"{label}(已打过)")
            continue
        if len(hits) != 1:
            print(
                f"::warning::{label}：锚点匹配到 {len(hits)} 处（应为 1 处），跳过这一处",
                file=sys.stderr,
            )
            skipped.append(label)
            continue

        src, n = rx.subn(lambda m: m.group(0) + "\n" + insert, src, count=1)
        if n != 1:
            skipped.append(label)
            continue
        path.write_text(src, encoding="utf-8")
        applied.append(label)

    if applied:
        print(f"已应用：给 {len(applied)} 处小/中尺寸补上「更新于 hh:mm」—— {', '.join(applied)}")
    if skipped:
        print(f"跳过：{', '.join(skipped)}")
    if not applied and not skipped:
        print("没有可应用的改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
