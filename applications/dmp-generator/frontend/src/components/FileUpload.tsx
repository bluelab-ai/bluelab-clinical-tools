import { useRef, useState } from "react";
import { Upload } from "lucide-react";
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
      className={`border-2 border-dashed rounded-2xl p-5 text-center cursor-pointer transition-colors ${
        dragging ? "border-blue-500 bg-blue-50/50" : "border-slate-300 bg-slate-50/50 hover:bg-slate-100/50"
      }`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); }}
      onClick={() => fileInputRef.current?.click()}
    >
      <div className="flex flex-col items-center gap-2">
        <Upload size={24} className={dragging ? "text-blue-600" : "text-slate-400"} />
        <p className="text-sm text-slate-600 font-medium">
          {uploading ? "Uploading..." : "Drop protocol file here or click to browse"}
        </p>
        <p className="text-xs text-slate-400">
          仅支持 .docx 格式（最大 50MB）。上传前请先接受所有修订并删除批注。
        </p>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        hidden
        accept=".docx"
        onChange={(e) => { if (e.target.files?.[0]) upload(e.target.files[0]); }}
      />
    </div>
  );
}
