# GCP 2026 Training Web App — 部署文档

## 项目简介

一个基于 FastAPI 的 GCP（药物临床试验质量管理规范，2026年修订）培训 Web 应用。

功能：
- 逐条学习 54 条 GCP 法规条文（含白话解读）
- 章节测验 + 期末考试（题库随机抽题）
- AI 助教 Q&A（调用 DeepSeek API）
- 学习记录追踪 + 完成证书生成

---

## 1. 环境要求

- **Python 3.10+**
- pip

## 2. 部署步骤

### 2.1 解压并进入项目目录

```bash
cd GCP-2026-skill
```

### 2.2 安装依赖

```bash
pip install -r requirements.txt
```

依赖包：
| 包名 | 用途 |
|------|------|
| fastapi | Web 框架 |
| uvicorn | ASGI 服务器 |
| jinja2 | HTML 模板引擎 |
| anthropic | AI API 客户端（调用 DeepSeek 兼容接口） |
| python-multipart | 表单数据解析 |
| python-dotenv | 读取 .env 环境变量 |

### 2.3 配置环境变量

复制模板文件并修改：

```bash
cp .env.example .env
```

编辑 `.env`，填入你的配置：

```env
# 【必填】DeepSeek API Key — 用于 AI 助教功能
# 在 https://platform.deepseek.com/api_keys 获取
ANTHROPIC_API_KEY=sk-your-deepseek-api-key-here

# DeepSeek 的 Anthropic 兼容接口（一般不需要改）
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

# 模型名称（可选：deepseek-v4-pro / deepseek-chat 等）
ANTHROPIC_MODEL=deepseek-v4-pro

# 【必改】Session 加密密钥 — 生产环境请改为随机字符串
SESSION_SECRET=请改成你的随机字符串
```

> ⚠️ `SESSION_SECRET` 用于加密 Cookie 中的用户会话，**生产环境务必改掉默认值**。可以这样生成：`python -c "import secrets; print(secrets.token_hex(32))"`

### 2.4 启动应用

**开发/测试：**
```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

**生产环境部署建议使用进程管理工具（如 systemd、supervisor、pm2）：**
```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000 --workers 4
```

启动后访问：`http://your-server-ip:8000`

### 2.5 验证部署

```bash
curl http://localhost:8000/health
# 返回: {"status":"ok"}
```

---

## 3. 目录结构说明

```
GCP-2026-skill/
├── web/                     # Web 应用主体
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置文件（路径、常量、环境变量）
│   ├── routes/              # 路由模块
│   │   ├── entry.py         # 入口页（选择角色/分支）
│   │   ├── learn.py         # 学习页（条文阅读）
│   │   ├── quiz.py          # 测验页
│   │   ├── exam.py          # 考试页
│   │   ├── cert.py          # 证书页
│   │   └── ask.py           # AI 助教 API
│   ├── templates/           # Jinja2 模板
│   ├── static/              # CSS/JS 静态文件
│   ├── article_parser.py    # 条文解析
│   ├── record_manager.py    # 学习记录管理
│   └── user_manager.py      # 用户管理
├── content/
│   ├── articles/            # 54 条法规条文 + scene 插图
│   └── diff-guide.md        # 新旧版差异指南
├── curriculum/              # 课程大纲 (6章)
├── exams/
│   ├── bank.json            # 题库
│   └── *-rules.json         # 考试规则
├── scripts/                 # 辅助脚本
├── assets/                  # 静态资源（证书模板等）
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
└── DEPLOY.md                # 本文档
```

## 4. 运行时生成目录（无需手动创建）

这些目录会在应用运行时自动创建，用户数据存储在这里：

- `web/users/` — 用户账户和角色数据
- `web/certs/` — 生成的完成证书 HTML
- `.training-records/` — 旧版学习记录（兼容）

---

## 5. FAQ

**Q: 如果没有 DeepSeek API Key，AI 助教功能怎么办？**
A: AI 助教功能会返回提示信息，告知功能不可用。其他功能（学习、测验、考试、证书）不受影响。

**Q: 如何切换其他 AI 模型（如直接使用 Anthropic Claude）？**
A: 修改 `.env` 中的 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`，例如：
```env
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-4-6
```

**Q: 如何修改考试规则？**
A: 编辑 `exams/chapter-quiz-rules.json`（章节测验）和 `exams/final-exam-rules.json`（期末考试）。

**Q: 如何重新生成 SSL 证书或 Nginx 反向代理？**
A: 如需配置 HTTPS，建议使用 Nginx 反向代理 + Let's Encrypt：
```nginx
server {
    listen 80;
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```



