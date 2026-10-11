#!/usr/bin/env python3
"""OSS 构建补丁（临时）：把 bundle id 对齐到共享描述文件的 AppID。

背景（2026-10-11）：
  实测结论：StaticConfiguration 组件能出内容，AppIntentConfiguration 组件（含无参数 intent）
  只出占位 —— 配置这条路整条断。当前安装的身份是矛盾的：
    描述文件 / 签名 entitlements 的 application-identifier = 7S3MGZK59N.com.cwd43.gu29
    但 app 的 CFBundleIdentifier = jiamin.chen.orange-cloud（LCSign 不改写 bundle id）
  App Intents 的注册/解析很可能依赖身份一致，这里把工程里的 bundle id 整体换成
  描述文件的 AppID，让两者对上（扩展会跟着变成 com.cwd43.gu29.<原后缀>）。

  这是一次对照实验：如果换成一致的 bundle id 后 AppIntentConfiguration 组件能出数据，
  说明问题在身份不一致（那就要固定用与证书匹配的 bundle id）；否则继续走静态配置方案。

幂等：已经替换过就跳过。
"""

from __future__ import annotations

import pathlib
import sys

PBXPROJ = pathlib.Path("apps/ios/Orange Cloud/Orange Cloud.xcodeproj/project.pbxproj")

OLD = "jiamin.chen.orange-cloud"
NEW = "com.cwd43.gu29"


def main() -> int:
    if not PBXPROJ.exists():
        print(f"::warning::找不到工程文件：{PBXPROJ}", file=sys.stderr)
        return 0

    src = PBXPROJ.read_text(encoding="utf-8")

    if OLD not in src:
        print(f"工程里已无 {OLD}（可能已替换过），跳过")
        return 0

    count = src.count(OLD)
    src = src.replace(OLD, NEW)
    PBXPROJ.write_text(src, encoding="utf-8")
    print(f"已应用：bundle id {OLD} -> {NEW}（{count} 处）")
    print(f"  {PBXPROJ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
