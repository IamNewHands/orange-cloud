#!/usr/bin/env python3
"""OSS 构建补丁：压低 ZoneDetailView 巨型 body 的类型检查开销。

为什么不在源码里改：
  本仓库是 fork，main 由 CI 定时 merge 上游。改动上游文件会在每次上游变更时
  产生冲突，打断自动同步。所以补丁只在构建时应用，源码树保持与上游一致。

背景（runs 37251582830 / 37253219078 / 37254149440 / 37254854501）：
  apps/ios/.../Views/Zones/ZoneDetailView.swift 报
    error: the compiler is unable to type-check this expression in reasonable time
  已排除的方向：
    - 把 solver 的 memory(默认 516MB) / scope / trail 上限放到极大值：无效
    - 换 Xcode 26.5（Swift 6.3.2）与 26.6：同样失败
  日志里的实测（两个 Xcode 都一样）：
    ZoneDetailView.swift:516:29  单条表达式 type-check 花 11.5-13.1 秒
    全仓其它文件最慢 2-6 秒
  也就是说问题出在这段 body 里少数几条求解代价极高的表达式。

补丁做三件事，都是行为等价的改写：
  1) Image(systemName: canPurge ? "chevron.right" : "lock.fill")
     三元表达式让 Image(systemName:) 的重载消解变重，先算好字符串再传入。
  2) Button(isPinned ? String(localized: ...) : String(localized: ...),
            systemImage: isPinned ? ... : ...)
     同一条调用里两个三元 + String(localized:) 的重载集合，拆成属性。
  3) .alert("操作失败", isPresented: .init(get:set:)) 的内联 Binding 提到属性里。

幂等：已经是打过补丁的形态就跳过；目标模式不存在就跳过（上游已改写）。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/Orange Cloud/Views/Zones/ZoneDetailView.swift"
)

PROPS = """
    /// OSS 构建补丁（.github/oss-patches/zone-detail-type-check.py）
    /// 原先直接写在视图里：Image(systemName: canPurge ? ... : ...) 这条表达式
    /// 实测要 11-13 秒才能 type-check，是整段 body 求解代价的大头。
    private var purgeChevronName: String {
        canPurge ? "chevron.right" : "lock.fill"
    }

    /// OSS 构建补丁：同一条 Button 调用里塞了两个三元 + String(localized:)，
    /// 重载消解代价高，拆成属性。
    private var pinButtonTitle: String {
        isPinned ? String(localized: "取消固定") : String(localized: "固定到首页")
    }

    private var pinButtonImage: String {
        isPinned ? "pin.fill" : "pin"
    }
"""

MARK_OLD = "    // MARK: - 设置开关行\n"
MARK_NEW = "    // MARK: - 设置开关行\n" + PROPS

IMG_OLD = 'Image(systemName: canPurge ? "chevron.right" : "lock.fill")'
IMG_NEW = "Image(systemName: purgeChevronName)"

PIN_OLD = """                Button(isPinned ? String(localized: "取消固定") : String(localized: "固定到首页"),
                       systemImage: isPinned ? "pin.fill" : "pin") {"""
PIN_NEW = """                Button(pinButtonTitle, systemImage: pinButtonImage) {"""

ALERT_OLD = """        .alert("操作失败", isPresented: .init(
            get: { actionsViewModel.error != nil },
            set: { if !$0 { actionsViewModel.error = nil } }
        )) {"""
ALERT_NEW = """        .alert("操作失败", isPresented: actionErrorPresented) {"""

ALERT_PROP_OLD = """        } message: {
            Text(actionsViewModel.error ?? "")
        }
    }
"""
ALERT_PROP_NEW = """        } message: {
            Text(actionsViewModel.error ?? "")
        }
    }

    /// OSS 构建补丁：内联 Binding 会让 body 这条超长表达式链更难推断，提到属性里。
    private var actionErrorPresented: Binding<Bool> {
        Binding(
            get: { actionsViewModel.error != nil },
            set: { if !$0 { actionsViewModel.error = nil } }
        )
    }
"""


def apply(src: str, old: str, new: str, already: str, label: str, log: list) -> str:
    if already in src:
        log.append(f"跳过（已打过）：{label}")
        return src
    if old not in src:
        log.append(f"::notice::目标模式未找到，跳过：{label}")
        return src
    log.append(f"已应用：{label}")
    return src.replace(old, new, 1)


def main() -> int:
    if not TARGET.exists():
        print(f"::error::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 1

    src = TARGET.read_text(encoding="utf-8")
    log: list = []

    src = apply(src, MARK_OLD, MARK_NEW, "purgeChevronName: String", "新增三个计算属性", log)
    src = apply(src, IMG_OLD, IMG_NEW, "Image(systemName: purgeChevronName)", "Image 三元表达式", log)
    src = apply(src, PIN_OLD, PIN_NEW, "Button(pinButtonTitle, systemImage: pinButtonImage)", "Button 双三元", log)
    src = apply(src, ALERT_OLD, ALERT_NEW, "isPresented: actionErrorPresented", "alert 内联 Binding", log)
    src = apply(src, ALERT_PROP_OLD, ALERT_PROP_NEW, "actionErrorPresented: Binding<Bool>", "actionErrorPresented 属性", log)

    TARGET.write_text(src, encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
