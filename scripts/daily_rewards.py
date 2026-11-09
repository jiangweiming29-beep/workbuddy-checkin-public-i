#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端巡检/处理猫猫旅行及成长任务；复用现有签到凭据，不读取本机会话。"""
import argparse
import json
import sys
import time

from workbuddy_checkin import api_call, resolve_credential

BASE = "https://www.codebuddy.cn"
TASKS = "/v2/activity/growth/tasks"
ACCEPT = "/v2/activity/growth/tasks/accept"
CLAIM = "/v2/activity/growth/tasks/%s/claim"
TRAVEL_STATUS = "/v2/activity/growth/buddy/travel/status"
TRAVEL_DEPART = "/v2/activity/growth/buddy/travel/depart"
TRAVEL_CLAIM = "/v2/activity/growth/buddy/travel/claim"
TRAVEL_CONFIG = "/v2/activity/growth/buddy/travel/config"


def request(token, path, method="GET", body=None):
    """只保留业务结果；不向公开日志输出原始响应或任何凭据。"""
    status, response = api_call(BASE, path, token,
                                payload=body if body is not None else {},
                                method=method)
    if not isinstance(response, dict):
        return {"ok": False, "message": "接口响应格式异常", "http_status": status}
    return {"ok": response.get("code") == 0,
            "message": str(response.get("msg") or response.get("message") or "")[:200],
            "data": response.get("data") if isinstance(response.get("data"), dict) else {},
            "http_status": status}


def inspect_tasks(token, dry_run):
    response = request(token, TASKS)
    result = {"status": "ok" if response["ok"] else "error", "dry_run": dry_run,
              "claimable": [], "claimed_now": [], "accepted": [], "in_progress": [],
              "already_claimed": [], "errors": [], "credits_gained": 0}
    if not response["ok"]:
        result["message"] = response["message"] or "无法读取成长任务"
        return result
    to_accept = []
    for task in response["data"].get("tasks") or []:
        if not isinstance(task, dict):
            continue
        code = task.get("task_code")
        if not isinstance(code, str) or not code or "/" in code:
            continue
        state = task.get("accept_status")
        title = str(task.get("title") or code)[:100]
        credit = task.get("reward_credit") or 0
        item = {"task_code": code, "title": title, "credit": credit}
        if state == "claimed":
            result["already_claimed"].append(item)
        elif state == "not_accepted":
            if not task.get("locked"):
                to_accept.append(code)
        else:
            progress = task.get("progress") or {}
            current = progress.get("current") or 0
            target = progress.get("target") or 0
            if state == "completed" or (target and current >= target):
                result["claimable"].append(item)
            else:
                item["progress"] = "%s/%s" % (current, target)
                result["in_progress"].append(item)
    if to_accept and not dry_run:
        time.sleep(0.6)
        accepted = request(token, ACCEPT, "POST", {"task_codes": to_accept})
        if accepted["ok"]:
            rows = accepted["data"].get("results") or []
            result["accepted"] = [x.get("task_code") for x in rows
                                  if isinstance(x, dict) and x.get("task_code")]
        else:
            result["errors"].append({"operation": "accept", "message": accepted["message"]})
    for item in result["claimable"]:
        if dry_run:
            continue
        time.sleep(0.6)
        claim = request(token, CLAIM % item["task_code"], "POST", {})
        if claim["ok"]:
            data = claim["data"]
            if not data.get("already_claimed"):
                item = dict(item)
                item["credit"] = data.get("credit") or item["credit"] or 0
                result["claimed_now"].append(item)
                result["credits_gained"] += item["credit"]
        else:
            result["errors"].append({"task_code": item["task_code"], "message": claim["message"]})
    result["status"] = "error" if result["errors"] else "ok"
    result["message"] = ("本次领取 %s 项、+%s 积分" %
                         (len(result["claimed_now"]), result["credits_gained"])
                         if result["claimed_now"] else
                         "可领取 %s 项（只读未领）" % len(result["claimable"]) if dry_run else
                         "暂无已完成待领奖励；%s 项进行中" % len(result["in_progress"]))
    return result


def inspect_travel(token, dry_run):
    result = {"status": "ok", "dry_run": dry_run, "state": "unknown",
              "action": "none", "credits_gained": 0}
    current = request(token, TRAVEL_STATUS)
    if not current["ok"]:
        result.update(status="error", message=current["message"] or "无法读取旅行状态")
        return result
    data = current["data"]
    result["state"] = data.get("state") or "unknown"
    result["location"] = (data.get("location") or {}).get("name")
    if data.get("daily_limit_reached"):
        result["message"] = "今日旅行次数已达上限"
        return result
    if result["state"] == "traveling":
        remaining = max(0, int(data.get("arrive_at") or 0) - int(data.get("server_now") or time.time()))
        result["remaining_seconds"] = remaining
        result["message"] = "旅行中，预计还需 %s 分钟" % ((remaining + 59) // 60)
        return result
    if result["state"] == "arrived":
        result["claimable_credit"] = data.get("reward_credit") or 0
        if dry_run:
            result.update(action="would_claim", message="旅行已到达，奖励待领（只读未领）")
            return result
        time.sleep(0.6)
        claim = request(token, TRAVEL_CLAIM, "POST", {})
        if not claim["ok"]:
            result.update(status="error", message=claim["message"] or "旅行奖励领取失败")
            return result
        result["credits_gained"] = claim["data"].get("reward_credit") or result["claimable_credit"]
        result["action"] = "claimed"
        # 领取后若空闲，继续派下一轮；下轮由后续定时领取。
        current = request(token, TRAVEL_STATUS)
        data = current["data"] if current["ok"] else {}
        result["state"] = data.get("state") or "idle"
    if result["state"] == "idle":
        if dry_run:
            result.update(action="would_depart", message="猫猫空闲，可以派出（只读未派出）")
            return result
        config = request(token, TRAVEL_CONFIG)
        locations = config["data"].get("locations") or []
        location = locations[0] if locations else None
        if not location or not location.get("id"):
            result.update(status="error", message="无法读取旅行地点")
            return result
        time.sleep(0.6)
        depart = request(token, TRAVEL_DEPART, "POST", {"location_id": location["id"]})
        if not depart["ok"]:
            result.update(status="error", message=depart["message"] or "猫猫出发失败")
            return result
        data = depart["data"]
        result.update(state=data.get("state") or "traveling", action="departed",
                      location=(data.get("location") or {}).get("name") or location.get("name"))
        remaining = max(0, int(data.get("arrive_at") or 0) - int(data.get("server_now") or time.time()))
        result["remaining_seconds"] = remaining
        result["message"] = "已派猫猫旅行，预计 %s 分钟后到达" % ((remaining + 59) // 60)
        return result
    result["message"] = "旅行奖励已领取，+%s 积分" % result["credits_gained"]
    return result


def main():
    parser = argparse.ArgumentParser(description="云端巡检并领取其他积分任务")
    parser.add_argument("--dry-run", action="store_true", help="只读，不接受、领取或派出")
    args = parser.parse_args()
    auth = {"detail": {}}
    token, domain, error = resolve_credential(auth)
    if error:
        print(json.dumps({"status": "error", "message": error}, ensure_ascii=False, indent=2))
        return 1
    report = {"status": "ok", "dry_run": args.dry_run,
              "tasks": inspect_tasks(token, args.dry_run),
              "travel": inspect_travel(token, args.dry_run)}
    if any(report[key]["status"] == "error" for key in ("tasks", "travel")):
        report["status"] = "partial_error"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
