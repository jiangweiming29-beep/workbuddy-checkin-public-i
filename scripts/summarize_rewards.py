#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把其他任务结果以白名单写入 Actions 摘要。"""
import json
import sys

try:
    with open(sys.argv[1] if len(sys.argv) > 1 else "rewards.json",
              encoding="utf-8") as f:
        report = json.load(f)
except Exception as exc:
    print("## 其他积分任务\n\n未能读取结果：%s" % exc)
    sys.exit(0)

print("## 其他积分任务")
print("\n模式：%s\n" % ("只读巡检" if report.get("dry_run") else "自动处理"))
tasks = report.get("tasks") or {}
print("### 成长计划任务\n")
print("- 本次领取：%s 项，+%s 积分" %
      (len(tasks.get("claimed_now") or []), tasks.get("credits_gained", 0)))
print("- 本次接受新任务：%s 项" % len(tasks.get("accepted") or []))
print("- 仍需真实使用完成：%s 项" % len(tasks.get("in_progress") or []))
for item in tasks.get("claimed_now") or []:
    print("  - 已领：%s（+%s）" % (item.get("title"), item.get("credit")))
for item in tasks.get("claimable") or []:
    print("  - 待领：%s（+%s）" % (item.get("title"), item.get("credit")))
travel = report.get("travel") or {}
print("\n### 猫猫旅行\n")
print("- %s" % (travel.get("message") or travel.get("state") or "无结果"))
print("- 本次旅行奖励：+%s 积分" % travel.get("credits_gained", 0))
if report.get("status") == "error":
    print("\n> 凭据获取失败，请检查长效令牌。")
