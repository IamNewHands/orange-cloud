#!/usr/bin/env python3
"""OSS 调试补丁（临时）：把 Widget Extension 进程看到的事实打印在小组件空态上。

为什么需要它：
  自签安装后小组件一直没数据，而设备端看不到任何日志。唯一能确定"扩展进程到底
  拿到了什么"的办法，就是在空态文案下面直接打印几个事实：

    G:<组名>       运行时解析出来的 App Group
    c0/c1          containerURL(forSecurityApplicationGroupIdentifier:) 是否成功
    z<n>           App Group 里读到的 zone 快照条数
    a<n>           App Group 里的账号目录条数
    s0/s1          App Group 里有没有 currentSessionId（决定能不能取 token）
    k<n>           不带 access group 能读到的 OAuth token 条数
                   （>0 = 扩展与主 App 共用钥匙串组，可以走钥匙串兜底）
    b:<bundle id>  扩展进程的 bundle id（看签名工具有没有改写 bundle id）

诊断完删掉本补丁（以及 workflow 里的那一行）。

幂等：已打过则跳过；目标模式找不到时打 warning 跳过。
"""

from __future__ import annotations

import pathlib
import sys

SNAPSHOT = pathlib.Path("apps/ios/Orange Cloud/Shared/WidgetSnapshot.swift")
HINT = pathlib.Path("apps/ios/Orange Cloud/OrangeCloudWidgets/WidgetDaybreak.swift")

MARK = "nonisolated enum WidgetGroupProbe {"

IMPORT_OLD = "import Foundation\n"
IMPORT_NEW = "import Foundation\nimport Security\n"

PROBE = '''

// MARK: - 临时诊断（OSS 调试补丁 .github/oss-patches/widget-app-group-debug.py）

/// 小组件空态上直接打印扩展进程看到的事实，用来定位共享容器 / 钥匙串到底通不通。
/// 诊断完请删掉本补丁。
nonisolated enum WidgetGroupProbe {

    static var line: String {
        let group = WidgetSnapshot.appGroupID
        let short = group.hasPrefix("group.") ? String(group.dropFirst(6)) : group
        let defaults = UserDefaults(suiteName: group)
        let container = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: group
        ) != nil
        let zones = WidgetDataStore.loadZones().count
        let accounts = WidgetDataStore.loadAccounts().count
        let session = defaults?.string(forKey: "currentSessionId") != nil
        let bundle = Bundle.main.bundleIdentifier ?? "-"
        return "G:\\(short) c\\(container ? 1 : 0)\\n"
            + "z\\(zones) a\\(accounts) s\\(session ? 1 : 0) k\\(keychainItemCount())\\n"
            + "b:\\(bundle)"
    }

    /// 不带 access group 能读到的 OAuth token 条数（>0 说明扩展与主 App 共用钥匙串组）
    private static func keychainItemCount() -> Int {
        let query: [String: Any] = [
            kSecClass as String:              kSecClassGenericPassword,
            kSecAttrService as String:        "app.orangecloud.oauth",
            kSecAttrSynchronizable as String: kSecAttrSynchronizableAny,
            kSecReturnAttributes as String:   true,
            kSecMatchLimit as String:         kSecMatchLimitAll,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let items = result as? [[String: Any]] else { return 0 }
        return items.count
    }
}
'''

HINT_OLD = """            Text(text)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
"""

HINT_NEW = """            Text(text)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            // OSS 调试补丁：打印扩展进程看到的 App Group / 快照 / 钥匙串事实
            Text(WidgetGroupProbe.line)
                .font(.system(size: 7, design: .monospaced))
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
"""


def main() -> int:
    for path in (SNAPSHOT, HINT):
        if not path.exists():
            print(f"::warning::调试补丁目标不存在：{path}", file=sys.stderr)
            return 0

    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if MARK in snapshot:
        print("已打过调试补丁，跳过")
        return 0

    if IMPORT_OLD not in snapshot:
        print("::warning::WidgetSnapshot.swift 里找不到 import Foundation，跳过调试补丁", file=sys.stderr)
        return 0
    snapshot = snapshot.replace(IMPORT_OLD, IMPORT_NEW, 1)
    snapshot = snapshot.rstrip("\n") + "\n" + PROBE
    SNAPSHOT.write_text(snapshot, encoding="utf-8")

    hint = HINT.read_text(encoding="utf-8")
    if HINT_OLD not in hint:
        print("::warning::WidgetDaybreak.swift 的 WidgetEmptyHint 结构变了，跳过空态打印", file=sys.stderr)
        return 0
    hint = hint.replace(HINT_OLD, HINT_NEW, 1)
    HINT.write_text(hint, encoding="utf-8")

    print("已应用：小组件空态打印 App Group / 快照 / 钥匙串诊断行")
    print(f"  {SNAPSHOT}（import Security + WidgetGroupProbe）")
    print(f"  {HINT}（WidgetEmptyHint 追加一行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
