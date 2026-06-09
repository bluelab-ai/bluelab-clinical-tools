# DMP 生成中断续传设计思路

## 1. 现状分析

### 当前流程

DMP 生成由 `dmp_orchestrator.py` 通过 `subprocess.Popen` 启动 Claude CLI 子进程，一次性执行完整工作流（阶段 0-9）。`start_dmp()` 入口始终调用 `clear_session()` 清空旧会话，从零开始。

```
用户点击 Generate DMP
  → start_dmp() → clear_session() → 构建 prompt → spawn Claude CLI
  → 阶段0 → 阶段1 → 阶段2 → 阶段3 → 阶段4 → 阶段5 → 阶段6 → 阶段7-9 → 完成
```

### 中断后果

Claude CLI 子进程一旦退出（浏览器关闭、网络断开、服务器重启、超时），所有进度丢失，用户必须从头开始。这在以下场景中体验极差：

- 用户在阶段 6（顺序确认门）中被问到第 4 个问题，刷新页面后需重新回答全部问题
- 语义审查（阶段 3）LLM 评审消耗数分钟，中断后重做浪费时间和 API 费用
- 协议 trace 构建（阶段 2）已生成完整结果，重启后重复执行无意义

### 各阶段产物与成本

| 阶段 | 产物 | 耗时 | 可恢复性 |
|------|------|------|----------|
| 0 规则准备 | 无 | 秒级 | 无需恢复 |
| 1 模板选择 | 无 | 秒级 | 无需恢复 |
| 2 构建 trace | `dmp_trace.json`, `protocol_dump.txt`, `dmp_questions.md` | 秒级 | **可复用** |
| 3a 审查准备 | `review_input.json` | 秒级 | **可复用** |
| 3b LLM 审查 | 修改 `review_input.json` | 分钟级 | **昂贵，需恢复** |
| 3c 审查应用 | 更新 `dmp_trace.json` | 秒级 | **需从 3b 结果恢复** |
| 4 交叉检查 | 无持久化产物 | 秒级 | 需重做（便宜） |
| 5 模板填充 | `DMP初稿.docx`, `DMP生成报告.md` | 秒级 | 幂等，可重跑 |
| 6 顺序确认门 | 逐步用户回答 | 分钟级 | **用户状态需恢复** |
| 7-9 QA/披露 | 无 | 秒级 | 需重做（便宜） |

关键结论：**阶段 2-3 的脚本产物和阶段 6 的用户回答状态是恢复的核心。**

---

## 2. 中断场景分类

### 场景 A：脚本执行中中断（阶段 2/3a/3c/5）

子进程在执行 `build_dmp_trace.py` 或 `review_trace.py` 等脚本时被 kill。已写入磁盘的产物完整可用。

**恢复策略**：检测已有产物 → 跳过已完成阶段 → 从下一阶段继续

### 场景 B：LLM 审查中中断（阶段 3b）

Claude 正在逐字段审查 `review_input.json`，已写入部分 review_decision。文件处于半完成状态。

**恢复策略**：检测 `review_input.json` 中的未完成字段 → 重新发起审查（仅审查未完成字段）

### 场景 C：用户交互中中断（阶段 1/4b/6）

用户正在回答弹窗问题。部分问题已回答并更新到 trace，部分未回答。

**恢复策略**：从 trace 中识别已确认/未确认项 → 从当前问题继续

### 场景 D：生成完成后的中断

`DMP初稿.docx` 已生成，用户在 QA 阶段中断。已有初稿在磁盘。

**恢复策略**：直接返回已有初稿，或仅重跑 QA

---

## 3. 核心设计

### 3.1 进度文件 `dmp_progress.json`

在项目目录下维护一个轻量进度文件：

```json
{
  "session_id": "uuid",
  "status": "in_progress",
  "current_stage": "3b",
  "completed_stages": ["0", "1", "2", "3a"],
  "stage_3b_progress": {
    "total_fields": 12,
    "reviewed_fields": 5
  },
  "stage_6_progress": {
    "total_pending": 4,
    "resolved": 2,
    "last_question_index": 2
  },
  "user_answers": [
    {"question": "模板选择", "answer": "随机系统", "timestamp": "..."},
    {"question": "样本量确认", "answer": "205例", "timestamp": "..."}
  ],
  "artifacts": {
    "dmp_trace.json": "2026-06-01T14:30:00",
    "protocol_dump.txt": "2026-06-01T14:30:00",
    "review_input.json": "2026-06-01T14:32:00",
    "DMP初稿.docx": null
  },
  "error_info": null
}
```

### 3.2 阶段推断（Artifact-based）

即使进度文件丢失，也可从已有产物推断可恢复的阶段：

```
存在 dmp_trace.json          → 阶段 2 已完成
存在 review_input.json       → 阶段 3a 已完成
review_input.json 无未决字段  → 阶段 3b 已完成
review_input.json 有未决字段  → 阶段 3b 部分完成（需重审）
存在 DMP初稿.docx            → 阶段 5 已完成
```

### 3.3 Claude CLI 侧改动

Claude CLI 子进程在 prompt 中收到**阶段跳过指令**。在 prompt 构建时注入：

```
===== RESUME CONTEXT =====
上次会话在阶段 3a 完成后中断。以下产物已就绪：
- dmp_trace.json
- protocol_dump.txt
- review_input.json（已生成，但尚未开始 3b 审查）

请直接从阶段 3b 开始执行，跳过阶段 0-3a。
阶段 3b 时，先检查 review_input.json 中是否已有部分字段完成审查
（review_decision 非空），已完成字段无需重复审查。
==========================
```

### 3.4 前端改动

`ChatPage` 检测到项目目录存在 `dmp_progress.json` 且 `status != "completed"` 时：

- 显示「检测到未完成的 DMP 生成，是否从中断处继续？」
- 提供两个按钮：「继续生成」/「重新开始」
- 「继续生成」调用 `POST /api/{project}/start-dmp?resume=true`

---

## 4. 续传流程

```
用户点击「继续生成」
  → Frontend: POST /start-dmp?resume=true
  → Orchestrator:
      1. 读取 dmp_progress.json
      2. 验证产物文件是否存在且完整
      3. 推断当前应从哪个阶段继续
      4. 构建 RESUME CONTEXT prompt 片段
      5. spawn Claude CLI（不 clear_session，复用已加载上下文）
      6. Claude CLI 读取 RESUME CONTEXT → 跳过已完成阶段
      7. Claude CLI 写 [STAGE] 行 → Orchestrator 更新进度文件
      8. 完成后标记 status=completed
```

### 状态机

```
                    ┌──────────┐
       start_dmp()  │  fresh   │
         ─────────→ │          │
                    └────┬─────┘
                         │ 阶段2完成
                         ▼
                    ┌──────────┐
                    │ stage_2  │◄────  resume（检测到 trace 存在）
                    └────┬─────┘
                         │ 阶段3a完成
                         ▼
                    ┌──────────┐
                    │ stage_3a │◄────  resume（检测到 review_input 存在）
                    └────┬─────┘
                         │ 阶段3b完成
                         ▼
                    ┌──────────┐
                    │ stage_3b │◄────  resume（review_input 部分完成 → 重审未决字段）
                    └────┬─────┘
                         │ 阶段3c完成
                         ▼
                    ┌──────────┐
                    │ stage_5  │◄────  resume（重新 apply_template，幂等）
                    └────┬─────┘
                         │ 阶段5完成
                         ▼
                    ┌──────────┐
                    │ stage_6  │◄────  resume（从 dmp_progress.user_answers 恢复已答问题）
                    └────┬─────┘
                         │ 全部完成
                         ▼
                    ┌──────────┐
                    │completed │
                    └──────────┘
```

---

## 5. 需修改的文件

### 后端

| 文件 | 改动内容 |
|------|----------|
| `backend/app/services/dmp_orchestrator.py` | 新增 `_build_resume_prompt()`、`_infer_stage()`、`_read_progress()`、`_write_progress()`；修改 `start_dmp()` 支持 `resume` 参数；修改 SSE 流中解析 `[STAGE]` 行时同步更新进度文件 |
| `backend/app/routers/chat.py` | `start_dmp` 路由新增 `resume` 查询参数 |

### 前端

| 文件 | 改动内容 |
|------|----------|
| `frontend/src/pages/ChatPage.tsx` | 检测未完成会话 → 显示续传提示 → 调用带 `resume=true` 的 API |
| `frontend/src/services/api.ts` | `startDMP()` 支持 `resume` 参数 |

### Skill

| 文件 | 改动内容 |
|------|----------|
| `.claude/skills/protocol-to-dmp/SKILL.md` | 新增阶段 0 的 RESUME CONTEXT 解析指令；Claude 在每阶段完成时输出带进度的 `[STAGE]` 行 |

---

## 6. 关键实现细节

### 6.1 `[STAGE]` 解析增强

当前 Orchestrator 已能解析 `[STAGE]` 行用于 SSE 推送。续传功能需在此基础上提取阶段号，更新进度文件：

```python
# _write_progress 在收到 [STAGE] 时调用
def _update_progress_from_stage(stage_line: str, progress: dict):
    match = re.match(r".*阶段\s*(\d+[a-z]?).*完成.*", stage_line)
    if match:
        stage = match.group(1)
        progress["completed_stages"].append(stage)
        progress["current_stage"] = _next_stage(stage)
        _write_progress(progress)
```

### 6.2 阶段 3b 部分恢复

最复杂的恢复场景。策略：

```
1. 读取 review_input.json
2. 检查每个 review item 的 review_decision：
   - 已填 → 跳过（已审查）
   - 空 → 加入「待审查列表」
3. 在 prompt 中注入：只审查以下字段：[列出待审查字段]
4. review_input.json 中的已审查字段保持不变
```

### 6.3 阶段 6 用户回答恢复

```
1. 从 dmp_progress.json 读取 user_answers 列表
2. 在 RESUME CONTEXT 中注入已回答的问题和答案
3. Claude prompt 中指明：以下问题已确认，无需再问
4. 从 dmp_trace.json 中识别仍为 uncertain/missing 的项
5. 继续顺序确认门
```

### 6.4 会话生命周期

进度文件在以下时机清理：

| 事件 | 操作 |
|------|------|
| 用户点击「重新开始」 | 删除 `dmp_progress.json` |
| 生成完成 | 标记 `status: "completed"`，保留文件备查 |
| 超时（24h 无活动） | 标记 `status: "stale"`，前端提示是否继续或重新开始 |
| 新协议/DM日志上传 | 检测产物过期 → 提示用户重新开始 |

### 6.5 安全性

- 进度文件限写在工作区项目目录下，遵循现有的 `safe_path()` 沙箱
- `resume=true` 仅在存在有效进度文件时生效，否则返回错误
- 进度文件不得被用户直接通过 API 修改

---

## 7. 边界情况

| 边界情况 | 处理 |
|----------|------|
| 进度文件存在但产物被手动删除 | 阶段推断回退到最早可用产物的阶段 |
| 进度文件损坏 | 从产物推断阶段（降级恢复） |
| 协议文件已更新 | 产物过期，提示用户重新开始 |
| DM 日志已更新 | 若 trace 基于旧 DM 日志，提示重新开始 |
| 同一项目多次同时生成 | `_acquire_session` 已有锁保护，返回 is_resume=true |

---

## 8. 实现优先级

考虑到投入产出比，建议分阶段实现：

**P0（核心体验改善）：**
- 产物检测 + 阶段推断
- 阶段 2 产物复用（跳过 trace 构建）
- 阶段 5 幂等重跑（跳过审查直接生成初稿，适用于只需改模板配置的场景）

**P1（完整续传）：**
- 阶段 3b 部分恢复（重审未决字段）
- 阶段 6 用户回答恢复
- 前端续传提示 UI

**P2（健壮性增强）：**
- 超时自动标记 stale
- 产物过期检测
- 进度文件自动备份
