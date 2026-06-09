import { useEffect, useState } from "react";
import api from "../services/api";
import { FileInfo } from "../types";

interface Props {
  refreshTrigger: number;
}

export default function FileSidebar({ refreshTrigger }: Props) {
  const [files, setFiles] = useState<FileInfo[]>([]);

  useEffect(() => {
    api.get("/files/list").then((res) => setFiles(res.data.files)).catch(() => {});
  }, [refreshTrigger]);

  const handleDownload = async (name: string) => {
    const res = await api.get(`/files/download/${name}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete ${name}?`)) return;
    await api.delete(`/files/delete/${name}`);
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const byCategory = (cat: string) => files.filter((f) => f.category === cat);
  const labels: Record<string, string> = { log: "Logs", protocol: "Protocols", dmp: "DMP Outputs" };

  return (
    <div style={{ width: 240, background: "#1a1a2e", padding: 12, overflowY: "auto", borderRight: "1px solid #333" }}>
      <h3 style={{ fontSize: 14, marginBottom: 4 }}>Workspace</h3>
      {(["log", "protocol", "dmp"] as const).map((cat) => (
        <div key={cat} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, color: "#888", textTransform: "uppercase", marginBottom: 4 }}>
            {labels[cat]}
          </div>
          {byCategory(cat).map((f) => (
            <div
              key={f.name}
              style={{ fontSize: 12, padding: "4px 6px", borderRadius: 4, cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}
              title={`${f.name} (${(f.size / 1024).toFixed(1)} KB)`}
            >
              <span onClick={() => handleDownload(f.name)} style={{ flex: 1 }}>
                {f.name}
              </span>
              <span onClick={() => handleDelete(f.name)} style={{ color: "#f87171", cursor: "pointer", marginLeft: 8, fontSize: 14 }}>
                ×
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
