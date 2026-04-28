# 🧠 bluelab-clinical-tools

**Practical tools for clinical research workflows**

> Building small, usable, and AI-powered tools for real-world clinical operations.
> 让临床研究，从“做项目”变成“用工具”。

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

Tools for clinical data management documentation.

- CRF (Case Report Form) Completion Guideline Draft Generator（CRF填写指南初稿生成工具）  
- DMP (Data Management Plan) Draft Generator（DMP初稿生成工具）  
- DVP (Data Validation Plan) Draft Generator（DVP初稿生成工具）  

👉 [`/data-management`](./data-management)

---

### 🟢 Statistical Analysis（统计分析）

Tools supporting statistical planning and analysis workflows.

- SAP (Statistical Analysis Plan) Draft Generator（SAP正文初稿生成工具）  
- TFL (Tables, Figures, Listings) Shell Generator（TFL shell初稿生成工具）  
- TFL Shell Quality Check Tool（TFL shell漏项检测与预警工具）  
  (AI-assisted validation for completeness, missing sections, and structure issues)

👉 [`/stat-analysis`](./stat-analysis)

---

### 🟠 TFL / CSR Reporting Automation（统计分析 / 临床研究报告自动起草助手）

Tools for statistical output generation and reporting automation.

- TFL → CSR (Clinical Study Report) Results Draft Generator（基于TFL生成CSR结果段落初稿工具）  
- Automated TFL Generation Pipeline (SAS + AI-assisted workflow)（基于SAS与AI的TFL自动生成工具，Demo版本）  

👉 [`/report-automation`](./report-automation)

---

### 🟣 Medical Writing（医学助手）

Tools assisting medical and scientific writing workflows.

- Structured Literature Summary Generator（文献结构化摘要生成工具）  
- Evidence Table Generator（证据表生成工具）  
  (Structured comparison of study design, population, interventions, outcomes, and results)  
- Review & Meta-analysis Assistance Tool（综述与Meta分析辅助工具）  

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

## ⚙️ Design Principles

- **Small and focused**  
  Each tool solves one clear problem.

- **Composable**  
  Tools can be combined into larger workflows.

- **Practical over perfect**  
  Prioritize usability in real-world scenarios.

- **Structured outputs**  
  Prefer JSON / tables / standardized formats.

- **AI as augmentation**  
  AI assists workflows but does not replace validation.

---

## 🔄 Workflow Pattern

Most tools follow a common pattern:

**Input → Structured Processing → Output → AI Enhancement → Deliverable**

**Examples:**

- Protocol → Structured JSON → SAP  
- Dataset → SAS → TFL → Report draft  
- Literature → Structured notes → Summary  

---

## 📦 Status

🚧 Active development

Modules may vary in maturity from prototype to internally usable tools.

---

## 🔒 Usage

This repository is intended for **internal use only**.

Do not distribute or reuse outside the organization without permission.

---

## 🧠 Vision

We focus on building **high-impact tools**, not platforms.

- Reduce repetitive work  
- Structure complex workflows  
- Make clinical processes programmable  

---

## 🤝 Contributing (Internal)

- Keep tools small and clearly scoped  
- Provide examples for every tool  
- Reuse shared skills and prompts  
- Avoid duplication across modules  
