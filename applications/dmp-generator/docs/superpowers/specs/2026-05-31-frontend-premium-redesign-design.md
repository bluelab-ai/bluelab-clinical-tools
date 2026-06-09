# DMP Platform — 前端 UI 高级感升级设计规约

**日期**: 2026-05-31  
**范围**: 前端全局视觉、动画、布局优化  
**技术栈**: React 18 + TypeScript + Vite + Tailwind CSS 4

---

## 1. 设计目标

在不改变现有页面结构和组件架构的前提下，统一升级视觉语言，使之具备「高级感」：
- 深色奢华主色调（Dark Premium）
- 流畅叙事交互动画（Fluid Storytelling）
- 保留现有三栏布局，精致化打磨

## 2. 色彩体系

### 2.1 背景层级

| Token | 色值 | 用途 |
|---|---|---|
| `base` | `#09090b` | 页面底色（最深） |
| `surface` | `#121216` | 卡片、侧边栏、顶部栏 |
| `elevated` | `#1a1a22` | 悬浮面板、弹窗、菜单 |
| `hover` | `#22222d` | hover / active 态 |

### 2.2 主色调

从蓝色 `#3b82f6` 体系转换为 **indigo-violet** 体系：

| 角色 | 色值 |
|---|---|
| primary | `#7c3aed` |
| primary-light | `#a78bfa` |
| primary-subtle | `rgba(124, 58, 237, 0.12)` |
| primary-ghost | `rgba(124, 58, 237, 0.06)` |

### 2.3 文字层级

| 层级 | 色值 | 用途 |
|---|---|---|
| primary | `#fafafa` | 标题 |
| secondary | `#e4e4e7` | 正文 |
| tertiary | `#a1a1aa` | 辅助文字 |
| muted | `#71717a` | 占位/禁用 |
| disabled | `#52525b` | 禁用态 |

### 2.4 边框系统

| Token | 色值 | 用途 |
|---|---|---|
| subtle | `rgba(255,255,255,0.06)` | 卡片静默分隔 |
| default | `rgba(255,255,255,0.10)` | 面板/输入框边界 |
| strong | `rgba(255,255,255,0.15)` | 聚焦/选中态 |
| accent | `rgba(124,58,237,0.30)` | 主色强调边框 |

### 2.5 语义色

- **成功**: `#34d399`（emerald-400）
- **警告**: `#fbbf24`（amber-400）
- **错误**: `#f87171`（red-400）
- **AI 披露**: `#c084fc`（purple-400）

## 3. 字体与排版

### 3.1 字号层级

| 级别 | 字号 | 字重 | 用途 |
|---|---|---|---|
| h1 | 24px | Bold 700 | 页面标题 |
| h2 | 18px | Semibold 600 | 区块标题 |
| h3 | 15px | Semibold 600 | 小节标题 |
| body | 14px | Regular 400 | 正文 |
| caption | 12px | Regular 400 | 辅助信息 |
| mono | 11px | Regular 400 | 代码/标签 |

字体保持不变：Inter（正文）+ JetBrains Mono（代码）。

### 3.2 间距体系

基于 4px 网格：`4 / 8 / 12 / 16 / 24 / 32 / 48`

### 3.3 圆角体系

| 尺寸 | 值 | 用途 |
|---|---|---|
| sm | `6px` | 标签、徽章 |
| md | `8px` | 按钮、输入框 |
| lg | `10px` | 卡片、面板 |
| xl | `12px` | 弹窗 |
| full | `9999px` | 胶囊、头像 |

## 4. 动画体系

### 4.1 缓动曲线

```css
--ease-out: cubic-bezier(0.16, 1, 0.3, 1);      /* 入场 */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* 弹性反馈 */
--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);     /* 状态切换（默认） */
```

### 4.2 入场动画

| 名称 | 方向 | 用途 |
|---|---|---|
| `fade-in-up` | opacity + translateY(12px→0) | 消息入场 |
| `fade-in-right` | opacity + translateX(16px→0) | 面板滑入 |
| `scale-in` | opacity + scale(0.95→1) | 弹窗/菜单 |
| `slide-down` | translateY(-8px→0) + opacity | 下拉/展开 |

时长统一 **300ms**（入场）/ **200ms**（微交互）。

### 4.3 微交互

| 触发 | 效果 | 时长 |
|---|---|---|
| 按钮 hover | scale(1.02) + 阴影扩散 | 200ms ease-spring |
| 卡片 hover | translateY(-2px) + 边框提亮 | 200ms ease-out |
| 输入框聚焦 | 紫色光晕 box-shadow | 200ms ease-out |
| 文件项 hover | 背景渐变 + translateX(-2px) | 150ms ease-out |

### 4.4 Stagger 延时

列表项按 **60ms** 间隔依次入场，通过 CSS `animation-delay` 或 JS stagger 实现。

## 5. 组件改造清单

### 5.1 ChatPage（主页面）

- 背景色改为 `#09090b`
- 顶部栏：半透明毛玻璃背景 + 底部微光边框
- 状态条：深色胶囊标签（替代原浅色横幅）
- 消息区滚动条：细 + 紫色调
- 文件上传区：深色虚线边框

### 5.2 ChatMessage

- 角色标签：细线胶囊样式，文字色匹配角色色
- Cluade 消息：紫色渐变 blockquote 边框
- 代码块：深色底 `#121216` + 紫色关键词高亮
- 表格：深色表头 + 微光边框
- Phase header：紫色渐变分隔线（替代蓝色）

### 5.3 ChatInput

- Generate DMP 按钮：紫色渐变背景
- hover：发光扩散 shadow
- disabled：半透明 + 无光晕
- 区底分隔线改为微光边框

### 5.4 FileSidebar

- 底色 `#121216`，右侧微光分隔线
- 分类标签：细线字体 + muted 色
- 文件项 hover：背景渐变 + 左移 2px
- 用户菜单弹窗：深色 elevated 背景 + 微光边框

### 5.5 QuestionCard

- 选项按钮：深色底 + 微光边框
- 选中态：紫色渐变边框 + box-shadow 发光
- 文本输入框：深色填充 + 聚焦紫色光晕
- 提交按钮：紫色渐变

### 5.6 FileUpload

- 拖拽区：深色虚线边框
- 拖拽中：紫色边框 + 微弱紫色背景
- 图标改为紫色调

### 5.7 ReportPanel

- 独立深色面板背景
- 头部：左侧紫色竖线标识
- 拖拽手柄：hover 时紫色发光
- 滚动条：细 + 紫色调
- 面板入场：fade-in-right 动画

### 5.8 LoginPage / RegisterPage

- 页面背景：深色底 + 微妙网格纹理（CSS background-pattern）
- 登录卡片：深色 surface 底 + 微光边框
- 输入框：深色填充 + 聚焦紫色光晕
- 提交按钮：紫色渐变 + hover 发光
- Logo 区域保持不变

### 5.9 LogFormPage

- 整体深色主题背景
- 表单卡片：深色 surface 底
- 条件字段显隐：增加 slide-down 过渡
- 帮助按钮：移至右上角

### 5.10 HelpPage

- 步骤卡片：深色 surface 底 + stagger 入场
- FAQ 区块：展开箭头 + slide-down
- 截图区域：深色边框容器

## 6. 实现策略

### 6.1 CSS 变量体系

在 `index.css` 中通过 Tailwind CSS 4 的 `@theme` 指令注入颜色、阴影、动画变量。所有组件通过 Tailwind 类名引用，不写裸色值。

### 6.2 实施顺序

1. `index.css` — 建立全局色彩/动画/阴影 CSS 变量体系
2. `tailwind.config` — 将变量挂载到 Tailwind 主题
3. `ChatPage.tsx` — 主页面，影响最大
4. `ChatMessage.tsx` — 消息渲染，最复杂的组件
5. `FileSidebar.tsx` — 导航视觉
6. `ChatInput.tsx` — 核心操作按钮
7. `QuestionCard.tsx` — 交互组件
8. `ReportPanel.tsx` — 报告面板
9. `FileUpload.tsx` — 上传区
10. `LoginPage.tsx` + `RegisterPage.tsx` — 认证页
11. `LogFormPage.tsx` + `HelpPage.tsx` — 辅助页

### 6.3 不做什么

- 不改组件结构 / props 接口
- 不改业务逻辑
- 不引入新的第三方依赖
- 不改后端代码
- 不添加新功能

## 7. 验收标准

- [ ] 深色主题为默认主题，全页面视觉统一
- [ ] 所有交互有流畅动画反馈（hover / focus / click / 入场）
- [ ] 紫色主调贯穿所有组件
- [ ] 亮色模式依然可用（保持但不作为本次重点）
- [ ] TypeScript 编译无错误
- [ ] 现有功能无回归
