#!/usr/bin/env python3
"""OSS 构建补丁：给用量组件（Workers / R2 / D1 / KV）补上「更新于 hh:mm」。

背景（2026-10-11）：
  用量组件的小/中尺寸看不出数据是什么时候写的；它的 entry 里也没有时间戳字段
  （用量快照 WidgetUsageData 有 updatedAt，但 provider 没带出来）。这里：
    1) 给 UsageWidgetEntry 加 updatedAt
    2) snapshot 取 App Group 里用量快照的 updatedAt
    3) timeline 自取数成功时用当前时刻，否则回退快照的 updatedAt
    4) 小/中尺寸显示「更新于 hh:mm」（锁屏 accessory 尺寸太小，不加）

只在构建工作区改，源码树保持与上游一致。
幂等：目标片段已存在则跳过；锚点匹配数不为 1 时打 warning 跳过那一处。
"""

from __future__ import annotations

import pathlib
import re
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/UsageWidget.swift"
)

SMALL_TIME = (
    "            if let updatedAt = entry.updatedAt {\n"
    '                Text("更新于 \\(updatedAt, format: .dateTime.hour().minute())")\n'
    "                    .font(.system(size: 8))\n"
    "                    .foregroundStyle(.tertiary)\n"
    "                    .monospacedDigit()\n"
    "                    .lineLimit(1)\n"
    "                    .minimumScaleFactor(0.8)\n"
    "            }"
)

# (kind, 锚点正则, 载荷, 说明)
#   insert_after：把载荷插到锚点整块之后（载荷自带缩进）
#   replace     ：把锚点整块换成载荷
EDITS = [
    (
        "insert_after",
        r"^    var unavailable: Bool = false.*$",
        "    var updatedAt: Date? = nil      // OSS 补丁：数据写入/拉取时刻",
        "UsageWidgetEntry 加 updatedAt",
    ),
    (
        "replace",
        r"^            missingName: nil\n        \)$",
        "            missingName: nil,\n"
        "            updatedAt: WidgetDataStore.loadUsage(accountId: accountId)?.updatedAt\n"
        "        )",
        "snapshot 带出快照时间",
    ),
    (
        "replace",
        r"^            unavailable: unavailable\n        \)$",
        "            unavailable: unavailable,\n"
        "            updatedAt: fresh != nil ? Date() : WidgetDataStore.loadUsage(accountId: accountId)?.updatedAt\n"
        "        )",
        "timeline 带出自取数/快照时间",
    ),
    (
        "insert_after",
        r"^                \.minimumScaleFactor\(0\.7\)$",
        SMALL_TIME,
        "小尺寸时间戳",
    ),
    (
        "replace",
        r'^                Text\("今日 · 本账期"\)\n'
        r"                    \.font\(\.caption2\)\n"
        r"                    \.foregroundStyle\(\.tertiary\)$",
        '                VStack(alignment: .trailing, spacing: 1) {\n'
        '                    Text("今日 · 本账期")\n'
        "                        .font(.caption2)\n"
        "                        .foregroundStyle(.tertiary)\n"
        "                    if let updatedAt = entry.updatedAt {\n"
        '                        Text("更新于 \\(updatedAt, format: .dateTime.hour().minute())")\n'
        "                            .font(.system(size: 8))\n"
        "                            .foregroundStyle(.tertiary)\n"
        "                            .monospacedDigit()\n"
        "                    }\n"
        "                }",
        "中尺寸时间戳",
    ),
]


def main() -> int:
    if not TARGET.exists():
        print(f"::warning::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 0

    src = TARGET.read_text(encoding="utf-8")
    applied: list[str] = []
    skipped: list[str] = []

    for kind, pattern, payload, label in EDITS:
        if payload in src:
            skipped.append(f"{label}(已打过)")
            continue

        rx = re.compile(pattern, re.MULTILINE)
        hits = rx.findall(src)
        if len(hits) != 1:
            print(f"::warning::{label}：锚点匹配到 {len(hits)} 处（应为 1 处），跳过", file=sys.stderr)
            skipped.append(label)
            continue

        if kind == "insert_after":
            src, n = rx.subn(lambda m: m.group(0) + "\n" + payload, src, count=1)
        else:
            src, n = rx.subn(lambda m: payload, src, count=1)
        if n != 1:
            skipped.append(label)
            continue
        applied.append(label)

    TARGET.write_text(src, encoding="utf-8")

    if applied:
        print(f"已应用：用量组件补时间戳 {len(applied)} 处 —— {', '.join(applied)}")
    if skipped:
        print(f"跳过：{', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
