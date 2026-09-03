import { useRef, useState } from "react";
import { Upload, CheckCircle2, Loader2, X } from "lucide-react";

interface UploadCardProps {
  label: string;
  accept: string;
  uploaded: boolean;
  uploading: boolean;
  filename: string;
  onUpload: (file: File) => void;
  onRemove: () => void;
  required?: boolean;
}

export default function UploadCard({
  label, accept, uploaded, uploading, filename, onUpload, onRemove, required,
}: UploadCardProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) onUpload(file);
  };

  return (
    <div
      className={`relative rounded-2xl border-2 border-dashed p-6 text-center transition-all cursor-pointer ${
        dragging
          ? "border-blue-400 bg-blue-50"
          : uploaded
            ? "border-emerald-300 bg-emerald-50/50"
            : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/30"
      }`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !uploaded && !uploading && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
      />

      {uploading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 size={32} className="text-blue-500 animate-spin" />
          <p className="text-sm text-slate-500">上传中...</p>
        </div>
      ) : uploaded ? (
        <div className="flex flex-col items-center gap-2">
          <CheckCircle2 size={32} className="text-emerald-500" />
          <p className="text-sm font-medium text-slate-700 truncate max-w-full">{filename}</p>
          <p className="text-xs text-emerald-600">上传成功</p>
          <button
            onClick={(e) => { e.stopPropagation(); onRemove(); }}
            className="absolute top-3 right-3 w-7 h-7 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-400 hover:text-red-500 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload size={32} className="text-slate-400" />
          <p className="text-sm font-medium text-slate-700">
            {label}
            {required && <span className="text-red-400 ml-1">*</span>}
          </p>
          <p className="text-xs text-slate-400">点击或拖拽文件到此处</p>
        </div>
      )}
    </div>
  );
}
