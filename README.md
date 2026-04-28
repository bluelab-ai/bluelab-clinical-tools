# 🧠 bluelab-clinical-tools

**Practical tools for clinical research workflows**

> Building small, usable, and AI-powered tools for real-world clinical operations.

---

## 🔍 Overview

This repository contains a curated collection of lightweight tools designed to improve efficiency across clinical trial workflows, including:

- Data management  
- Statistical analysis  
- Reporting automation  
- Medical writing  

Each tool is designed to be **practical, reusable, and composable**.

---

## 🧩 Modules

Each module focuses on a specific area of clinical research.  
Click into each directory for detailed tools and examples.

---

### 🔵 Data Management（数据管理文档生成助手）

Tools for clinical data workflows and documentation.

- DMP / DVP / CRF填写指南初稿自动生成  
- Structured data extraction  
- Data-related document generation  

👉 [`/data-management`](./data-management)

---

### 🟢 Statistical Analysis（SAP骨架生成助手）

Tools supporting statistical planning and analysis workflows.

- SAP目录骨架 / TFL shell建议 / 漏项提示  
- SAP skeleton generation  
- Analysis workflow support  

👉 [`/stat-analysis`](./stat-analysis)

---

### 🟠 Reporting Automation（统计报告自动起草助手）

Tools for generating statistical outputs and report drafts.

- 保留原方向：调用SAS程序 → 自动产出TFL → 生成结果段描述初稿  
- TFL generation via SAS integration  
- AI-assisted interpretation of outputs  

👉 [`/report-automation`](./report-automation)

---

### 🟣 Medical Writing（医学助手）

Tools assisting medical and scientific writing workflows.

- 文献结构化摘要 / 证据表 / 综述与Meta辅助  
- Literature structuring  
- Evidence summarization  

👉 [`/medical-writing`](./medical-writing)

---

## 🏗️ Repository Structure

```text
bluelab-clinical-tools/
│
├── data-management/
├── stat-analysis/
├── report-automation/
├── medical-writing/
│
├── shared/
│   ├── skills/
│   ├── prompts/
│   ├── workflows/
│   └── utils/
│
├── docs/
└── README.md
