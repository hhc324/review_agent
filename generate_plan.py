#!/usr/bin/env python3
"""自适应复习计划生成脚本。

输入:
  - syllabus.json（必需）
  - weakness.json（必需）
  - 复习天数（默认 14）

算法:
  1. 计算每个知识点的复习优先级 = weight × (1 - mastery) × difficulty_factor
  2. 按依赖关系拓扑排序
  3. 薄弱点优先分配，按每日负载均衡分配到各天
  4. 最后 2 天安排综合复习与模拟测试

输出: plan.json

用法:
  python generate_plan.py --syllabus syllabus.json --weakness weakness.json --days 14 --output plan.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import (
    Syllabus, WeaknessReport, ReviewPlan, DailyTask, Topic,
    load_syllabus, load_weakness,
)


def topological_sort(syllabus: Syllabus) -> list[Topic]:
    """按依赖关系拓扑排序知识点（被依赖的先复习）。"""
    topics = syllabus.all_topics()
    name_set = {t.name for t in topics}
    topic_map = {t.name: t for t in topics}

    visited: set[str] = set()
    on_stack: set[str] = set()
    result: list[Topic] = []

    def visit(name: str):
        if name in visited or name not in name_set:
            return
        if name in on_stack:
            return  # 循环依赖保护
        on_stack.add(name)
        topic = topic_map[name]
        for dep in topic.dependencies:
            visit(dep)
        on_stack.discard(name)
        visited.add(name)
        result.append(topic)

    for t in topics:
        visit(t.name)

    return result


def compute_priority(topic: Topic, mastery: float) -> float:
    """计算知识点复习优先级。

    优先级 = weight × (1 - mastery) × (1 + difficulty × 0.5)
    掌握度越低、权重越高、难度越大 → 优先级越高
    """
    difficulty_factor = 1.0 + topic.difficulty * 0.5
    return topic.weight * (1.0 - mastery) * difficulty_factor


def estimate_duration(topic: Topic, mastery: float) -> int:
    """估算单个知识点复习时长（分钟）。

    基础 15 分钟，根据难度和薄弱程度增加。
    """
    base = 15
    difficulty_add = int(topic.difficulty * 20)
    weakness_add = int((1.0 - mastery) * 30)
    importance_add = {"core": 15, "important": 10, "normal": 5, "optional": 0}.get(
        topic.importance, 5
    )
    return base + difficulty_add + weakness_add + importance_add


def generate_plan(
    syllabus: Syllabus,
    weakness: WeaknessReport,
    days: int = 14,
    daily_minutes: int = 120,
) -> ReviewPlan:
    """生成复习计划。"""
    if days < 3:
        raise ValueError("复习天数至少需要 3 天")

    masteries = weakness.topic_masteries
    sorted_topics = topological_sort(syllabus)

    # 计算优先级和时长
    topic_info = []
    for topic in sorted_topics:
        mastery = masteries.get(topic.name, 0.5)
        priority = compute_priority(topic, mastery)
        duration = estimate_duration(topic, mastery)
        topic_info.append((topic, priority, duration, mastery))

    # 按优先级降序排序（高优先级先分配）
    topic_info.sort(key=lambda x: -x[1])

    # 分配天数：前 N-2 天知识点复习，最后 2 天综合+模拟
    review_days = days - 2
    daily_tasks: list[DailyTask] = []

    # 贪心分配：按优先级依次分配到当前负载最轻的天
    day_loads = [0] * review_days       # 每天已分配时长
    day_topics: list[list[str]] = [[] for _ in range(review_days)]
    day_priorities = [0.0] * review_days
    day_durations = [0] * review_days

    for topic, priority, duration, mastery in topic_info:
        # 找当前负载最轻且未超载的天
        best_day = min(range(review_days), key=lambda d: day_loads[d])
        day_topics[best_day].append(topic.name)
        day_loads[best_day] += duration
        day_priorities[best_day] = max(day_priorities[best_day], priority)
        day_durations[best_day] += duration

    # 构建每日任务
    base_date = datetime.now().date()
    for d in range(review_days):
        if not day_topics[d]:
            continue
        date_str = (base_date + timedelta(days=d)).isoformat()
        # 确定任务类型和重点
        avg_mastery = sum(
            masteries.get(t, 0.5) for t in day_topics[d]
        ) / len(day_topics[d])
        if avg_mastery < 0.4:
            task_type = "review"
            focus = "重点攻克薄弱知识点"
        elif avg_mastery < 0.7:
            task_type = "review"
            focus = "巩固中等掌握度知识点"
        else:
            task_type = "practice"
            focus = "强化练习已掌握知识点"

        daily_tasks.append(DailyTask(
            day=d + 1,
            topics=day_topics[d],
            duration_minutes=min(day_durations[d], daily_minutes),
            task_type=task_type,
            priority=round(day_priorities[d], 3),
            focus=focus,
        ))

    # 倒数第二天：综合复习
    all_weak = weakness.weak_topics
    all_medium = weakness.medium_topics
    summary_topics = all_weak + all_medium[:len(all_medium) // 2]
    daily_tasks.append(DailyTask(
        day=days - 1,
        topics=summary_topics or [t.name for t in sorted_topics[:5]],
        duration_minutes=daily_minutes,
        task_type="summary",
        priority=2.0,
        focus="综合复习薄弱与中等知识点，梳理知识体系",
    ))

    # 最后一天：模拟测试
    daily_tasks.append(DailyTask(
        day=days,
        topics=[t.name for t in sorted_topics],
        duration_minutes=daily_minutes,
        task_type="mock",
        priority=3.0,
        focus="全真模拟测试，检验复习效果",
    ))

    total_minutes = sum(t.duration_minutes for t in daily_tasks)
    total_hours = round(total_minutes / 60.0, 1)

    notes = (
        f"共 {days} 天复习计划，覆盖 {len(sorted_topics)} 个知识点。"
        f"前 {review_days} 天知识点专项复习，第 {days-1} 天综合复习，第 {days} 天模拟测试。"
        f"总预计时长 {total_hours} 小时。"
    )

    return ReviewPlan(
        course_name=syllabus.course_name,
        total_days=days,
        daily_tasks=daily_tasks,
        created_at=datetime.now().isoformat(),
        total_duration_hours=total_hours,
        notes=notes,
    )


def main():
    parser = argparse.ArgumentParser(description="生成自适应复习计划")
    parser.add_argument("--syllabus", required=True, help="syllabus.json 路径")
    parser.add_argument("--weakness", required=True, help="weakness.json 路径")
    parser.add_argument("--days", type=int, default=14, help="复习天数（默认 14）")
    parser.add_argument("--daily-minutes", type=int, default=120,
                        help="每日最大复习时长（分钟，默认 120）")
    parser.add_argument("--output", "-o", default="plan.json", help="输出路径")
    args = parser.parse_args()

    try:
        syllabus = load_syllabus(args.syllabus)
        weakness = load_weakness(args.weakness)

        plan = generate_plan(syllabus, weakness, args.days, args.daily_minutes)
        plan.to_json(args.output)

        print(f"[成功] 课程: {plan.course_name}")
        print(f"  复习天数: {plan.total_days}")
        print(f"  总时长: {plan.total_duration_hours} 小时")
        print(f"  每日任务数: {len(plan.daily_tasks)}")
        print(f"  输出: {args.output}")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[失败] 参数错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
