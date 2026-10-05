#!/usr/bin/env python3
"""gitstat — 仓库活跃度一览：谁提交了多少、什么时候提交。

纯标准库，只读 git 历史，不修改任何东西。
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime

VERSION = "0.1.0"
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
HEAT = " ▁▂▃▄▅▆▇█"


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run_git(args):
    try:
        p = subprocess.run(["git"] + args, capture_output=True, text=True)
    except FileNotFoundError:
        die("找不到 git 命令，请先安装 git。")
    return p


def check_repo():
    p = run_git(["rev-parse", "--is-inside-work-tree"])
    if p.returncode != 0:
        die("当前目录不在 git 仓库中。")


def collect(since=None, author=None):
    """返回 commits 列表：每项 {author, ts, files:[(add,del,path)]}。

    解析方式：逐行扫描。含 US 分隔符且形如 "<40位hash><US><作者><US><时间戳>"
    的行开启一个新提交；其后的 numstat 行（add<TAB>del<TAB>path）归属该提交。
    （git 把 --format 头放在每个提交的 numstat 块之前，所以不能按记录分隔符切块。）
    """
    US = chr(31)  # 字段分隔符，作者名/文件名里几乎不可能出现
    fmt = "%H" + US + "%an" + US + "%at"
    args = ["log", "--format=" + fmt, "--numstat", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if author:
        args.append(f"--author={author}")
    p = run_git(args)
    if p.returncode != 0:
        die(f"git log 失败：{p.stderr.strip()}")
    commits = []
    cur = None
    for line in p.stdout.split("\n"):
        if US in line:
            parts = line.split(US)
            if (len(parts) == 3 and len(parts[0]) == 40
                    and parts[2].strip().isdigit()):
                cur = {"author": parts[1], "ts": int(parts[2]), "files": []}
                commits.append(cur)
                continue
        if cur is not None:
            s = line.strip()
            if not s:
                continue
            parts = s.split("\t")
            if len(parts) >= 3:
                try:
                    cur["files"].append((int(parts[0]), int(parts[1]), parts[2]))
                except ValueError:
                    # 二进制文件显示为 - -，插入/删除记 0，但文件算一次变更
                    cur["files"].append((0, 0, parts[2]))
    return commits


def summarize(commits):
    authors = Counter()
    weekdays = Counter()
    hours = Counter()
    insertions = deletions = 0
    files_touched = set()
    first = last = None
    for c in commits:
        authors[c["author"]] += 1
        dt = datetime.fromtimestamp(c["ts"])
        weekdays[dt.weekday()] += 1
        hours[dt.hour] += 1
        if first is None or c["ts"] < first:
            first = c["ts"]
        if last is None or c["ts"] > last:
            last = c["ts"]
        for add, dele, path in c["files"]:
            insertions += add
            deletions += dele
            files_touched.add(path)
    return {
        "commits": len(commits),
        "authors": dict(authors),
        "weekdays": {WEEKDAYS[i]: weekdays.get(i, 0) for i in range(7)},
        "hours": {h: hours.get(h, 0) for h in range(24)},
        "first": first,
        "last": last,
        "insertions": insertions,
        "deletions": deletions,
        "files_changed": len(files_touched),
    }


def bar(n, max_n, width=30):
    if max_n <= 0:
        return ""
    return "█" * max(1, round(n / max_n * width)) if n else ""


def print_report(s):
    print("===== 仓库活跃度 =====\n")
    f = datetime.fromtimestamp(s["first"]).strftime("%Y-%m-%d")
    l = datetime.fromtimestamp(s["last"]).strftime("%Y-%m-%d")
    print(f"提交总数：{s['commits']}　首次：{f}　最近：{l}")
    print(f"变更文件：{s['files_changed']} 个　新增：{s['insertions']} 行　删除：{s['deletions']} 行\n")

    print("## 按作者")
    amax = max(s["authors"].values()) if s["authors"] else 0
    for name, n in sorted(s["authors"].items(), key=lambda x: -x[1]):
        print(f"  {name:<16} {n:>4}  {bar(n, amax)}")
    print("\n## 按星期")
    wmax = max(s["weekdays"].values()) if s["weekdays"] else 0
    for wd in WEEKDAYS:
        n = s["weekdays"][wd]
        print(f"  {wd}  {n:>4}  {bar(n, wmax)}")
    print("\n## 按小时（全天热度）")
    hmax = max(s["hours"].values()) if s["hours"] else 0
    strip = "".join(HEAT[round(s["hours"][h] / hmax * 8)] if hmax else " "
                    for h in range(24))
    print(f"  00{'':>22}12{'':>22}23")
    print(f"  {strip}")
    print(f"  最高峰：{max(s['hours'], key=lambda h: s['hours'][h]):02d}:00"
          f"（{hmax} 次提交）" if hmax else "  暂无数据")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="gitstat",
        description="仓库活跃度一览：谁提交了多少、什么时候提交（只读，不修改仓库）。")
    ap.add_argument("--since", metavar="DATE",
                    help="只统计此时间之后的提交，如 '3 months ago'、'2026-01-01'")
    ap.add_argument("--author", metavar="NAME", help="只统计某作者（git --author 语法）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--version", action="version", version=f"gitstat {VERSION}")
    args = ap.parse_args(argv)

    check_repo()
    commits = collect(since=args.since, author=args.author)
    if not commits:
        die("没有符合条件的提交。")
    s = summarize(commits)
    if args.json:
        out = dict(s)
        out["first"] = datetime.fromtimestamp(s["first"]).isoformat()
        out["last"] = datetime.fromtimestamp(s["last"]).isoformat()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print_report(s)


if __name__ == "__main__":
    main()
