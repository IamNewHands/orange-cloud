#!/usr/bin/env python3
"""OSS 构建补丁：App Group 名改成「按实际授权解析」，修自签安装下小组件没数据。

现象：
  自签安装后小组件能加到主屏、配置页能列出全部域名，但卡片上没有任何数据
  （空态文案「打开 App 同步数据」）。未配置的小组件同样为空 —— 说明是
  Widget Extension 进程读不到共享容器，而不是配置或取数逻辑的问题。

根因（三件事叠在一起）：
  1) 主 App 与小组件靠 App Group 交换快照，组名在
     Shared/WidgetSnapshot.swift 里写死为 group.jiamin.chen.Orange-Cloud；
  2) CI 出的是未签名包（oss-pipeline.yml 里 CODE_SIGNING_ALLOWED=NO），
     IPA 里不带任何 entitlements，签名工具看不到工程里声明的组；
  3) 签名工具（SideStore / SideInstaller 用的同一套 isideload）自己推导组名：
     group.<原bundleID>.<TeamID>，同时把安装后的 bundle id 改写成
     <原bundleID>.<TeamID>（见 isideload 的 sideloader.rs / application.rs），
     最终 profile 里被授权的只有推导出来的那个。
  → 写死的组名永远不在授权列表里：containerURL(forSecurityApplicationGroupIdentifier:)
    返回 nil，UserDefaults(suiteName:) 退化成"各自本地一份"，主 App 写进自己的
    suite、扩展进程读自己的空 suite。

做法（只改构建工作区，不动源码树 —— 与 zone-detail-type-check.py 同样的理由）：
  把写死的组名换成运行时解析：从 embedded.mobileprovision 的 Entitlements 里取
  com.apple.security.application-groups 实际授权的那一个，再用 containerURL 校验；
  都取不到时回退原常量。扩展进程里 Bundle.main 是 .appex，主 App 在其上两级。
  上游作者自己的 Xcode 构建里 profile 授权的就是原常量，解析结果与原行为一致。

幂等：已打过则跳过；目标模式找不到时打 warning 跳过（上游改写过了）。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/Shared/WidgetSnapshot.swift"
)

OLD = '    static let appGroupID = "group.jiamin.chen.Orange-Cloud"\n'
NEW = "    static let appGroupID: String = WidgetAppGroup.resolved\n"

MARK = "nonisolated enum WidgetAppGroup {"

HELPER = '''

// MARK: - App Group 解析（OSS 构建补丁 .github/oss-patches/widget-app-group.py）

/// 自签安装时签名工具会把组名改成 `group.<bundleID>.<TeamID>`，工程里写死的组名
/// 不在 profile 的授权列表里，两个进程各拿一份本地 suite，小组件永远读不到数据。
/// 这里改成运行时解析：优先用 embedded.mobileprovision 里实际被授权的组，取不到
/// 再回退上游常量（上游自己的 Xcode 构建解析结果就是上游常量，行为不变）。
nonisolated enum WidgetAppGroup {

    static let legacy = "group.jiamin.chen.Orange-Cloud"

    static let resolved: String = {
        var candidates = authorizedGroups()
        if let index = candidates.firstIndex(of: legacy) {
            candidates.swapAt(0, index)
        }
        if !candidates.contains(legacy) {
            candidates.append(legacy)
        }
        for candidate in candidates {
            if FileManager.default.containerURL(
                forSecurityApplicationGroupIdentifier: candidate
            ) != nil {
                return candidate
            }
        }
        return legacy
    }()

    /// profile 的 Entitlements 里声明的 App Group（按声明顺序）
    private static func authorizedGroups() -> [String] {
        guard let url = mainAppBundleURL()?.appendingPathComponent("embedded.mobileprovision"),
              let data = try? Data(contentsOf: url),
              let start = data.range(of: Data("<?xml".utf8)),
              let end = data.range(of: Data("</plist>".utf8), in: start.lowerBound..<data.endIndex)
        else { return [] }

        // profile 是 CMS 包着的 XML plist，取出 plist 段再解析
        guard let raw = try? PropertyListSerialization.propertyList(
                  from: data[start.lowerBound..<end.upperBound], options: [], format: nil
              ),
              let plist = raw as? [String: Any],
              let entitlements = plist["Entitlements"] as? [String: Any],
              let groups = entitlements["com.apple.security.application-groups"] as? [String]
        else { return [] }

        return groups.filter { !$0.isEmpty }
    }

    /// 扩展进程里 Bundle.main 是 .appex，主 App 在其上两级（App.app/PlugIns/X.appex）
    private static func mainAppBundleURL() -> URL? {
        let bundle = Bundle.main.bundleURL
        if bundle.pathExtension == "appex" {
            return bundle.deletingLastPathComponent().deletingLastPathComponent()
        }
        return bundle
    }
}
'''


def main() -> int:
    if not TARGET.exists():
        print(f"::warning::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 0

    src = TARGET.read_text(encoding="utf-8")

    if MARK in src:
        print("已打过补丁，跳过（App Group 运行时解析）")
        return 0

    if OLD not in src:
        print(
            "::warning::找不到写死的 App Group 常量，跳过本补丁。"
            "上游可能改写了 Shared/WidgetSnapshot.swift —— 自签安装下小组件会重新变成没数据，"
            "请人工核对 .github/oss-patches/widget-app-group.py 的 OLD 模式。",
            file=sys.stderr,
        )
        return 0

    if src.count(OLD) != 1:
        print(f"::warning::写死的 App Group 常量匹配到 {src.count(OLD)} 处（应为 1 处），跳过", file=sys.stderr)
        return 0

    src = src.replace(OLD, NEW, 1)
    src = src.rstrip("\n") + "\n" + HELPER
    TARGET.write_text(src, encoding="utf-8")

    print("已应用：App Group 改为从 embedded.mobileprovision 解析实际授权值")
    print(f"  {TARGET}: {OLD.strip()}  ->  {NEW.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
