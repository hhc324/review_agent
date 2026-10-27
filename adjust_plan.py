#!/usr/bin/env python3
"""动态调整复习方案脚本。

输入:
  - plan.json（必需）
  - quiz_result.json（必需）：答题反馈数据

调整算法:
  1. 按知识点统计正确率
  2. 正确率 < 60% → 提升优先级 + 增加复习时长 + 降低掌握度
  3. 正确率 60%-90% → 维持当前安排 + 微调掌握度
  4. 正确率 > 90% → 降低优先级 + 提升掌握度
  5. 重新分配剩余天数任务

输出:
  - adjusted_plan.json（调整后的计划）
  - adjustment_report.md（调整说明）

用法:
  python adjust_plan.py --plan plan.json --feedback quiz_result.json --output adjusted_plan.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import ReviewPlan, DailyTask, QuizResult, load_plan, clamp


# 调整阈值
CORRECT_RATE_LOW = 0.6       # 正确率低于此值 → 加强复习
CORRECT_RATE_HIGH = 0.9      # 正确率高于此值 → 减少复习

# 掌握度调整幅度
MASTERY_BOOST = 0.15         # 高正确率时掌握度提升
MASTERY_DROP = 0.20          # 低正确率时掌握度下降
MASTERY_NUDGE = 0.05         # 中等正确率微调


def aggregate_by_topic(result: QuizResult) -> dict[str, dict]:
    """按知识点聚合答题结果。"""
    stats: dict[str, dict] = {}
    for record in result.records:
        topic = record.topic
        if topic not in stats:
            stats[topic] = {"correct": 0, "total": 0, "total_time": 0}
        stats[topic]["total"] += 1
        if record.correct:
            stats[topic]["correct"] += 1
        stats[topic]["total_time"] += record.time_seconds

    for topic in stats:
        s = stats[topic]
        s["accuracy"] = s["correct"] / s["total"] if s["total"] > 0 else 0.0
        s["avg_time"] = s["total_time"] / s["total"] if s["total"] > 0 else 0
    return stats


def compute_mastery_update(stats: dict[str, dict]) -> dict[str, float]:
    """根据答题正确率计算掌握度调整量。"""
    updates: dict[str, float] = {}
    for topic, s in stats.items():
        acc = s["accuracy"]
        if acc < CORRECT_RATE_LOW:
            updates[topic] = -MASTERY_DROP
        elif acc > CORRECT_RATE_HIGH:
            updates[topic] = MASTERY_BOOST
        else:
            # 线性微调：正确率越高，正向微调越大
            normalized = (acc - CORRECT_RATE_LOW) / (CORRECT_RATE_HIGH - CORRECT_RATE_LOW)
            updates[topic] = -MASTERY_NUDGE + 2 * MASTERY_NUDGE * normalized
    return updates


def adjust_plan(plan: ReviewPlan, result: QuizResult) -> tuple[ReviewPlan, str]:
    """调整复习计划。"""
    stats = aggregate_by_topic(result)
    mastery_updates = compute_mastery_update(stats)

    # 找出需要加强和可以减少的知识点
    need_reinforce: list[str] = []
    can_reduce: list[str] = []
    for topic, s in stats.items():
        if s["accuracy"] < CORRECT_RATE_LOW:
            need_reinforce.append(topic)
        elif s["accuracy"] > CORRECT_RATE_HIGH:
            can_reduce.append(topic)

    # 确定当前进度（假设反馈来自第 N 天，调整第 N+1 天及以后）
    # 简化处理：调整所有 review 类型的后续任务
    adjusted_tasks: list[DailyTask] = []
    adjustments_log: list[str] = []

    for task in plan.daily_tasks:
        new_task = DailyTask(
            day=task.day,
            topics=list(task.topics),
            duration_minutes=task.duration_minutes,
            task_type=task.task_type,
            priority=task.priority,
            focus=task.focus,
        )

        # 对包含薄弱知识点的任务：增加时长和优先级
        reinforce_in_task = [t for t in new_task.topics if t in need_reinforce]
        if reinforce_in_task:
            new_task.duration_minutes = int(new_task.duration_minutes * 1.3)
            new_task.priority = new_task.priority * 1.2
            new_task.focus = (
                f"{new_task.focus} | ⚡ 加强复习: "
                f"{', '.join(reinforce_in_task[:3])}"
            )
            adjustments_log.append(
                f"第 {new_task.day} 天: 加强复习 "
                f"{', '.join(reinforce_in_task)}（时长 +30%, 优先级 +20%）"
            )

        # 对包含已掌握知识点的任务：减少时长
        reduce_in_task = [t for t in new_task.topics if t in can_reduce]
        if reduce_in_task and not reinforce_in_task:
            new_task.duration_minutes = int(new_task.duration_minutes * 0.7)
            new_task.priority = new_task.priority * 0.8
            new_task.focus = (
                f"{new_task.focus} | ✓ 已掌握可减少: "
                f"{', '.join(reduce_in_task[:3])}"
            )
            adjustments_log.append(
                f"第 {new_task.day} 天: 减少复习 "
                f"{', '.join(reduce_in_task)}（时长 -30%, 优先级 -20%）"
            )

        adjusted_tasks.append(new_task)

    # 如果有大量需要加强的知识点，追加专项复习任务
    if len(need_reinforce) > 3:
        insert_day = 1
        reinforce_task = DailyTask(
            day=0,  # 标记为插入任务
            topics=need_reinforce[:10],
            duration_minutes=90,
            task_type="review",
            priority=5.0,
            focus=f"⚡ 专项强化薄弱知识点（基于答题反馈新增）: "
                  f"{', '.join(need_reinforce[:5])}",
        )
        adjusted_tasks.insert(insert_day, reinforce_task)
        adjustments_log.insert(0,
            f"新增专项强化任务: 覆盖 {len(need_reinforce)} 个薄弱知识点")

    total_minutes = sum(t.duration_minutes for t in adjusted_tasks)
    total_hours = round(total_minutes / 60.0, 1)

    adjusted_plan = ReviewPlan(
        course_name=plan.course_name,
        total_days=plan.total_days,
        daily_tasks=adjusted_tasks,
        created_at=plan.created_at,
        total_duration_hours=total_hours,
        notes=(
            f"{plan.notes} | 已根据答题反馈调整。"
            f"加强 {len(need_reinforce)} 个薄弱点，"
            f"减少 {len(can_reduce)} 个已掌握点。"
        ),
    )

    # 生成调整报告
    report_lines = [
        f"# 复习计划调整报告 — {plan.course_name}",
        "",
        f"> 调整时间: {datetime.now().isoformat()}",
        "",
        "## 答题反馈概览",
        "",
        f"- 总答题数: {result.total_count}",
        f"- 总正确数: {result.total_correct}",
        f"- 总正确率: {result.overall_accuracy * 100:.1f}%",
        "",
        "## 各知识点答题情况",
        "",
        "| 知识点 | 正确率 | 题数 | 平均用时(秒) | 掌握度变化 | 调整动作 |",
        "|--------|--------|------|-------------|-----------|----------|",
    ]

    for topic, s in sorted(stats.items(), key=lambda x: x[1]["accuracy"]):
        update = mastery_updates[topic]
        update_str = f"{update:+.2f}"
        if s["accuracy"] < CORRECT_RATE_LOW:
            action = "⚡ 加强复习"
        elif s["accuracy"] > CORRECT_RATE_HIGH:
            action = "✓ 减少复习"
        else:
            action = "○ 维持"
        report_lines.append(
            f"| {topic} | {s['accuracy']*100:.0f}% | {s['total']} | "
            f"{s['avg_time']:.0f} | {update_str} | {action} |"
        )

    report_lines.extend([
        "",
        "## 调整明细",
        "",
    ])
    if adjustments_log:
        report_lines.extend(f"- {log}" for log in adjustments_log)
    else:
        report_lines.append("- 无需调整，当前计划保持不变")

    report_lines.extend([
        "",
        "## 掌握度更新建议",
        "",
        "以下知识点掌握度建议更新（可用于下一轮评估）：",
        "",
        "```json",
        "{",
    ])
    for topic, update in mastery_updates.items():
        report_lines.append(f'  "{topic}": {update:+.3f},')
    report_lines.extend([
        "}",
        "```",
        "",
    ])

    return adjusted_plan, "\n".join(report_lines)


def main():
    parser = argparse.ArgumentParser(description="动态调整复习方案")
    parser.add_argument("--plan", required=True, help="plan.json 路径")
    parser.add_argument("--feedback", required=True, help="quiz_result.json 路径")
    parser.add_argument("--output", "-o", default="adjusted_plan.json",
                        help="调整后计划输出路径")
    parser.add_argument("--report", default="adjustment_report.md",
                        help="调整报告输出路径")
    args = parser.parse_args()

    try:
        plan = load_plan(args.plan)
        result = QuizResult.from_json_file(args.feedback)

        adjusted_plan, report = adjust_plan(plan, result)
        adjusted_plan.to_json(args.output)

        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"[成功] 课程: {adjusted_plan.course_name}")
        print(f"  原始总时长: {plan.total_duration_hours}h → "
              f"调整后: {adjusted_plan.total_duration_hours}h")
        print(f"  答题正确率: {result.overall_accuracy*100:.1f}%")
        print(f"  调整后计划: {args.output}")
        print(f"  调整报告: {args.report}")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
