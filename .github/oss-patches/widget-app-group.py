#!/usr/bin/env python3
"""OSS 构建补丁：App Group / 共享钥匙串组都改成「按实际授权解析」。

现象（2026-10-11）：
  自签安装后小组件能加、配置页能列域名，但卡片上没有任何数据；未配置的组件同样为空
  ⇒ Widget Extension 进程读不到共享容器。

根因（三件事叠在一起）：
  1) 主 App 与小组件靠 App Group 交换快照，组名在 Shared/WidgetSnapshot.swift 里写死为
     group.jiamin.chen.Orange-Cloud，共享钥匙串组写死为上游作者的 team
     (6G78MMY657.jiamin.chen.orange-cloud.shared)；
  2) CI 出的是未签名包（CODE_SIGNING_ALLOWED=NO），IPA 里不带任何 entitlements；
  3) 签名工具自己决定授权的组：App Group 由工具推导，钥匙串组来自描述文件
     （用户那张 profile 是 `7S3MGZK59N.*` 通配）。写死的那两个都不在授权列表里。

做法（只改构建工作区，不动源码树）：
  把 WidgetSnapshot.appGroupID 换成运行时解析：优先用 embedded.mobileprovision 里
  实际被授权的 App Group，再用 containerURL 校验，取不到回退原常量；同时提供
  sharedKeychainGroup —— 用 profile 里的 team 前缀拼出共享钥匙串组（通配授权下可用），
  解析不到 team 时回退上游常量。上游作者自己的 Xcode 构建解析结果与原来一致。

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

// MARK: - App Group / 钥匙串组解析（OSS 构建补丁 .github/oss-patches/widget-app-group.py）

/// 自签安装时签名工具授权的组名与工程里写死的不同（App Group 由工具推导、
/// 钥匙串组来自描述文件），写死的那个取不到共享容器。这里改成运行时解析：
/// App Group 优先用 embedded.mobileprovision 里实际被授权的那个，钥匙串组用
/// profile 的 team 前缀拼（profile 的 keychain-access-groups 是 `TEAM.*` 通配）。
/// 都取不到时回退上游常量 —— 上游自己的 Xcode 构建解析结果就是上游常量，行为不变。
nonisolated enum WidgetAppGroup {

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

    /// 共享钥匙串组（主 App / 扩展 / 手表共用同一个名字）
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


def main() -> int:
    if not TARGET.exists():
        print(f"::warning::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 0

    src = TARGET.read_text(encoding="utf-8")

    if MARK in src:
        print("已打过补丁，跳过（App Group / 钥匙串组运行时解析）")
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

    print("已应用：App Group 与共享钥匙串组都改为从 embedded.mobileprovision 解析")
    print(f"  {TARGET}: {OLD.strip()}  ->  {NEW.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
