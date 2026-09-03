# QUANSUB模板变体说明

## 概述
基于 F_G1_QUANSUB_N_N（单组-无缺失）基础模板，创建了5个QUANSUB模板变体。

## 模板列表

### 1. F_G1_QUANSUB_Y_N（单组-有缺失）
- **路径**: `/Users/xulei/项目/sap/sap_toolkit/scripts/phase2/模板代码/F_G1_QUANSUB_Y_N/`
- **列数**: 4列（亚组、项目、指标、结果）
- **行数**: 6行/指标（增加缺失行）
- **特点**: 单组数据，包含缺失值统计

### 2. F_G2_QUANSUB_N_N（两组-无缺失）
- **路径**: `/Users/xulei/项目/sap/sap_toolkit/scripts/phase2/模板代码/F_G2_QUANSUB_N_N/`
- **列数**: 5列（亚组、项目、指标、试验组、对照组）
- **行数**: 5行/指标
- **特点**: 两组对比数据，无缺失值

### 3. F_G2_QUANSUB_Y_N（两组-有缺失）
- **路径**: `/Users/xulei/项目/sap/sap_toolkit/scripts/phase2/模板代码/F_G2_QUANSUB_Y_N/`
- **列数**: 5列（亚组、项目、指标、试验组、对照组）
- **行数**: 6行/指标（增加缺失行）
- **特点**: 两组对比数据，包含缺失值统计

### 4. F_G3_QUANSUB_N_N（三组-无缺失）
- **路径**: `/Users/xulei/项目/sap/sap_toolkit/scripts/phase2/模板代码/F_G3_QUANSUB_N_N/`
- **列数**: 6列（亚组、项目、指标、试验组A、试验组B、对照组）
- **行数**: 5行/指标
- **特点**: 三组对比数据，无缺失值

### 5. F_G3_QUANSUB_Y_N（三组-有缺失）
- **路径**: `/Users/xulei/项目/sap/sap_toolkit/scripts/phase2/模板代码/F_G3_QUANSUB_Y_N/`
- **列数**: 6列（亚组、项目、指标、试验组A、试验组B、对照组）
- **行数**: 6行/指标（增加缺失行）
- **特点**: 三组对比数据，包含缺失值统计

## 每个模板包含的文件

1. **{code}.json** - 语义JSON模板
   - 定义表格结构、列配置、行模板
   - 描述重复模式和变量插槽

2. **fill_template.py** - 数据填充脚本
   - 读取语义模板和填充数据
   - 生成填充结果JSON

3. **gen_docx.py** - Word文档生成脚本
   - 从填充结果生成三线表Word文档
   - 支持亚组合并单元格

4. **填充数据.json** - 示例数据
   - 包含亚组分类和指标示例数据

## 统计行说明

### N_N（无缺失）- 5行
1. 例数(缺失)
2. 均值(标准差)
3. 中位数
4. 第25%分位数,第75%分位数
5. 最小值,最大值

### Y_N（有缺失）- 6行
1. 例数(缺失)
2. 均值(标准差)
3. 中位数
4. 第25%分位数,第75%分位数
5. 最小值,最大值
6. 缺失

## 使用方法

### 1. 填充数据
```bash
cd /path/to/template
python fill_template.py
```

### 2. 生成Word文档
```bash
python gen_docx.py 填充结果.json -o 输出文档.docx
```

## 测试结果

所有模板均已测试通过：
- ✅ F_G1_QUANSUB_Y_N
- ✅ F_G2_QUANSUB_N_N
- ✅ F_G2_QUANSUB_Y_N
- ✅ F_G3_QUANSUB_N_N
- ✅ F_G3_QUANSUB_Y_N

## 代码风格

所有模板保持与基础模板 F_G1_QUANSUB_N_N 一致的代码风格：
- 相同的函数结构
- 相同的JSON处理逻辑
- 相同的Word文档生成逻辑
- 相同的三线表格式

## 扩展说明

如需创建更多变体，可参考以下模式：
- **G{n}**: n组数据（1/2/3组）
- **N_N**: 无缺失（5行）
- **Y_N**: 有缺失（6行）
