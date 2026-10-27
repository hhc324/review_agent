#!/usr/bin/env python3
"""背诵提纲生成脚本。

输入:
  - syllabus.json（必需）
  - weakness.json（必需）

输出: outline.md（Markdown 格式背诵提纲）

提纲按章节组织，标注：
  - 掌握等级：⚠️ 薄弱 / ◯ 中等 / ✓ 掌握
  - 重要性：★ 核心 / ● 重点 / ○ 了解
  - 难度与权重信息

用法:
  python generate_outline.py --syllabus syllabus.json --weakness weakness.json --output outline.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import Syllabus, WeaknessReport, load_syllabus, load_weakness


# 掌握等级标记
MASTERY_MARKS = {
    "weak": "⚠️ 薄弱",
    "medium": "◯ 中等",
    "strong": "✓ 掌握",
    "unknown": "? 未评估",
}

# 重要性标记
IMPORTANCE_MARKS = {
    "core": "★ 核心",
    "important": "● 重点",
    "normal": "○ 一般",
    "optional": "▽ 选学",
}


def mastery_level(mastery: float) -> str:
    """根据掌握度返回等级。"""
    if mastery < 0:
        return "unknown"
    if mastery < 0.4:
        return "weak"
    if mastery < 0.7:
        return "medium"
    return "strong"


def generate_outline(syllabus: Syllabus, weakness: WeaknessReport) -> str:
    """生成背诵提纲 Markdown 文本。"""
    masteries = weakness.topic_masteries
    lines: list[str] = []

    # 标题
    lines.append(f"# {syllabus.course_name} — 期末复习背诵提纲")
    lines.append("")
    lines.append(f"> {weakness.summary}")
    lines.append("")

    # 图例
    lines.append("## 图例说明")
    lines.append("")
    lines.append("| 标记 | 含义 |")
    lines.append("|------|------|")
    lines.append("| ⚠️ | 薄弱知识点（掌握度 < 0.4），需重点攻克 |")
    lines.append("| ◯  | 中等掌握（0.4 - 0.7），需巩固 |")
    lines.append("| ✓  | 已掌握（≥ 0.7），保持即可 |")
    lines.append("| ★  | 核心知识点 |")
    lines.append("| ●  | 重点知识点 |")
    lines.append("| ○  | 一般知识点 |")
    lines.append("| ▽  | 选学知识点 |")
    lines.append("")

    # 统计概览
    total = len(masteries)
    weak_count = len(weakness.weak_topics)
    medium_count = len(weakness.medium_topics)
    strong_count = len(weakness.strong_topics)
    lines.append("## 概览统计")
    lines.append("")
    lines.append(f"- 知识点总数: **{total}**")
    lines.append(f"- ⚠️ 薄弱: **{weak_count}** ({weak_count/max(total,1)*100:.0f}%)")
    lines.append(f"- ◯ 中等: **{medium_count}** ({medium_count/max(total,1)*100:.0f}%)")
    lines.append(f"- ✓ 掌握: **{strong_count}** ({strong_count/max(total,1)*100:.0f}%)")
    lines.append("")

    # 薄弱知识点速查（优先展示）
    if weakness.weak_topics:
        lines.append("## 🔴 薄弱知识点速查（复习优先级最高）")
        lines.append("")
        for name in weakness.weak_topics:
            m = masteries.get(name, 0)
            lines.append(f"- [ ] **{name}** (掌握度: {m:.2f})")
        lines.append("")

    # 按章节组织详细提纲
    lines.append("## 详细提纲（按章节）")
    lines.append("")

    for ch_idx, chapter in enumerate(syllabus.chapters, 1):
        lines.append(f"### 第 {ch_idx} 章 {chapter.name}")
        if chapter.description:
            lines.append(f"> {chapter.description}")
        lines.append("")

        if not chapter.topics:
            lines.append("（本章无具体知识点）")
            lines.append("")
            continue

        for topic in chapter.topics:
            mastery = masteries.get(topic.name, -1.0)
            m_level = mastery_level(mastery)
            m_mark = MASTERY_MARKS[m_level]
            i_mark = IMPORTANCE_MARKS.get(topic.importance, "○ 一般")

            # 知识点标题行
            mastery_str = f"{mastery:.2f}" if mastery >= 0 else "未评估"
            lines.append(
                f"- **{topic.name}** "
                f"[{m_mark}] [{i_mark}] "
                f"(难度: {topic.difficulty:.1f} | 权重: {topic.weight:.1f} | "
                f"掌握度: {mastery_str})"
            )

            # 描述
            if topic.description:
                lines.append(f"  - {topic.description}")

            # 依赖关系
            if topic.dependencies:
                lines.append(f"  - 前置依赖: {', '.join(topic.dependencies)}")

            # 关键词
            if topic.keywords:
                lines.append(f"  - 关键词: {', '.join(topic.keywords)}")

        lines.append("")

    # 复习建议
    lines.append("## 复习建议")
    lines.append("")
    if weakness.weak_topics:
        lines.append(f"1. **优先攻克 {len(weakness.weak_topics)} 个薄弱知识点**，"
                     "建议每天分配 60% 复习时间")
    if weakness.medium_topics:
        lines.append(f"2. **巩固 {len(weakness.medium_topics)} 个中等知识点**，"
                     "通过练习题加深理解")
    if weakness.strong_topics:
        lines.append(f"3. **保持 {len(weakness.strong_topics)} 个已掌握知识点**，"
                     "定期快速回顾即可")
    lines.append("4. 使用 `generate_quiz.py` 生成自测习题检验复习效果")
    lines.append("5. 答题后使用 `adjust_plan.py` 动态调整复习计划")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成背诵提纲")
    parser.add_argument("--syllabus", required=True, help="syllabus.json 路径")
    parser.add_argument("--weakness", required=True, help="weakness.json 路径")
    parser.add_argument("--output", "-o", default="outline.md", help="输出路径")
    args = parser.parse_args()

    try:
        syllabus = load_syllabus(args.syllabus)
        weakness = load_weakness(args.weakness)

        outline = generate_outline(syllabus, weakness)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(outline)

        print(f"[成功] 课程: {syllabus.course_name}")
        print(f"  知识点: {syllabus.topic_count()}")
        print(f"  薄弱: {len(weakness.weak_topics)} | "
              f"中等: {len(weakness.medium_topics)} | "
              f"掌握: {len(weakness.strong_topics)}")
        print(f"  输出: {args.output}")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
