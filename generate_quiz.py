#!/usr/bin/env python3
"""自测习题生成脚本。

输入:
  - syllabus.json（必需）
  - weakness.json（必需）
  - 题型（choice/fill/short/application/true_false，默认全部）
  - 题量（默认 20）

选题策略:
  - 薄弱知识点分配 50% 题量
  - 中等知识点分配 35% 题量
  - 掌握知识点分配 15% 题量（巩固）
  - 难度根据掌握度自适应

输出: quiz.json
  注意: 题目内容（题干/选项/答案/解析）标记 needs_model=True，
  需由模型语义生成。脚本负责结构化框架与选题策略。

用法:
  python generate_quiz.py --syllabus syllabus.json --weakness weakness.json --types choice,fill,short --count 30 --output quiz.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import Syllabus, WeaknessReport, Quiz, Question, load_syllabus, load_weakness


# 题型分配比例（在总题量内分配）
TYPE_RATIOS = {
    "choice": 0.35,         # 选择题
    "fill": 0.20,           # 填空题
    "short": 0.25,          # 简答题
    "application": 0.15,    # 应用题
    "true_false": 0.05,     # 判断题
}

# 掌握度分组 → 题量分配比例
GROUP_RATIOS = {
    "weak": 0.50,       # 薄弱知识点 50% 题量
    "medium": 0.35,     # 中等知识点 35% 题量
    "strong": 0.15,     # 掌握知识点 15% 题量
}

# 掌握度 → 目标难度
MASTERY_TO_DIFFICULTY = {
    "weak": 0.4,        # 薄弱 → 基础题，先打牢基础
    "medium": 0.6,      # 中等 → 中等难度
    "strong": 0.8,      # 掌握 → 提高题，挑战极限
}

VALID_TYPES = list(TYPE_RATIOS.keys())


def determine_group(mastery: float) -> str:
    """根据掌握度确定分组。"""
    if mastery < 0.4:
        return "weak"
    if mastery < 0.7:
        return "medium"
    return "strong"


def distribute_questions(
    syllabus: Syllabus,
    weakness: WeaknessReport,
    total_count: int,
    types: list[str],
) -> list[Question]:
    """分配题目到各知识点和题型。"""
    masteries = weakness.topic_masteries
    all_topics = syllabus.all_topics()

    # 按掌握度分组
    groups: dict[str, list] = {"weak": [], "medium": [], "strong": []}
    for topic in all_topics:
        mastery = masteries.get(topic.name, 0.5)
        group = determine_group(mastery)
        groups[group].append((topic, mastery))

    # 计算各组题量
    questions: list[Question] = []
    qid_counter = 0

    # 归一化题型比例（只使用用户指定的题型）
    active_types = [t for t in types if t in TYPE_RATIOS]
    if not active_types:
        active_types = VALID_TYPES
    type_weight_sum = sum(TYPE_RATIOS[t] for t in active_types)

    for group_name in ["weak", "medium", "strong"]:
        group_topics = groups[group_name]
        if not group_topics:
            continue

        group_count = int(total_count * GROUP_RATIOS[group_name])
        if group_count == 0:
            continue

        target_difficulty = MASTERY_TO_DIFFICULTY[group_name]

        # 在组内按知识点权重分配题量
        total_weight = sum(t.weight for t, _ in group_topics)
        if total_weight == 0:
            total_weight = len(group_topics)

        for topic, mastery in group_topics:
            topic_share = topic.weight / total_weight
            topic_count = max(1, int(group_count * topic_share))

            # 在该知识点内分配题型
            for qtype in active_types:
                type_ratio = TYPE_RATIOS[qtype] / type_weight_sum
                type_count = max(1, int(topic_count * type_ratio))

                for _ in range(type_count):
                    qid_counter += 1
                    q = Question(
                        qid=f"Q{qid_counter:04d}",
                        qtype=qtype,
                        topic=topic.name,
                        difficulty=round(target_difficulty, 2),
                        stem="",          # 需模型生成
                        options=[],       # 需模型生成
                        answer="",        # 需模型生成
                        explanation="",   # 需模型生成
                        needs_model=True,
                    )
                    questions.append(q)

    return questions


def generate_model_prompt(question: Question, syllabus: Syllabus) -> str:
    """为单道题生成模型填充提示词。

    模型应根据知识点、题型、难度生成题干、选项、答案和解析。
    """
    topic = question.topic
    qtype = question.qtype
    diff = question.difficulty

    type_desc = {
        "choice": "选择题（4 个选项 A/B/C/D，单选）",
        "fill": "填空题（1-3 个空）",
        "short": "简答题（要求条理清晰、要点完整）",
        "application": "应用题/计算题（结合实际场景）",
        "true_false": "判断题（判断对错并说明理由）",
    }.get(qtype, qtype)

    difficulty_desc = {
        (0.0, 0.4): "基础难度，考查基本概念和定义",
        (0.4, 0.7): "中等难度，考查理解和应用",
        (0.7, 1.1): "较高难度，考查综合分析和灵活运用",
    }
    diff_label = "中等难度"
    for (lo, hi), label in difficulty_desc.items():
        if lo <= diff < hi:
            diff_label = label
            break

    return (
        f"请为知识点「{topic}」生成一道{type_desc}。\n"
        f"难度要求: {diff_label}（难度系数 {diff}）\n"
        f"课程: {syllabus.course_name}\n"
        f"要求:\n"
        f"  - 题目内容原创，不抄袭真实考试题\n"
        f"  - 答案准确，解析清晰\n"
        f"  - 输出 JSON 格式: "
        f'{{"stem": "...", "options": ["A...", "B...", ...], '
        f'"answer": "...", "explanation": "..."}}\n'
        f"  - 选择题 options 为 4 个选项，其他题型 options 为空数组"
    )


def generate_quiz(
    syllabus: Syllabus,
    weakness: WeaknessReport,
    total_count: int = 20,
    types: list[str] | None = None,
) -> Quiz:
    """生成习题集。"""
    if types is None:
        types = VALID_TYPES

    questions = distribute_questions(syllabus, weakness, total_count, types)

    # 为每道题附加模型生成提示词（存入 explanation 字段临时位置不合适，
    # 单独输出 prompt 字段供模型使用）
    for q in questions:
        q.explanation = generate_model_prompt(q, syllabus)

    return Quiz(
        course_name=syllabus.course_name,
        questions=questions,
        total_count=len(questions),
        created_at=datetime.now().isoformat(),
    )


def main():
    parser = argparse.ArgumentParser(description="生成自测习题")
    parser.add_argument("--syllabus", required=True, help="syllabus.json 路径")
    parser.add_argument("--weakness", required=True, help="weakness.json 路径")
    parser.add_argument("--types", default="choice,fill,short,application,true_false",
                        help=f"题型（逗号分隔，可选: {','.join(VALID_TYPES)}）")
    parser.add_argument("--count", type=int, default=20, help="总题量（默认 20）")
    parser.add_argument("--output", "-o", default="quiz.json", help="输出路径")
    args = parser.parse_args()

    try:
        syllabus = load_syllabus(args.syllabus)
        weakness = load_weakness(args.weakness)
        types = [t.strip() for t in args.types.split(",") if t.strip()]

        # 校验题型
        invalid = [t for t in types if t not in VALID_TYPES]
        if invalid:
            print(f"[失败] 无效题型: {invalid}，可选: {VALID_TYPES}", file=sys.stderr)
            sys.exit(1)

        quiz = generate_quiz(syllabus, weakness, args.count, types)
        quiz.to_json(args.output)

        # 统计
        type_counts = {}
        for q in quiz.questions:
            type_counts[q.qtype] = type_counts.get(q.qtype, 0) + 1

        print(f"[成功] 课程: {quiz.course_name}")
        print(f"  总题数: {quiz.total_count}")
        print(f"  题型分布: {type_counts}")
        print(f"  输出: {args.output}")
        print(f"  注意: 题目内容需模型生成，每题 explanation 字段含生成提示词")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
