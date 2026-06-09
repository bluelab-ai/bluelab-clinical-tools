# Help Page Design

## Overview

Add a `/help` route with a static page that guides new users through the DMP platform workflow with screenshots and step-by-step instructions, plus a FAQ section.

## Routes & Entry Points

- New route: `/help` (ProtectedRoute, requires login)
- Entry points:
  - ChatPage header: `?` help button next to user workspace display
  - LogFormPage header: `?` help button next to user workspace display
- Both buttons navigate to `/help` via `useNavigate`

## Page Structure

Single scrollable static page at `src/pages/HelpPage.tsx`:

1. **Page title** — "使用帮助" with brief intro
2. **Step 1: 注册账号** — screenshot placeholder, registration form walkthrough
3. **Step 2: 登录系统** — screenshot placeholder, login walkthrough
4. **Step 3: 填写 DM 日志信息** — screenshot placeholder, field categories, conditional field explanation
5. **Step 4: 上传试验方案文件** — screenshot placeholder, drag-and-drop, format/size limits
6. **Step 5: 生成 DMP** — screenshot placeholder, prerequisites (log + protocol), button behavior
7. **Step 6: 与 AI 交互问答** — screenshot placeholder, question cards, session management
8. **FAQ** — 4 common questions with answers

### Screenshot Placeholder Pattern

Each screenshot uses a consistent placeholder:

```
<div className="border-2 border-dashed border-slate-300 rounded-xl bg-slate-50 flex items-center justify-center h-48">
  <p className="text-slate-400 text-sm">截图占位 — 替换为实际截图</p>
</div>
```

## Styling

- Consistent with existing pages (LogFormPage layout pattern)
- `max-w-2xl mx-auto` centered card layout
- White card (`bg-white rounded-2xl shadow-sm border border-slate-200/70`)
- Step numbers use blue circle badges
- FAQ uses bold question + paragraph answer pattern

## FAQ Content

1. **为什么 Generate DMP 按钮是灰色的？**
   Answer: 需要同时具备两个条件：已保存 DM 日志信息（在日志填写页面）且已上传试验方案文件（.docx 格式）。

2. **支持哪些文件格式和大小？**
   Answer: 仅支持 .docx 格式的试验方案文件，最大 50MB。

3. **如何切换项目？**
   Answer: 点击页面顶部的 Project 下拉菜单，选择已有项目或点击 "+ New project..." 创建新项目。

4. **如何下载生成的 DMP 文件？**
   Answer: DMP 生成完成后，左侧 Workspace 侧边栏的 "DMP Outputs" 分类下会出现生成的文件，点击文件名即可下载。

## What's NOT Included

- No anchor/scroll-to-section navigation (page is short enough to scroll)
- No i18n (Chinese only)
- No collapsible accordion sections (flat display, all visible)

## Files to Change

| File | Action |
|---|---|
| `frontend/src/pages/HelpPage.tsx` | **Create** — new help page component |
| `frontend/src/App.tsx` | Edit — add `/help` route inside ProtectedRoute |
| `frontend/src/pages/ChatPage.tsx` | Edit — add `?` help button in header |
| `frontend/src/pages/LogFormPage.tsx` | Edit — add `?` help button in header |
