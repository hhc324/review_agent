#!/usr/bin/env python3
"""学情薄弱点评估脚本。

输入:
  - syllabus.json（必需）
  - 学情数据（可选）：平时成绩 / 自评等级 / 错题记录

无学情数据时，基于知识点难度和依赖深度初始化掌握度：
  mastery = 1.0 - difficulty * 0.5 - dependency_depth_penalty

有学情数据时，综合加权计算：
  mastery = w1 * exam_score + w2 * self_rating + w3 * (1 - error_rate)

输出: weakness.json

用法:
  python assess_weakness.py --syllabus syllabus.json --output weakness.json
  python assess_weakness.py --syllabus syllabus.json --mastery mastery.json --output weakness.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import Syllabus, WeaknessReport, Topic, clamp, load_syllabus


# 薄弱等级阈值
WEAK_THRESHOLD = 0.4
MEDIUM_THRESHOLD = 0.7

# 学情数据权重
W_EXAM = 0.5       # 平时成绩权重
W_SELF = 0.3       # 自评权重
W_ERROR = 0.2      # 错题率权重


def compute_dependency_depth(syllabus: Syllabus) -> dict[str, int]:
    """计算每个知识点的依赖深度（拓扑层级）。"""
    topic_map = {t.name: t for t in syllabus.all_topics()}
    depth_cache: dict[str, int] = {}

    def get_depth(name: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if name in depth_cache:
            return depth_cache[name]
        if name in visited:
            return 0  # 循环依赖保护
        visited.add(name)
        topic = topic_map.get(name)
        if not topic or not topic.dependencies:
            depth = 0
        else:
            depth = 1 + max((get_depth(d, visited.copy()) for d in topic.dependencies
                             if d in topic_map), default=0)
        depth_cache[name] = depth
        return depth

    for name in topic_map:
        get_depth(name)
    return depth_cache


def assess_without_data(syllabus: Syllabus) -> dict[str, float]:
    """无学情数据时，基于难度和依赖深度初始化掌握度。

    假设：难度越高、依赖越深的知识点，初始掌握度越低。
    """
    depths = compute_dependency_depth(syllabus)
    max_depth = max(depths.values()) if depths else 1

    masteries: dict[str, float] = {}
    for topic in syllabus.all_topics():
        # 基础掌握度 = 1 - 难度影响
        base = 1.0 - topic.difficulty * 0.5
        # 依赖深度惩罚：深度越大，掌握度越低
        depth_penalty = (depths.get(topic.name, 0) / max(max_depth, 1)) * 0.2
        mastery = clamp(base - depth_penalty)
        masteries[topic.name] = round(mastery, 3)
    return masteries


def load_mastery_data(path: str) -> dict:
    """加载学情数据文件。

    支持格式:
      {
        "topic_scores": { "知识点名": 0.0-1.0, ... },     # 平时成绩（归一化）
        "self_ratings": { "知识点名": 0.0-1.0, ... },     # 自评等级
        "error_records": { "知识点名": 错题次数, ... },    # 错题记录
        "exam_scores": { "知识点名": 0-100, ... },        # 百分制成绩
        "global_self_rating": 0.0-1.0                      # 全局自评
      }
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def assess_with_data(syllabus: Syllabus, data: dict) -> tuple[dict[str, float], str]:
    """有学情数据时，综合加权计算掌握度。"""
    topic_scores = data.get("topic_scores", {})
    self_ratings = data.get("self_ratings", {})
    error_records = data.get("error_records", {})
    exam_scores = data.get("exam_scores", {})
    global_self = data.get("global_self_rating", -1)

    # 将百分制成绩归一化
    normalized_exam = {}
    for k, v in exam_scores.items():
        normalized_exam[k] = clamp(v / 100.0)

    # 合并成绩来源
    all_exam = {**normalized_exam, **topic_scores}

    # 计算错题率（相对于最大错题数）
    max_errors = max(error_records.values()) if error_records else 1

    masteries: dict[str, float] = {}
    components_used = []

    for topic in syllabus.all_topics():
        name = topic.name
        parts = []
        weights = []

        if name in all_exam:
            parts.append(all_exam[name])
            weights.append(W_EXAM)
            if "exam" not in components_used:
                components_used.append("exam")

        if name in self_ratings:
            parts.append(self_ratings[name])
            weights.append(W_SELF)
            if "self_rating" not in components_used:
                components_used.append("self_rating")
        elif global_self >= 0:
            parts.append(global_self)
            weights.append(W_SELF)
            if "global_self_rating" not in components_used:
                components_used.append("global_self_rating")

        if name in error_records:
            error_rate = error_records[name] / max(max_errors, 1)
            parts.append(1.0 - error_rate)
            weights.append(W_ERROR)
            if "error_rate" not in components_used:
                components_used.append("error_rate")

        if parts:
            total_w = sum(weights)
            mastery = sum(p * w for p, w in zip(parts, weights)) / total_w
        else:
            # 该知识点无数据，回退到无数据评估
            base = 1.0 - topic.difficulty * 0.5
            mastery = clamp(base)

        masteries[name] = round(clamp(mastery), 3)

    method = "weighted: " + " + ".join(components_used) if components_used else "fallback"
    return masteries, method


def classify_topics(masteries: dict[str, float]) -> tuple[list[str], list[str], list[str]]:
    """按掌握度分类知识点。"""
    weak, medium, strong = [], [], []
    for name, m in masteries.items():
        if m < WEAK_THRESHOLD:
            weak.append(name)
        elif m < MEDIUM_THRESHOLD:
            medium.append(name)
        else:
            strong.append(name)
    # 薄弱知识点按掌握度升序（最薄弱的排前面）
    weak.sort(key=lambda n: masteries[n])
    return weak, medium, strong


def assess(syllabus: Syllabus, mastery_data: dict | None = None) -> WeaknessReport:
    """执行学情评估。"""
    if mastery_data:
        masteries, method = assess_with_data(syllabus, mastery_data)
    else:
        masteries = assess_without_data(syllabus)
        method = "difficulty+dependency_heuristic"

    weak, medium, strong = classify_topics(masteries)

    total = len(masteries)
    summary = (
        f"共评估 {total} 个知识点。"
        f"薄弱({len(weak)}) / 中等({len(medium)}) / 掌握({len(strong)})。"
    )
    if weak:
        summary += f" 最薄弱: {weak[0]}({masteries[weak[0]]:.2f})。"

    return WeaknessReport(
        course_name=syllabus.course_name,
        topic_masteries=masteries,
        weak_topics=weak,
        medium_topics=medium,
        strong_topics=strong,
        assessment_method=method,
        summary=summary,
    )


def main():
    parser = argparse.ArgumentParser(description="评估学情薄弱点")
    parser.add_argument("--syllabus", required=True, help="syllabus.json 路径")
    parser.add_argument("--mastery", help="学情数据文件路径（可选）")
    parser.add_argument("--output", "-o", default="weakness.json", help="输出路径")
    args = parser.parse_args()

    try:
        syllabus = load_syllabus(args.syllabus)
        mastery_data = load_mastery_data(args.mastery) if args.mastery else None

        report = assess(syllabus, mastery_data)
        report.to_json(args.output)

        print(f"[成功] 课程: {report.course_name}")
        print(f"  评估方法: {report.assessment_method}")
        print(f"  薄弱: {len(report.weak_topics)} | "
              f"中等: {len(report.medium_topics)} | "
              f"掌握: {len(report.strong_topics)}")
        if report.weak_topics:
            print(f"  薄弱知识点: {', '.join(report.weak_topics[:5])}"
                  f"{'...' if len(report.weak_topics) > 5 else ''}")
        print(f"  输出: {args.output}")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
