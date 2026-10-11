#!/usr/bin/env python3
"""OSS 构建补丁：共享钥匙串组改成按描述文件的 team 运行时推导。

背景（2026-10-11）：
  上游把共享钥匙串组写死成作者自己的 team：6G78MMY657.jiamin.chen.orange-cloud.shared。
  自签安装用的是另一张证书（team 7S3MGZK59N），这个组不在授权列表里 —— 写进去会失败并
  回退到各自 bundle id 的默认组，于是主 App / File Provider / 手表之间互相读不到 token
  （Files 里的 Orange Cloud 因此不可用）。

做法：
  Shared 里的 WidgetAppGroup 与两个扩展自带的 OCAppGroup 已经提供 sharedKeychainGroup
  （用 profile 的 team 前缀拼；profile 的 keychain-access-groups 是 `TEAM.*` 通配，
  授权上没问题；解析不到 team 时回退上游常量）。这里把三处写死的常量换成它：
    - 主 App TokenStore.sharedAccessGroup
    - File Provider R2FileProviderClient.keychainAccessGroup
    - 手表 WatchTokenStore.accessGroup

  必须在 widget-app-group.py / widget-extension-appgroup.py 之后运行（那两个负责生成解析器）。
  写不进去时各处仍有「去掉 access group 再写一次」的兜底，不会把 token 弄丢。

幂等：已替换则跳过；锚点匹配数不为 1 时打 warning 跳过那一处。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path("apps/ios/Orange Cloud")

OLD = '    static let sharedAccessGroup = "6G78MMY657.jiamin.chen.orange-cloud.shared"\n'
OLD_FILE = '    private static let keychainAccessGroup = "6G78MMY657.jiamin.chen.orange-cloud.shared"\n'
OLD_WATCH = '    private static let accessGroup = "6G78MMY657.jiamin.chen.orange-cloud.shared"\n'

# (文件, 旧整行, 新整行, 说明)
EDITS = [
    (
        ROOT / "Orange Cloud" / "Core" / "Auth" / "TokenStore.swift",
        OLD,
        "    /// OSS 补丁：按描述文件的 team 运行时推导（自签安装下上游写死的 team 不匹配）\n"
        "    static var sharedAccessGroup: String { WidgetAppGroup.sharedKeychainGroup }\n",
        "主 App · TokenStore",
    ),
    (
        ROOT / "Orange Cloud File" / "R2FileProviderClient.swift",
        OLD_FILE,
        "    /// OSS 补丁：与主 App 同一个运行时推导的共享组\n"
        "    private static var keychainAccessGroup: String { OCAppGroup.sharedKeychainGroup }\n",
        "File Provider · R2FileProviderClient",
    ),
    (
        ROOT / "Orange Cloud Watch Watch App" / "WatchTokenStore.swift",
        OLD_WATCH,
        "    /// OSS 补丁：与 iPhone 侧同一个运行时推导的共享组\n"
        "    private static var accessGroup: String { WidgetAppGroup.sharedKeychainGroup }\n",
        "手表 · WatchTokenStore",
    ),
]


def main() -> int:
    replaced: list[str] = []
    skipped: list[str] = []

    for path, old, new, label in EDITS:
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

    if replaced:
        print(f"已应用：共享钥匙串组改为运行时推导 {len(replaced)} 处 —— {', '.join(replaced)}")
    if skipped:
        print(f"跳过：{', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
