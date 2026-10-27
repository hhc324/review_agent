#!/usr/bin/env python3
"""课程大纲解析脚本。

支持三种输入格式：
  1. JSON  — 直接结构化大纲
  2. Markdown — 解析标题层级与列表项
  3. 纯文本 — 按行启发式解析

输出: syllabus.json

用法:
  python parse_syllabus.py --input syllabus.md --output syllabus.json
  python parse_syllabus.py --input syllabus.json --output syllabus.json
  python parse_syllabus.py --text "课程名: 高等数学\\n第一章 极限\\n- 数列极限" --output syllabus.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import Syllabus, Chapter, Topic


# 重要性关键词 → importance 映射
IMPORTANCE_KEYWORDS = {
    "重点掌握": "core",
    "核心": "core",
    "熟练掌握": "core",
    "掌握": "important",
    "重点": "important",
    "理解": "important",
    "了解": "normal",
    "认识": "normal",
    "知道": "optional",
    "选学": "optional",
    "拓展": "optional",
}

# 权重关键词 → 数值
WEIGHT_PATTERN = re.compile(r"(?:权重|weight)[:：\s]*([0-9.]+)", re.IGNORECASE)
# 难度关键词
DIFFICULTY_PATTERN = re.compile(r"(?:难度|difficulty)[:：\s]*([0-9.]+)", re.IGNORECASE)
# 依赖关键词
DEPENDENCY_PATTERN = re.compile(r"(?:依赖|前置|depends)[:：\s]*(.+)", re.IGNORECASE)


def detect_format(content: str) -> str:
    """检测输入格式。"""
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return "json"
    if re.search(r"^#{1,6}\s", stripped, re.MULTILINE):
        return "markdown"
    return "text"


def parse_json(content: str) -> Syllabus:
    """解析 JSON 格式大纲。"""
    data = json.loads(content)
    return Syllabus.from_dict(data)


def _extract_importance(text: str) -> tuple[str, float]:
    """从文本提取重要性等级和权重。"""
    importance = "normal"
    for keyword, level in IMPORTANCE_KEYWORDS.items():
        if keyword in text:
            importance = level
            break

    weight = 1.0
    if importance == "core":
        weight = 3.0
    elif importance == "important":
        weight = 2.0
    elif importance == "optional":
        weight = 0.5

    m = WEIGHT_PATTERN.search(text)
    if m:
        try:
            weight = float(m.group(1))
        except ValueError:
            pass

    return importance, weight


def _extract_difficulty(text: str) -> float:
    """从文本提取难度。"""
    m = DIFFICULTY_PATTERN.search(text)
    if m:
        try:
            val = float(m.group(1))
            return max(0.0, min(1.0, val))
        except ValueError:
            pass
    # 启发式：包含"难/复杂/高级" → 高难度
    if any(k in text for k in ["难", "复杂", "高级", "深入"]):
        return 0.8
    if any(k in text for k in ["易", "简单", "基础", "初步"]):
        return 0.3
    return 0.5


def _extract_dependencies(text: str) -> list[str]:
    """提取依赖知识点。"""
    m = DEPENDENCY_PATTERN.search(text)
    if m:
        deps = [d.strip() for d in re.split(r"[,，;；、]", m.group(1)) if d.strip()]
        return deps
    return []


def _clean_topic_name(text: str) -> str:
    """清理知识点名称，去除标记符号。"""
    # 去除列表标记
    text = re.sub(r"^[-*•·]\s*", "", text)
    # 去除数字编号
    text = re.sub(r"^\d+[.、)]\s*", "", text)
    # 去除行尾权重/难度标注
    text = re.sub(r"\s*[（(].*?[)）]\s*$", "", text)
    return text.strip()


def parse_markdown(content: str) -> Syllabus:
    """解析 Markdown 格式大纲。"""
    lines = content.split("\n")
    course_name = "未命名课程"
    chapters: list[Chapter] = []
    current_chapter: Chapter | None = None
    current_topic: Topic | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 一级标题 → 课程名
        if stripped.startswith("# ") and not stripped.startswith("## "):
            course_name = stripped[2:].strip()
            continue

        # 二级标题 → 章节
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if current_chapter:
                chapters.append(current_chapter)
            ch_name = stripped[3:].strip()
            imp, w = _extract_importance(ch_name)
            current_chapter = Chapter(name=re.sub(WEIGHT_PATTERN, "", ch_name).strip(),
                                      weight=w, description="")
            current_topic = None
            continue

        # 三级标题 → 子章节（作为知识点组，也可视为知识点）
        if stripped.startswith("### "):
            topic_name = _clean_topic_name(stripped[4:])
            if current_chapter:
                imp, w = _extract_importance(stripped)
                diff = _extract_difficulty(stripped)
                deps = _extract_dependencies(stripped)
                current_topic = Topic(
                    name=topic_name,
                    difficulty=diff,
                    weight=w,
                    dependencies=deps,
                    importance=imp,
                )
                current_chapter.topics.append(current_topic)
            continue

        # 列表项 → 知识点
        if re.match(r"^[-*•·]\s+", stripped) or re.match(r"^\d+[.、)]\s+", stripped):
            topic_name = _clean_topic_name(stripped)
            if not topic_name:
                continue
            if current_chapter is None:
                current_chapter = Chapter(name="默认章节")
                chapters.append(current_chapter)
            imp, w = _extract_importance(stripped)
            diff = _extract_difficulty(stripped)
            deps = _extract_dependencies(stripped)
            topic = Topic(
                name=topic_name,
                difficulty=diff,
                weight=w,
                dependencies=deps,
                importance=imp,
            )
            current_chapter.topics.append(topic)
            current_topic = topic
            continue

        # 普通文本行 → 作为描述附加到当前知识点
        if current_topic and stripped:
            if not current_topic.description:
                current_topic.description = stripped
            else:
                current_topic.description += " " + stripped

    if current_chapter:
        chapters.append(current_chapter)

    return Syllabus(course_name=course_name, chapters=chapters,
                    metadata={"source_format": "markdown"})


def parse_text(content: str) -> Syllabus:
    """解析纯文本格式大纲（启发式）。"""
    lines = content.split("\n")
    course_name = "未命名课程"
    chapters: list[Chapter] = []
    current_chapter: Chapter | None = None

    chapter_patterns = [
        re.compile(r"^第[一二三四五六七八九十\d]+[章节单元部分]\s*(.*)"),
        re.compile(r"^(?:Chapter|Unit|Part)\s+\d+[:：\s]*(.*)", re.IGNORECASE),
        re.compile(r"^[一二三四五六七八九十]+[、.]\s*(.*)"),
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 课程名
        if not chapters and not current_chapter:
            if stripped.startswith("课程") or stripped.startswith("科目"):
                course_name = re.sub(r"^课程[名]?[:：\s]*", "", stripped)
                course_name = re.sub(r"^科目[名]?[:：\s]*", "", course_name)
                continue
            # 第一行若不像章节，视为课程名
            if not any(p.match(stripped) for p in chapter_patterns):
                if not re.match(r"^[-*•·]", stripped):
                    course_name = stripped
                    continue

        # 章节标题
        matched_chapter = False
        for pattern in chapter_patterns:
            m = pattern.match(stripped)
            if m:
                if current_chapter:
                    chapters.append(current_chapter)
                ch_name = m.group(1).strip() or stripped
                current_chapter = Chapter(name=ch_name)
                matched_chapter = True
                break
        if matched_chapter:
            continue

        # 知识点（列表项或缩进行）
        is_topic_line = (
            re.match(r"^[-*•·]\s+", stripped)
            or re.match(r"^\d+[.、)]\s+", stripped)
            or (line.startswith(("  ", "\t")) and stripped)
        )
        if is_topic_line:
            topic_name = _clean_topic_name(stripped)
            if not topic_name:
                continue
            if current_chapter is None:
                current_chapter = Chapter(name="默认章节")
                chapters.append(current_chapter)
            imp, w = _extract_importance(stripped)
            diff = _extract_difficulty(stripped)
            deps = _extract_dependencies(stripped)
            current_chapter.topics.append(Topic(
                name=topic_name, difficulty=diff, weight=w,
                dependencies=deps, importance=imp,
            ))

    if current_chapter:
        chapters.append(current_chapter)

    if not chapters:
        # 无法识别结构，将整个内容作为一个章节
        all_topics = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("课程"):
                topic_name = _clean_topic_name(stripped)
                if topic_name:
                    all_topics.append(Topic(name=topic_name))
        if all_topics:
            chapters.append(Chapter(name="全部内容", topics=all_topics))

    return Syllabus(course_name=course_name, chapters=chapters,
                    metadata={"source_format": "text"})


def parse_syllabus(content: str, format_hint: str | None = None) -> Syllabus:
    """解析大纲内容，自动检测格式。"""
    fmt = format_hint or detect_format(content)
    if fmt == "json":
        return parse_json(content)
    elif fmt == "markdown":
        return parse_markdown(content)
    else:
        return parse_text(content)


def main():
    parser = argparse.ArgumentParser(description="解析课程大纲")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="大纲文件路径")
    group.add_argument("--text", help="大纲文本内容（内联）")
    parser.add_argument("--output", "-o", default="syllabus.json", help="输出文件路径")
    parser.add_argument("--format", choices=["json", "markdown", "text"],
                        help="强制指定格式")
    args = parser.parse_args()

    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = args.text

        syllabus = parse_syllabus(content, args.format)
        syllabus.to_json(args.output)

        topic_count = syllabus.topic_count()
        print(f"[成功] 课程: {syllabus.course_name}")
        print(f"  章节数: {len(syllabus.chapters)}")
        print(f"  知识点数: {topic_count}")
        print(f"  输出: {args.output}")

        if topic_count == 0:
            print("[警告] 未识别到任何知识点，请检查大纲格式")
            print("  参考文档: references/syllabus-format.md")

    except FileNotFoundError as e:
        print(f"[失败] 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[失败] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
