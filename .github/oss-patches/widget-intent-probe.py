#!/usr/bin/env python3
"""OSS 调试补丁（临时）：加两个诊断小组件，把"App Intent 配置"这条路二分掉。

背景（2026-10-11）：
  自签安装后 4 个小组件全部停在 WidgetKit 的占位（红acted）态、控制中心按钮空白无反应，
  但**实时活动（Live Activity）能正常渲染** —— 说明扩展进程是活的、渲染没问题，
  坏的只是所有依赖 App Intent 的入口（4 个组件都是 AppIntentConfiguration，
  控制中心按钮的 action 也是 AppIntent）。主 App 侧的 App Intents 正常（配置页能列出域名）。

  于是加两个只做诊断、不联网的小组件：
    1) OCStaticProbe  —— StaticConfiguration，完全不用 App Intent
    2) OCIntentProbe  —— AppIntentConfiguration，但 intent **没有任何参数**
  读法：
    两个都出内容   → 带参数的配置 intent 有问题（现有 4 个组件都属于这类）
    只有静态出内容 → 只要走 AppIntentConfiguration 就坏
    两个都不出     → 扩展产不出 timeline（更底层的问题）

  诊断完删掉本补丁（以及 workflow 里那一行）。

幂等：已打过则跳过；锚点找不到时打 warning 跳过。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/WidgetDaybreak.swift"
)
BUNDLE = pathlib.Path(
    "apps/ios/Orange Cloud/OrangeCloudWidgets/OrangeCloudWidgetsBundle.swift"
)

MARK = "struct OCStaticProbeWidget: Widget {"

PROBE = r'''

// MARK: - 临时诊断组件（OSS 调试补丁 .github/oss-patches/widget-intent-probe.py）

/// 诊断用 entry：只带一行文本，不联网、不读 App Group 以外的东西。
nonisolated struct OCProbeEntry: TimelineEntry {
    let date: Date
    let text: String
}

nonisolated struct OCProbeView: View {

    let entry: OCProbeEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("诊断")
                .font(.caption2.bold())
            Text(entry.text)
                .font(.system(size: 9, design: .monospaced))
                .multilineTextAlignment(.leading)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(8)
    }
}

/// 1) 静态配置：完全没有 App Intent
nonisolated struct OCStaticProbeProvider: TimelineProvider {

    func placeholder(in context: Context) -> OCProbeEntry {
        OCProbeEntry(date: .now, text: "静态诊断占位")
    }

    func getSnapshot(in context: Context, completion: @escaping (OCProbeEntry) -> Void) {
        completion(current())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<OCProbeEntry>) -> Void) {
        completion(Timeline(entries: [current()], policy: .after(Date().addingTimeInterval(600))))
    }

    private func current() -> OCProbeEntry {
        OCProbeEntry(date: .now, text: WidgetGroupProbe.line)
    }
}

struct OCStaticProbeWidget: Widget {

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "OCStaticProbe", provider: OCStaticProbeProvider()) { entry in
            OCProbeView(entry: entry)
        }
        .configurationDisplayName("诊断 · 静态")
        .description("不依赖 App Intent 的诊断组件")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

/// 2) App Intent 配置，但 intent 不带任何参数
nonisolated struct OCProbeIntent: WidgetConfigurationIntent {

    static let title: LocalizedStringResource = "诊断（无参数）"
    static let description = IntentDescription("没有任何参数的诊断配置")
}

nonisolated struct OCIntentProbeProvider: AppIntentTimelineProvider {

    func placeholder(in context: Context) -> OCProbeEntry {
        OCProbeEntry(date: .now, text: "Intent 诊断占位")
    }

    func snapshot(for configuration: OCProbeIntent, in context: Context) async -> OCProbeEntry {
        current()
    }

    func timeline(for configuration: OCProbeIntent, in context: Context) async -> Timeline<OCProbeEntry> {
        Timeline(entries: [current()], policy: .after(Date().addingTimeInterval(600)))
    }

    private func current() -> OCProbeEntry {
        OCProbeEntry(date: .now, text: WidgetGroupProbe.line)
    }
}

struct OCIntentProbeWidget: Widget {

    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "OCIntentProbe", intent: OCProbeIntent.self,
                               provider: OCIntentProbeProvider()) { entry in
            OCProbeView(entry: entry)
        }
        .configurationDisplayName("诊断 · 无参数 Intent")
        .description("用 App Intent 配置、但不带任何参数")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
'''

BUNDLE_OLD = """        ZoneStatusWidget()
"""
BUNDLE_NEW = """        ZoneStatusWidget()
        // OSS 调试补丁：两个诊断组件（.github/oss-patches/widget-intent-probe.py）
        OCStaticProbeWidget()
        OCIntentProbeWidget()
"""


def main() -> int:
    for path in (TARGET, BUNDLE):
        if not path.exists():
            print(f"::warning::调试补丁目标不存在：{path}", file=sys.stderr)
            return 0

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("已打过诊断组件补丁，跳过")
        return 0

    src = src.rstrip("\n") + "\n" + PROBE
    TARGET.write_text(src, encoding="utf-8")

    bundle = BUNDLE.read_text(encoding="utf-8")
    if "OCStaticProbeWidget()" not in bundle:
        if BUNDLE_OLD not in bundle:
            print("::warning::WidgetBundle 结构变了，诊断组件没注册进去", file=sys.stderr)
            return 0
        bundle = bundle.replace(BUNDLE_OLD, BUNDLE_NEW, 1)
        BUNDLE.write_text(bundle, encoding="utf-8")

    print("已应用：新增两个诊断组件（诊断 · 静态 / 诊断 · 无参数 Intent）并注册进 WidgetBundle")
    print(f"  {TARGET}")
    print(f"  {BUNDLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
