#!/usr/bin/env python3
"""OSS 构建补丁（临时）：加一个走静态配置的域名组件，保证能出数据。

背景（2026-10-11）：
  实测：StaticConfiguration 组件能出内容，AppIntentConfiguration 组件（含无参数 intent）
  只出占位。所以在 App Intent 那条路查清/修好之前，先用静态配置给一个能用的域名组件：
  复用现有 ZoneStatWidgetView，域名取「当前账号的第一个域名」，指标固定请求数。

  放在 ZoneWidgets.swift 里是因为 resolveZone / sampleZone / latestZone 都是该文件的
  private 成员，同文件才能复用。

幂等：已打过则跳过。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/ZoneWidgets.swift"
)
BUNDLE = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/OrangeCloudWidgetsBundle.swift"
)

MARK = "struct OCStaticZoneWidget: Widget {"

CODE = r'''

// MARK: - 临时：静态配置的域名组件（OSS 调试补丁 .github/oss-patches/widget-static-zone.py）

/// 与 ZoneStatWidget 共用视图，但走 StaticConfiguration（不经过 App Intent）。
/// 域名取当前账号的第一个域名，指标固定请求数。
nonisolated struct OCStaticZoneProvider: TimelineProvider {

    func placeholder(in context: Context) -> ZoneWidgetEntry {
        ZoneWidgetEntry(date: .now, zone: sampleZone, metric: .requests)
    }

    func getSnapshot(in context: Context, completion: @escaping (ZoneWidgetEntry) -> Void) {
        completion(ZoneWidgetEntry(date: .now, zone: currentZone(), metric: .requests))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<ZoneWidgetEntry>) -> Void) {
        let entry = ZoneWidgetEntry(date: .now, zone: currentZone(), metric: .requests)
        let next = Calendar.current.date(byAdding: .minute, value: 30, to: .now) ?? .now
        completion(Timeline(entries: [entry], policy: .after(next)))
    }

    /// 当前账号的第一个域名（账号总览之外只取该账号，避免跨账号串）
    private func currentZone() -> WidgetZoneMetrics? {
        WidgetDataStore.loadZones(accountId: WidgetSnapshot.currentAccountId()).first
    }
}

struct OCStaticZoneWidget: Widget {

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "OCStaticZone", provider: OCStaticZoneProvider()) { entry in
            ZoneStatWidgetView(entry: entry)
                .daybreakContainer(date: entry.date)
        }
        .configurationDisplayName("域名指标 · 静态")
        .description("不依赖 App Intent 的域名指标（当前账号的第一个域名）")
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}
'''

BUNDLE_OLD = """        ZoneStatusWidget()
"""
BUNDLE_NEW = """        ZoneStatusWidget()
        OCStaticZoneWidget()
"""


def main() -> int:
    for path in (TARGET, BUNDLE):
        if not path.exists():
            print(f"::warning::补丁目标不存在：{path}", file=sys.stderr)
            return 0

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("已打过静态域名组件补丁，跳过")
        return 0

    src = src.rstrip("\n") + "\n" + CODE
    TARGET.write_text(src, encoding="utf-8")

    bundle = BUNDLE.read_text(encoding="utf-8")
    if "OCStaticZoneWidget()" not in bundle:
        if BUNDLE_OLD not in bundle:
            print("::warning::WidgetBundle 里找不到 OCIntentProbeWidget()，静态域名组件没注册", file=sys.stderr)
            return 0
        bundle = bundle.replace(BUNDLE_OLD, BUNDLE_NEW, 1)
        BUNDLE.write_text(bundle, encoding="utf-8")

    print("已应用：新增静态配置的域名组件（域名指标 · 静态）并注册进 WidgetBundle")
    print(f"  {TARGET}")
    print(f"  {BUNDLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
