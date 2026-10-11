#!/usr/bin/env python3
"""OSS 构建补丁：把 File Provider 与推送扩展里写死的 App Group / 钥匙串组改成运行时解析。

背景（2026-10-11）：
  小组件那条链已经修好（Shared/WidgetSnapshot.swift 里的 WidgetAppGroup 从
  embedded.mobileprovision 解析实际授权的组）。但 File Provider（Files 里的 Orange Cloud）
  与 notification 扩展不编译 Shared/，各自写死了 group.jiamin.chen.Orange-Cloud 与
  上游 team 的钥匙串组 6G78MMY657.jiamin.chen.orange-cloud.shared —— 自签安装下这两个
  都没被授权，两个扩展同样取不到共享容器 / 读不到主 App 的 token。

做法：
  工程用的是 Xcode 16+ 的同步文件夹（fileSystemSynchronizedGroups），往
  "Orange Cloud File/" 与 "notification/" 里各放一个自带的解析文件 OCAppGroup.swift，
  这两个 target 会自动编译它；再把三处常量换成 OCAppGroup.resolved。
  主 App 的 Core/Auth/RefreshGate.swift 直接引用 Shared 里的 WidgetSnapshot.appGroupID。

只在构建工作区改，源码树保持与上游一致。幂等：已存在则跳过。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path("apps/ios/Orange Cloud")

HELPER_FILES = [
    ROOT / "Orange Cloud File" / "OCAppGroup.swift",
    ROOT / "notification" / "OCAppGroup.swift",
]

HELPER = '''//
//  OCAppGroup.swift
//  OSS 构建补丁生成（.github/oss-patches/widget-extension-appgroup.py）
//
//  本扩展不编译 Shared/，所以自带一份 App Group / 钥匙串组解析：自签安装时签名工具
//  授权的组名与工程里写死的不同，写死的那个取不到共享容器。这里优先用
//  embedded.mobileprovision 里实际授权的 App Group，钥匙串组用 profile 的 team 前缀拼
//  （profile 的 keychain-access-groups 是 `TEAM.*` 通配）；都取不到时回退上游常量
//  （上游自己的 Xcode 构建解析结果就是上游常量，行为不变）。
//

import Foundation

nonisolated enum OCAppGroup {

    static let legacy = "group.jiamin.chen.Orange-Cloud"
    static let legacyKeychainGroup = "6G78MMY657.jiamin.chen.orange-cloud.shared"

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

    /// 共享钥匙串组（与主 App 用同一个名字）
    static let sharedKeychainGroup: String = {
        if let team = teamIdentifier(), !team.isEmpty {
            return "\\(team).jiamin.chen.orange-cloud.shared"
        }
        return legacyKeychainGroup
    }()

    /// profile 的 Entitlements 里声明的 App Group（按声明顺序）
    private static func authorizedGroups() -> [String] {
        guard let entitlements = profileEntitlements(),
              let groups = entitlements["com.apple.security.application-groups"] as? [String]
        else { return [] }
        return groups.filter { !$0.isEmpty }
    }

    /// team 前缀：优先 com.apple.developer.team-identifier，其次 application-identifier 前缀
    private static func teamIdentifier() -> String? {
        guard let entitlements = profileEntitlements() else { return nil }
        if let team = entitlements["com.apple.developer.team-identifier"] as? String,
           !team.isEmpty {
            return team
        }
        if let appID = entitlements["application-identifier"] as? String,
           let prefix = appID.split(separator: ".").first, !prefix.isEmpty {
            return String(prefix)
        }
        return nil
    }

    /// profile 是 CMS 包着的 XML plist，取出 plist 段再解析出 Entitlements
    private static func profileEntitlements() -> [String: Any]? {
        guard let url = mainAppBundleURL()?.appendingPathComponent("embedded.mobileprovision"),
              let data = try? Data(contentsOf: url),
              let start = data.range(of: Data("<?xml".utf8)),
              let end = data.range(of: Data("</plist>".utf8), in: start.lowerBound..<data.endIndex)
        else { return nil }

        guard let raw = try? PropertyListSerialization.propertyList(
                  from: data[start.lowerBound..<end.upperBound], options: [], format: nil
              ),
              let plist = raw as? [String: Any],
              let entitlements = plist["Entitlements"] as? [String: Any]
        else { return nil }

        return entitlements
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

OLD_GROUP = '"group.jiamin.chen.Orange-Cloud"'

# (文件, 旧常量整行, 新常量整行, 说明)
REPLACEMENTS = [
    (
        ROOT / "Orange Cloud File" / "RefreshGate.swift",
        f'    private static let appGroupID = {OLD_GROUP}\n',
        "    private static let appGroupID = OCAppGroup.resolved\n",
        "File Provider · RefreshGate",
    ),
    (
        ROOT / "Orange Cloud File" / "FileProviderIdentifierStore.swift",
        f'    private static let appGroup = {OLD_GROUP}\n',
        "    private static let appGroup = OCAppGroup.resolved\n",
        "File Provider · IdentifierStore",
    ),
    (
        ROOT / "notification" / "PushExtensionStore.swift",
        f'    static let appGroupID = {OLD_GROUP}\n',
        "    static let appGroupID = OCAppGroup.resolved\n",
        "推送扩展 · PushExtensionStore",
    ),
    (
        ROOT / "Orange Cloud" / "Core" / "Auth" / "RefreshGate.swift",
        f'    private static let appGroupID = {OLD_GROUP}\n',
        "    private static let appGroupID = WidgetSnapshot.appGroupID\n",
        "主 App · RefreshGate",
    ),
]


def main() -> int:
    written: list[str] = []
    replaced: list[str] = []
    skipped: list[str] = []

    for path in HELPER_FILES:
        if not path.parent.exists():
            print(f"::warning::目录不存在：{path.parent}", file=sys.stderr)
            skipped.append(str(path))
            continue
        if path.exists():
            skipped.append(f"{path.name}@{path.parent.name}(已存在)")
            continue
        path.write_text(HELPER, encoding="utf-8")
        written.append(f"{path.parent.name}/OCAppGroup.swift")

    for path, old, new, label in REPLACEMENTS:
        if not path.exists():
            print(f"::warning::补丁目标不存在：{path}", file=sys.stderr)
            skipped.append(label)
            continue
        src = path.read_text(encoding="utf-8")
        if new.strip() in src:
            skipped.append(f"{label}(已打过)")
            continue
        if src.count(old) != 1:
            print(f"::warning::{label}：常量匹配到 {src.count(old)} 处（应为 1 处），跳过", file=sys.stderr)
            skipped.append(label)
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        replaced.append(label)

    if written:
        print(f"已生成解析文件：{', '.join(written)}")
    if replaced:
        print(f"已改常量：{', '.join(replaced)}")
    if skipped:
        print(f"跳过：{', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
