# TFL-Listing Cross-Validation QC — 使用教程

## 1. 这是什么？

一个临床试验 TFL（Tables/Figures/Listings）反向质控工具。核心理念：**表格里的每一个数字，都应能从清单中推算出来。**

适用场景：
- 拿到 SAR/SAP 的表格附件和清单附件，需要做交叉核查
- 验证 AE/SAE 表格与清单的一致性
- 检查分析集（FAS/PPS/SS）人数、受试者流向、主要终点跨文件一致
- 批量 QC 数十对表格-清单，自动生成分级报告

不适用场景：
- 只有单对表格-清单（直接用 subagent 模板更高效）
- 只做格式转换
- 文件已经是提取好的 Excel，且映射关系已知（从 Phase 3 开始即可）

---

## 2. 环境准备

### 2.1 Python 依赖

```bash
pip install python-docx openpyxl sentence-transformers scikit-learn lxml numpy
```

### 2.2 余弦相似度模型下载（重要）

Phase 1 匹配使用 HuggingFace 模型 `BAAI/bge-large-zh-v1.5` 计算表格标题与清单标题的语义相似度。首次运行 `match_tables_listings.py` 时会**自动从 HuggingFace Hub 下载**模型文件（约 1.3 GB），下载后的模型缓存到以下位置：

| 操作系统 | 缓存路径 |
|----------|----------|
| macOS/Linux | `~/.cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/` |
| Windows | `%USERPROFILE%\.cache\huggingface\hub\models--BAAI--bge-large-zh-v1.5/` |

#### 方式一：自动下载（推荐，需科学上网）

直接运行匹配脚本，sentence-transformers 会自动下载模型：

```bash
python3 scripts/match_tables_listings.py 表格.docx 清单.docx 映射表.json
```

首次运行会看到进度条：
```
Loading weights: 100%|██████████| 391/391 [00:00<00:00, 74462.99it/s]
```

#### 方式二：手动下载（网络受限环境）

如果无法访问 HuggingFace Hub，可通过镜像站或离线方式下载：

**A. 使用 HF 镜像站**

```bash
# 设置镜像环境变量后运行脚本
export HF_ENDPOINT=https://hf-mirror.com
python3 scripts/match_tables_listings.py 表格.docx 清单.docx 映射表.json
```

**B. 离线下载后手动放置**

1. 在有网络的机器上，用以下任一方式下载模型文件：

   ```bash
   # 方式 1：用 huggingface-cli
   pip install huggingface_hub
   huggingface-cli download BAAI/bge-large-zh-v1.5 --local-dir ./bge-large-zh-v1.5

   # 方式 2：用 git-lfs
   git lfs install
   git clone https://huggingface.co/BAAI/bge-large-zh-v1.5
   ```

2. 需要下载的完整文件列表：
   ```
   bge-large-zh-v1.5/
   ├── config.json
   ├── model.safetensors          (~1.3 GB)
   ├── tokenizer.json
   ├── tokenizer_config.json
   ├── special_tokens_map.json
   ├── vocab.txt
   ├── modules.json
   ├── sentence_bert_config.json
   └── 1_Pooling/
       └── config.json
   ```

3. 将整个文件夹拷贝到目标机器的缓存目录，或通过代码指定本地路径。

**C. 代码中指定本地模型路径**

如果不想用缓存目录，可修改 `match_tables_listings.py` 第 364 行：

```python
# 原来（自动从 Hub 下载）
model = SentenceTransformer("BAAI/bge-large-zh-v1.5")

# 改为本地路径
model = SentenceTransformer("/path/to/bge-large-zh-v1.5")
```

#### 方式三：预先缓存（批量部署）

在多台机器上批量使用时，可以在一台机器下载后，将缓存目录打包分发：

```bash
# 在已下载的机器上打包
tar -czf bge-large-zh-v1.5-cache.tar.gz -C ~/.cache/huggingface/hub models--BAAI--bge-large-zh-v1.5

# 在目标机器上解压到相同位置
tar -xzf bge-large-zh-v1.5-cache.tar.gz -C ~/.cache/huggingface/hub/
```

#### 验证模型是否就绪

```bash
python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-large-zh-v1.5')
print('模型加载成功，向量维度:', model.get_sentence_embedding_dimension())
"
# 预期输出: 模型加载成功，向量维度: 1024
```

---

## 3. 五阶段流程

### Phase 1：匹配表格与清单

**输入：** 表格附件 docx + 清单附件 docx
**输出：** `表格-清单-映射表.json`

```bash
cd <项目目录>
python3 <skill目录>/scripts/match_tables_listings.py \
    表格附件.docx \
    清单附件.docx \
    表格-清单-映射表.json
```

匹配策略（三级级联）：
1. **关键字匹配** — 从表格标题提取核心词，用最长公共子串在清单标题中搜索。直接包含即高置信度命中。
2. **余弦相似度** — 用 BAAI/bge-large-zh-v1.5 编码标题，分差 ≥0.06 为直接匹配，<0.06 为多源候选。
3. **DeepSeek LLM 兜底**（可选）— 对多源候选对用 LLM 重匹配。

输出统计示例：
```
表格: 43  清单: 21
关键字匹配: 23  直接匹配: 6  多源候选: 14  需人工审核: 20
```

### Phase 1b：交互式复核

生成 HTML 页面供人工审查和修正匹配结果：

```bash
python3 -c "
import json
with open('<skill>/assets/映射复核.html') as f: tpl = f.read()
with open('表格-清单-映射表.json') as f: data = json.load(f)
listings = sorted(set(c['清单名称'] for d in data for c in [d['最佳匹配']]+d.get('候选匹配',[])))
html = tpl.replace('__MAPPING_DATA__', json.dumps(data, ensure_ascii=False, separators=(',',':')))
html = html.replace('__LISTINGS_DATA__', json.dumps(listings, ensure_ascii=False))
with open('映射复核.html','w') as f: f.write(html)
```

用浏览器打开 `映射复核.html`，审查匹配、修正错误，点击 **"导出修改"** 下载 `表格-清单-映射表-已复核.json`，放回项目目录。

### Phase 2：提取表格到 Excel

```bash
cd <项目目录>
python3 <skill目录>/scripts/extract_tables.py 表格附件.docx 清单附件.docx
```

输出结构：
```
表格/
  01-表 5.1.1.1 各中心的病例分布情况（入组人群）.xlsx
  02-表 5.1.1.2 受试者人群划分情况（入组人群）.xlsx
  ...
清单/
  01-清单 1 受试者完成情况清单（所有入组人群）.xlsx
  02-清单 2 一般资料清单（FAS）.xlsx
  ...
```

### Phase 3：批量 QC（核心步骤）

由主流程计算 keyword-matched 对数 N，一次性并行启动 N 个 subagent，每个负责一对表格-清单的反向核查。Subagent 会：
1. 定位 Excel 文件
2. 解析表格和清单结构
3. 根据表格类型选择核查规则
4. 编写 Python 比对脚本并执行
5. 输出 `QC结果-Pair{N}.md`

核查覆盖四类规则：
| 类别 | 检查项 |
|------|--------|
| 总体质控 | 人数去重、例次 vs 人数、组别一致、分析集一致 |
| AE/SAE | Table↔Listing 总数、SAE 在 AE 中、死亡链路、人数≤例次 |
| 事件类 | 跨疗效/安全性表一致、复合终点=Σ组成事件 |
| 实验室/生命体征 | 异常 Listing↔交叉表、min≤Q1≤median≤Q3≤max、n+缺失=N |

### Phase 4：合并报告

```bash
cd <项目目录>
python3 <skill目录>/scripts/merge_qc.py . QC报告-汇总.md
```

生成两份报告：
- `QC结果-全部合并.md` — 完整详细报告（默认输出）
- `QC报告-汇总.md` — 带封面的汇总报告（指定输出）

### Phase 5：清理中间文件

```bash
# 预览
python3 <skill目录>/scripts/cleanup_qc.py . --dry-run

# 执行
python3 <skill目录>/scripts/cleanup_qc.py .
```

---

## 4. 匹配策略详解

### 4.1 关键字匹配是第一优先级

关键字匹配不依赖模型，通过最长公共子串（LCS）直接匹配标题核心词。例如：
- 表格 "不良事件发生率（SS）" → 剥离人群后缀 → "不良事件发生率" → 匹配清单 "不良事件清单（SS）"

关键字命中即为高置信度匹配，直接进入 QC，不需要人工复核。

### 4.2 余弦相似度的角色

当关键字无法命中时（如 "手术成功率" vs "器械和手术评价" 没有公共子串），余弦相似度通过语义向量判断相关性。分差（gap）用于区分：
- **分差 ≥ 0.06**：第一名明显优于第二名 → 直接匹配
- **分差 < 0.06**：前两名接近，难以自动判定 → 多源候选

### 4.3 什么情况需要人工复核

以下匹配结果应进入 Phase 1b 人工复核：
- 多源候选对（分差 < 0.06）
- 余弦相似度 < 0.58 的低置信度匹配
- 直接匹配但相似度在 0.58-0.70 之间的中置信度对

---

## 5. 常见问题

### Q1: 模型下载失败 / 网络超时

设置镜像或手动下载（见 2.2 节方式二）。

### Q2: 内存不足

bge-large-zh-v1.5 模型加载约需 1.3 GB 内存。如果内存紧张，可在 `match_tables_listings.py` 中将模型切换为轻量版：

```python
# 原来
model = SentenceTransformer("BAAI/bge-large-zh-v1.5")

# 轻量替代（约 0.4 GB，中文效果略降）
model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
```

### Q3: 提取的 Excel 合并单元格值为空

docx 提取时纵向合并的单元格只在首行有值。解析时需前向填充或用块分组来处理。

### Q4: 表格有多行表头导致解析错误

TFL 表格常有 2-3 行表头（N=XX 标签行 + 列名行 + 分组行）。Subagent 必须先 `print` 全部行来确定数据起始行。

### Q5: Excel 文件名搜索不到

表格名称中的特殊字符可能导致搜索不匹配。先用 `ls` 列出文件夹所有文件，再模糊匹配。

### Q6: QC 结果中某个 pair 迟迟不完成

Subagent 超时阈值为 10 分钟。超过后向用户报告并询问是否跳过该 pair。

---

## 6. 文件清单

| 文件 | 说明 |
|------|------|
| `SKILL.md` | Skill 完整定义和执行指令 |
| `TUTORIAL.md` | 本教程 |
| `scripts/match_tables_listings.py` | Phase 1 匹配脚本 |
| `scripts/deepseek_match.py` | DeepSeek LLM 兜底匹配 |
| `scripts/extract_tables.py` | Phase 2 表格提取脚本 |
| `scripts/merge_qc.py` | Phase 4 报告合并脚本 |
| `scripts/cleanup_qc.py` | Phase 5 清理脚本 |
| `reference/qc_rules.md` | QC 核查规则定义 |
| `reference/subagent_output_template.md` | Subagent 输出模板规范 |
| `assets/映射复核.html` | Phase 1b 交互式复核页面模板 |
