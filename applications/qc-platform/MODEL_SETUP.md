# 模型配置说明

本项目使用 `BAAI/bge-large-zh-v1.5` 模型进行文本向量化。由于模型文件较大（约 4.9GB），不包含在 Git 仓库中。

## 下载模型

### 方法一：使用 huggingface-cli（推荐）

```bash
# 安装 huggingface_hub
pip install huggingface_hub

# 下载模型
huggingface-cli download BAAI/bge-large-zh-v1.5 --local-dir ./models--BAAI--bge-large-zh-v1.5
```

### 方法二：使用 Python

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="BAAI/bge-large-zh-v1.5",
    local_dir="./models--BAAI--bge-large-zh-v1.5"
)
```

### 方法三：手动下载

1. 访问 [Hugging Face 模型页面](https://huggingface.co/BAAI/bge-large-zh-v1.5)
2. 下载所有文件到 `models--BAAI--bge-large-zh-v1.5` 目录

## 目录结构

下载完成后，目录结构应如下：

```
qc-platform/
├── backend/
├── frontend/
├── models--BAAI--bge-large-zh-v1.5/
│   ├── blobs/
│   ├── refs/
│   └── snapshots/
└── ...
```

## 验证模型

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('./models--BAAI--bge-large-zh-v1.5')
embeddings = model.encode(["测试文本"])
print(f"向量维度: {embeddings.shape[1]}")
```
