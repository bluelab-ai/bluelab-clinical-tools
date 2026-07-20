/**
 * 检查是否为旧版 .doc 格式，是则弹出提示。
 * 返回 true 表示文件被拒绝。
 */
export function rejectOldDoc(file: File): boolean {
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (ext === "doc") {
    alert(
      `文件「${file.name}」为旧版 .doc 格式，不支持直接上传。\n\n` +
      "请用 Word 打开该文件 → 另存为 → 选择「Word 文档 (.docx)」格式，转换后刷新页面重新上传。"
    );
    return true;
  }
  return false;
}
