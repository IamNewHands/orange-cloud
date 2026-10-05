#!/usr/bin/env python3
"""OSS 构建补丁：把 ZoneDetailView 里求解代价过高的表达式拆开。

为什么不在源码里改：
  本仓库是 fork，main 由 CI 定时 merge 上游。改动上游文件会在每次上游变更时
  产生冲突，打断自动同步。所以补丁只在构建时应用，源码树保持与上游一致。

背景（runs 37251582830 … 37255704433）：
  apps/ios/.../Views/Zones/ZoneDetailView.swift 反复报
    error: the compiler is unable to type-check this expression in reasonable time
  已排除：solver 的 memory / scope / trail 上限放到极大值无效；Xcode 26.5 与 26.6 一样。
  已确认有效：修掉 Image(systemName: 三元) 与 Button 双三元后，日志里 >5s 的
  表达式告警全部消失，报错位置从 692 行后退到 443 行 —— 说明方向对，只是还没拆完。

补丁分两组，全部是行为等价的改写：
  A. 去掉重载消解的重灾区
     1) Image(systemName: canPurge ? "chevron.right" : "lock.fill")
     2) toolbar 里 Button 的两个三元
     3) 「操作失败」alert 的内联 Binding
  B. 把 body 里三块巨型 ViewBuilder 各自提成计算属性，让它们各自成为一次
     独立的类型检查（编译器提示的 "breaking up the expression into distinct
     sub-expressions" 就是这个意思）：
     4) sectionCard("管理")   -> manageSection
     5) if botConfigLoaded …  -> botControlSection
     6) sectionCard("操作")   -> actionsSection

幂等：已经打过的步骤跳过；目标模式找不到时打印 notice 跳过（上游已改写）。
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "apps/ios/Orange Cloud/Orange Cloud/Views/Zones/ZoneDetailView.swift"
)

MARK = "    // MARK: - 设置开关行\n"

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

# (块首行内容, 属性名, 注释) —— 按文档倒序处理，保证行号不串
BLOCKS = [
    ('sectionCard(String(localized: "操作")) {', "actionsSection", "「操作」分组卡"),
    ("if actionsViewModel.botConfigLoaded || actionsViewModel.aiSettingsAvailable {",
     "botControlSection", "AI 内容控制分组卡"),
    ('sectionCard(String(localized: "管理")) {', "manageSection", "「管理」分组卡"),
]

INDENT = 16


def apply_text(src: str, old: str, new: str, already: str, label: str, log: list) -> str:
    if already in src:
        log.append(f"跳过（已打过）：{label}")
        return src
    if old not in src:
        log.append(f"::notice::目标模式未找到，跳过：{label}")
        return src
    log.append(f"已应用：{label}")
    return src.replace(old, new, 1)


def extract_block(lines: list, start_text: str, prop: str, note: str, log: list,
                  indent: int = INDENT, decorator: str = "@ViewBuilder",
                  type_: str = "some View") -> bool:
    """把一段 ViewBuilder / ToolbarContent 语句提成独立计算属性。"""
    if f"private var {prop}: " in "".join(lines):
        log.append(f"跳过（已打过）：提取 {prop}")
        return False

    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == start_text and len(line) - len(line.lstrip()) == indent:
            start = i
            break
    if start is None:
        log.append(f"::notice::目标块未找到，跳过：{prop}")
        return False

    end = None
    for j in range(start + 1, len(lines)):
        s = lines[j]
        if s.strip() == "}" and len(s) - len(s.lstrip()) == indent:
            end = j
            break
    if end is None:
        log.append(f"::error::找不到 {prop} 的收尾大括号")
        return False

    body = lines[start:end + 1]
    dedented = []
    for line in body:
        if line.strip():
            if len(line) - len(line.lstrip()) < 4:
                log.append(f"::error::{prop} 内缩进异常，放弃")
                return False
            dedented.append(line[4:])
        else:
            dedented.append(line)

    lines[start:end + 1] = [" " * indent + prop + "\n"]

    prop_lines = [
        "\n",
        f"    /// OSS 构建补丁：把{note}整块提出来，让它单独成为一次类型检查\n",
        "    /// （编译器提示的 breaking up the expression into distinct sub-expressions）。\n",
        f"    {decorator}\n",
        f"    private var {prop}: {type_} {{\n",
        *dedented,
        "    }\n",
    ]
    anchor = lines.index(MARK)
    lines[anchor:anchor] = prop_lines
    log.append(f"已应用：提取 {prop}（{end - start + 1} 行）")
    return True


def main() -> int:
    if not TARGET.exists():
        print(f"::error::补丁目标不存在：{TARGET}", file=sys.stderr)
        return 1

    src = TARGET.read_text(encoding="utf-8")
    log: list = []

    src = apply_text(src, MARK, MARK + PROPS, "purgeChevronName: String", "新增三个计算属性", log)
    src = apply_text(src, IMG_OLD, IMG_NEW, "Image(systemName: purgeChevronName)", "Image 三元表达式", log)
    src = apply_text(src, PIN_OLD, PIN_NEW, "Button(pinButtonTitle, systemImage: pinButtonImage)", "Button 双三元", log)
    src = apply_text(src, ALERT_OLD, ALERT_NEW, "isPresented: actionErrorPresented", "alert 内联 Binding", log)
    src = apply_text(src, ALERT_PROP_OLD, ALERT_PROP_NEW, "actionErrorPresented: Binding<Bool>", "actionErrorPresented 属性", log)

    lines = src.splitlines(keepends=True)
    for start_text, prop, note in BLOCKS:
        if MARK not in lines:
            log.append("::error::找不到 MARK 锚点，跳过提取")
            break
        extract_block(lines, start_text, prop, note, log)

    # toolbar 里的 ToolbarItem 单独实测 6.2s，也提成 ToolbarContent。
    if MARK in lines:
        extract_block(
            lines,
            "ToolbarItem(placement: .topBarTrailing) {",
            "pinToolbarItem",
            "toolbar 里的置顶按钮（实测 6.2s）",
            log,
            indent=12,
            decorator="@ToolbarContentBuilder",
            type_="some ToolbarContent",
        )
    src = "".join(lines)

    TARGET.write_text(src, encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
