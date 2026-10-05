#!/usr/bin/env python3
"""OSS 构建补丁：绕开上游代码在本仓库 runner 上触发的 Swift 类型检查超时。

为什么不在源码里直接改：
  本仓库是 fork，main 由 CI 定时 merge 上游。改动上游文件会在每次上游变更时
  产生冲突，打断自动同步。所以补丁只在构建时应用，源码树保持与上游一致。

幂等：
  - 目标文件不存在 -> 报错退出（上游挪了路径，需要人工核对）。
  - 已经是打过补丁的形态 -> 跳过。
  - 原模式不存在 -> 打印说明后跳过（上游已自行修复或改写，构建会告诉我们）。

背景（run 37251582830，2026-10-05）：
  apps/ios/.../Views/Zones/ZoneDetailView.swift:692:23: error: the compiler is
  unable to type-check this expression in reasonable time
  「操作失败」alert 里内联的 Binding.init(get:set:) 让整个 body 表达式超出
  Swift 类型检查时限。把它提到属性里即可，行为不变。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/Orange Cloud/Views/Zones/ZoneDetailView.swift"
)

OLD = """        .alert("操作失败", isPresented: .init(
            get: { actionsViewModel.error != nil },
            set: { if !$0 { actionsViewModel.error = nil } }
        )) {
            apiErrorDocButton(for: actionsViewModel.error)
            Button("好", role: .cancel) {}
        } message: {
            Text(actionsViewModel.error ?? "")
        }
    }
"""

NEW = """        .alert("操作失败", isPresented: actionErrorPresented) {
            apiErrorDocButton(for: actionsViewModel.error)
            Button("好", role: .cancel) {}
        } message: {
            Text(actionsViewModel.error ?? "")
        }
    }

    /// OSS 构建补丁（.github/oss-patches/ios-type-check.py）：
    /// 内联 Binding 会让整个 body 表达式超出 Swift 类型检查时限，提到属性里。
    private var actionErrorPresented: Binding<Bool> {
        Binding(
            get: { actionsViewModel.error != nil },
            set: { if !$0 { actionsViewModel.error = nil } }
        )
    }
"""

ALREADY = ".alert(\"操作失败\", isPresented: actionErrorPresented)"


def main() -> int:
    if not TARGET.exists():
        print(f"::error::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 1

    src = TARGET.read_text(encoding="utf-8")

    if ALREADY in src:
        print(f"已打过补丁，跳过：{TARGET}")
        return 0

    if OLD not in src:
        print(
            f"::notice::目标模式未找到（上游可能已修复），跳过补丁：{TARGET}"
        )
        return 0

    TARGET.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"已应用类型检查补丁：{TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
