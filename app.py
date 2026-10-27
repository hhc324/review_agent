import streamlit as st
import subprocess
import json
import os

st.set_page_config(page_title="自适应复习助手", layout="wide")
st.title("📖 自适应考试复习Agent")

menu = st.sidebar.selectbox("功能菜单", ["解析大纲", "薄弱评估", "生成复习计划", "背诵提纲", "自测刷题", "调整复习计划"])

if menu == "解析大纲":
    st.subheader("1. 上传课程大纲 syllabus.json")
    upload_file = st.file_uploader("上传 syllabus.json", type="json")
    if upload_file and st.button("开始解析"):
        with open("syllabus.json", "wb") as f:
            f.write(upload_file.read())
        res = subprocess.run(["python", "parse_syllabus.py", "--input", "syllabus.json"], capture_output=True, text=True)
        st.code(res.stdout + "\n" + res.stderr)

elif menu == "薄弱评估":
    st.subheader("2. 评估薄弱知识点")
    if st.button("运行评估"):
        res = subprocess.run(["python", "assess_weakness.py", "--syllabus", "syllabus.json"], capture_output=True, text=True)
        st.code(res.stdout + "\n" + res.stderr)

elif menu == "生成复习计划":
    st.subheader("3. 生成复习计划 plan.json")
    if st.button("生成计划"):
        try:
            res = subprocess.run(
                ["python", "generate_plan.py", "--syllabus", "syllabus.json", "--weakness", "weakness.json", "--days", "14", "--daily-minutes", "28"],
                capture_output=True,
                text=True,
                timeout=15
            )
            st.code(res.stdout + "\n" + res.stderr)
        except subprocess.TimeoutExpired:
            st.error("执行超时！")

elif menu == "背诵提纲":
    st.subheader("4. 生成背诵提纲")
    st.write("点击下方按钮生成Markdown背诵提纲")
    btn_outline = st.button("生成提纲")
    if btn_outline:
        try:
            res = subprocess.run(
                ["python", "generate_outline.py", "--syllabus", "syllabus.json", "--weakness", "weakness.json"],
                capture_output=True,
                text=True,
                timeout=15
            )
            st.success("✅ 提纲生成成功，已输出 outline.md")
            st.code(res.stdout + "\n" + res.stderr)
        except subprocess.TimeoutExpired:
            st.error("超时，脚本等待输入，请先在PowerShell手动测试！")

elif menu == "自测刷题":
    st.subheader("5. 生成自测习题")
    if st.button("生成习题"):
        try:
            res = subprocess.run(
                ["python", "generate_quiz.py", "--syllabus", "syllabus.json", "--weakness", "weakness.json"],
                capture_output=True,
                text=True,
                timeout=15
            )
            st.code(res.stdout + "\n" + res.stderr)
        except subprocess.TimeoutExpired:
            st.error("执行超时！")

elif menu == "调整复习计划":
    st.subheader("6. 根据反馈调整复习计划")
    if st.button("调整计划"):
        try:
            res = subprocess.run(
                ["python", "adjust_plan.py", "--plan", "plan.json", "--feedback", "weakness.json"],
                capture_output=True,
                text=True,
                timeout=15
            )
            st.code(res.stdout + "\n" + res.stderr)
        except subprocess.TimeoutExpired:
            st.error("执行超时！")