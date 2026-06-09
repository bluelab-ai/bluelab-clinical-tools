import { useRef, useState } from "react";
import api from "../services/api";

interface Props {
  onUploaded: () => void;
}

export default function FileUpload({ onUploaded }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      await api.post("/files/upload", formData);
      onUploaded();
    } catch (err: any) {
      alert("Upload failed: " + (err.response?.data?.detail || "Error"));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      style={{
        border: `2px dashed ${dragging ? "#4ade80" : "#555"}`,
        borderRadius: 8,
        padding: 20,
        textAlign: "center",
        marginBottom: 16,
        cursor: "pointer",
      }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); }}
      onClick={() => fileInputRef.current?.click()}
    >
      <p style={{ color: "#888", margin: 0 }}>
        {uploading ? "Uploading..." : "Drop protocol file here or click to browse"}
      </p>
      <p style={{ color: "#666", fontSize: 12, margin: "4px 0 0" }}>
        Supports .docx .pdf .txt .md (max 50MB)
      </p>
      <input
        ref={fileInputRef}
        type="file"
        hidden
        accept=".docx,.pdf,.txt,.md"
        onChange={(e) => { if (e.target.files?.[0]) upload(e.target.files[0]); }}
      />
    </div>
  );
}
