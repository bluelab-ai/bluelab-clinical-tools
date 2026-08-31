# 更新日志本地数据

`entries.json` 是 8517 开发试用版“更新日志”页面的数据源。页面按置顶状态和发布时间倒序显示；甲方页面只读，不能从网页端发布或修改日志。

## 单条记录格式

```json
{
  "id": "release-20260727-01",
  "published_at": "2026-07-27 17:11 CST",
  "version": "开发试用版 2026.07",
  "category": "功能更新",
  "title": "更新标题",
  "body": "一段简短说明。",
  "highlights": ["变化一", "变化二"],
  "images": [
    {
      "path": "示例图片.png",
      "caption": "图片说明",
      "wide": false
    }
  ],
  "pinned": false
}
```

## 人工发布步骤

1. 将 PNG 或 JPG 图片放入 `data/changelog/media/`；推荐宽度 600–1400 px，避免包含患者级数据。
2. 在 `data/changelog/entries.json` 的 `entries` 列表开头加入一条记录。`published_at` 建议写为 `YYYY-MM-DD HH:MM CST`。
3. 普通图片保持 `wide: false`；横向截图需要整行展示时设为 `wide: true`。
4. 检查 JSON 格式：`.demo_venv/bin/python -m json.tool data/changelog/entries.json >/dev/null`。
5. 8517 关闭了文件自动监视，发布后运行：`systemctl --user restart bzp-sponsor-dev.service`。
6. 打开 8517 的“更新日志”页面，确认时间、文字、图片清晰度和移动端布局。

图片路径只能是 `media` 目录中的直接文件名，不能使用绝对路径或子目录。更新内容应保持探索性、规划阶段边界，不应写成已证实疗效或三期成功率结论。
