import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Upload,
  FileText,
  CircleCheck,
  X,
  Play,
  Loader2,
  Download,
  AlertCircle,
  FileCheck,
  ScrollText,
} from "lucide-react";
import api from "../services/api";
import { useSSE } from "../hooks/useSSE";
import { rejectOldDoc } from "../utils/fileValidation";

interface UploadState {
  file: File | null;
  uploaded: boolean;
  uploading: boolean;
  path: string;
}

export default function ProtocolTableQCPage() {
  const navigate = useNavigate();
  const { connect, cancel } = useSSE();

  // Upload states: 方案 + 表格
  const [protocolUpload, setProtocolUpload] = useState<UploadState>({
    file: null, uploaded: false, uploading: false, path: "",
  });
  const [tableUpload, setTableUpload] = useState<UploadState>({
    file: null, uploaded: false, uploading: false, path: "",
  });

  // QC states
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [qcComplete, setQcComplete] = useState(false);

  // Temp folder lifecycle
  const [tempDir, setTempDir] = useState("");
  const [tempId, setTempId] = useState("");
  const [tempReady, setTempReady] = useState(false);
  const tempDirRef = useRef("");

  // Session id for download
  const [sessionId, setSessionId] = useState("");

  // Refs for SSE closure
  const progressRef = useRef(0);

  // Drag states
  const [protocolDragging, setProtocolDragging] = useState(false);
  const [tableDragging, setTableDragging] = useState(false);
  const protocolInputRef = useRef<HTMLInputElement>(null);
  const tableInputRef = useRef<HTMLInputElement>(null);

  // ── Temp folder lifecycle ─────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    api.post("/qc/temp-folder")
      .then((res) => {
        if (!cancelled) {
          setTempDir(res.data.temp_dir);
          setTempId(res.data.temp_id);
          tempDirRef.current = res.data.temp_dir;
          setTempReady(true);
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          console.error("创建临时目录失败:", err);
          setErrorMsg("无法创建临时工作目录，请刷新页面重试");
        }
      });
    return () => { cancelled = true; };
  }, []);

  const cleanupTempFolder = () => {
    const dir = tempDirRef.current;
    if (!dir) return;
    const blob = new Blob(
      [JSON.stringify({ temp_dir: dir })],
      { type: "application/json" },
    );
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/qc/cleanup", blob);
    }
  };

  useEffect(() => {
    window.addEventListener("beforeunload", cleanupTempFolder);
    return () => {
      window.removeEventListener("beforeunload", cleanupTempFolder);
      cleanupTempFolder();
    };
  }, []);

  // ── Upload file ───────────────────────────────────────────────────────

  const uploadFile = async (
    file: File,
    category: string,
    setState: (updater: (prev: UploadState) => UploadState) => void,
  ) => {
    if (rejectOldDoc(file)) return;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("category", category);
    if (tempDirRef.current) {
      formData.append("temp_dir", tempDirRef.current);
    }
    setState((prev) => ({ ...prev, uploading: true }));
    try {
      const res = await api.post("/files/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setState((prev) => ({
        ...prev, uploaded: true, uploading: false,
        path: res.data.path || res.data.filename || file.name,
      }));
    } catch (err: any) {
      setState((prev) => ({ ...prev, uploading: false }));
      alert("上传失败: " + (err.response?.data?.detail || "请重试"));
    }
  };

  const removeFile = (
    setState: (updater: (prev: UploadState) => UploadState) => void,
  ) => {
    setState((prev) => ({ ...prev, file: null, uploaded: false, uploading: false, path: "" }));
  };

  // ── Start QC ──────────────────────────────────────────────────────────

  const startQC = () => {
    if (!protocolUpload.uploaded || !tableUpload.uploaded) {
      setErrorMsg("请先上传方案文件和表格文件");
      return;
    }
    setIsRunning(true);
    setProgress(0);
    progressRef.current = 0;
    setErrorMsg("");
    setQcComplete(false);
    setSessionId("");
    setProgressText("正在启动...");

    connect(
      "/api/qc/protocol-table",
      {
        protocol_path: protocolUpload.path,
        table_path: tableUpload.path,
        project_dir: tempDirRef.current,
      },
      (data: Record<string, unknown>) => {
        const eventType = data._eventType || data.type;

        switch (eventType) {
          case "progress":
            if (data.percent !== undefined) {
              progressRef.current = data.percent as number;
              setProgress(progressRef.current);
            }
            if (data.text) setProgressText(data.text as string);
            break;

          case "total_pairs":
            // For protocol-table QC, total_pairs represents agent count
            break;

          case "error":
            setErrorMsg((data.content as string) || "质控过程发生错误");
            setIsRunning(false);
            break;

          case "done":
            progressRef.current = 100;
            setProgress(100);
            setProgressText("质控完成");
            setQcComplete(true);
            setIsRunning(false);
            if (data.session_id) setSessionId(data.session_id as string);
            break;
        }
      },
      (error: string) => {
        setErrorMsg(error);
        setIsRunning(false);
      },
    );
  };

  const cancelQC = () => {
    cancel();
    setIsRunning(false);
    setProgress(0);
    progressRef.current = 0;
    setProgressText("已取消");
    setSessionId("");
  };

  const resetQC = () => {
    setProgress(0);
    progressRef.current = 0;
    setProgressText("");
    setQcComplete(false);
    setErrorMsg("");
    setSessionId("");
  };

  const canStart = protocolUpload.uploaded && tableUpload.uploaded && !isRunning && tempReady;

  // ── Circular progress ring calculations ───────────────────────────────

  const ringRadius = 90;
  const ringCircumference = 2 * Math.PI * ringRadius;
  const ringOffset = ringCircumference - (progress / 100) * ringCircumference;

  return (
    <div className="min-h-screen bg-slate-50 font-sans antialiased">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/70 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate("/home")}
              className="flex items-center gap-1.5 text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="flex items-center gap-3">
              <img src="/logo.png" alt="Logo" className="h-8" />
              <div>
                <h1 className="text-lg font-bold text-slate-900">方案表格一致性质控</h1>
                <p className="text-xs text-slate-500">Protocol-Table Consistency QC</p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* ========== LEFT PANEL: Progress ========== */}
          <div className="lg:col-span-3 space-y-6">
            {/* Progress Card */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8">
              <h3 className="text-sm font-semibold text-slate-700 mb-6 flex items-center gap-2">
                <FileCheck size={18} className="text-blue-600" />
                质控进度
              </h3>

              {/* Circular Progress Ring */}
              <div className="flex flex-col items-center">
                <div className="relative w-56 h-56 mb-6">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 200 200">
                    <circle
                      cx="100" cy="100" r={ringRadius}
                      fill="none"
                      stroke="#e2e8f0"
                      strokeWidth="10"
                    />
                    {/* Progress ring */}
                    <circle
                      cx="100" cy="100" r={ringRadius}
                      fill="none"
                      stroke={qcComplete ? "#10b981" : "#2563eb"}
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={ringCircumference}
                      strokeDashoffset={ringOffset}
                      className="transition-all duration-700 ease-out"
                    />
                  </svg>

                  {/* Center content */}
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    {isRunning ? (
                      <>
                        <Loader2 size={32} className="text-blue-600 animate-spin mb-1" />
                        <span className="text-4xl font-bold text-blue-600 tabular-nums">
                          {progress}%
                        </span>
                      </>
                    ) : qcComplete ? (
                      <>
                        <CircleCheck size={32} className="text-emerald-500 mb-1" />
                        <span className="text-4xl font-bold text-emerald-600">100%</span>
                      </>
                    ) : (
                      <>
                        <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center mb-1">
                          <Play size={16} className="text-slate-400" />
                        </div>
                        <span className="text-4xl font-bold text-slate-300">0%</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Status text */}
                <p className="text-sm text-slate-600 font-medium mb-2">
                  {progressText || "等待开始"}
                </p>

                {/* Error display */}
                {errorMsg && (
                  <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-start gap-2 w-full">
                    <AlertCircle size={16} className="text-red-500 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-red-700">{errorMsg}</p>
                  </div>
                )}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              {!isRunning && !qcComplete && (
                <button
                  onClick={startQC}
                  disabled={!canStart}
                  className={`flex-1 py-4 rounded-2xl font-bold text-white shadow-sm transition-all flex items-center justify-center gap-2 ${
                    canStart
                      ? "bg-blue-600 hover:bg-blue-700 active:scale-[0.98] cursor-pointer"
                      : "bg-slate-300 cursor-not-allowed"
                  }`}
                >
                  <Play size={20} />
                  点击进行方案表格一致性质控
                </button>
              )}
              {isRunning && (
                <button
                  onClick={cancelQC}
                  className="flex-1 py-4 rounded-2xl font-bold text-white bg-red-500 hover:bg-red-600 shadow-sm transition-all active:scale-[0.98] cursor-pointer flex items-center justify-center gap-2"
                >
                  <X size={20} />
                  取消质控
                </button>
              )}
              {qcComplete && (
                <>
                  <button
                    onClick={resetQC}
                    className="flex-1 py-4 rounded-2xl font-bold text-white bg-blue-600 hover:bg-blue-700 shadow-sm transition-all active:scale-[0.98] cursor-pointer flex items-center justify-center gap-2"
                  >
                    <Play size={20} />
                    重新质控
                  </button>
                  {sessionId && (
                    <button
                      onClick={async () => {
                        try {
                          const res = await api.get(`/qc/download-protocol-viewer/${sessionId}`, { responseType: "blob" });
                          const blob = new Blob([res.data], { type: "text/html" });
                          const url = window.URL.createObjectURL(blob);
                          const link = document.createElement("a");
                          link.href = url;
                          link.download = "方案表格一致性质控报告.html";
                          document.body.appendChild(link);
                          link.click();
                          document.body.removeChild(link);
                          window.URL.revokeObjectURL(url);
                        } catch {
                          // fallback: 直接打开
                          window.open(`/api/qc/download-protocol-viewer/${sessionId}`, "_blank");
                        }
                      }}
                      className="px-6 py-4 rounded-2xl font-bold text-blue-600 bg-blue-50 hover:bg-blue-100 border border-blue-200 transition-all active:scale-[0.98] cursor-pointer flex items-center gap-2"
                    >
                      <Download size={20} />
                      下载报告
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {/* ========== RIGHT PANEL: File Upload ========== */}
          <div className="lg:col-span-2 space-y-5">
            {/* Temp folder not ready yet */}
            {!tempReady && (
              <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-6 flex items-center gap-4">
                <Loader2 size={24} className="text-blue-600 animate-spin flex-shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-slate-700">正在初始化工作区...</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    创建临时文件目录，请稍候
                  </p>
                </div>
              </div>
            )}

            {/* Protocol Upload — 方案文件 */}
            <UploadCard
              title="上传方案文件"
              subtitle="Protocol (.docx)"
              icon={<ScrollText size={22} />}
              state={protocolUpload}
              dragging={protocolDragging}
              onDragOver={(e) => { e.preventDefault(); setProtocolDragging(true); }}
              onDragEnter={(e) => { e.preventDefault(); setProtocolDragging(true); }}
              onDragLeave={() => setProtocolDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setProtocolDragging(false);
                if (e.dataTransfer.files[0]) {
                  const file = e.dataTransfer.files[0];
                  setProtocolUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "protocol", (updater) => setProtocolUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
              onClick={() => !isRunning && protocolInputRef.current?.click()}
              onRemove={() => removeFile((updater) => setProtocolUpload((prev) => ({ ...prev, ...updater(prev) })))}
              disabled={isRunning || !tempReady}
              required
            />
            <input ref={protocolInputRef} type="file" hidden accept=".docx"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  const file = e.target.files[0];
                  setProtocolUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "protocol", (updater) => setProtocolUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
            />

            {/* Table Upload — 表格文件 */}
            <UploadCard
              title="上传表格文件"
              subtitle="Tables (.docx)"
              icon={<FileText size={22} />}
              state={tableUpload}
              dragging={tableDragging}
              onDragOver={(e) => { e.preventDefault(); setTableDragging(true); }}
              onDragEnter={(e) => { e.preventDefault(); setTableDragging(true); }}
              onDragLeave={() => setTableDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setTableDragging(false);
                if (e.dataTransfer.files[0]) {
                  const file = e.dataTransfer.files[0];
                  setTableUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "table", (updater) => setTableUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
              onClick={() => !isRunning && tableInputRef.current?.click()}
              onRemove={() => removeFile((updater) => setTableUpload((prev) => ({ ...prev, ...updater(prev) })))}
              disabled={isRunning || !tempReady}
              required
            />
            <input ref={tableInputRef} type="file" hidden accept=".docx"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  const file = e.target.files[0];
                  setTableUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "table", (updater) => setTableUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
            />

          </div>
        </div>
      </main>
    </div>
  );
}

// ─── Upload Card Sub-Component ───────────────────────────────────────────

interface UploadCardProps {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  state: UploadState;
  dragging: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragEnter: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  onClick: () => void;
  onRemove: () => void;
  disabled: boolean;
  required?: boolean;
}

function UploadCard({
  title, subtitle, icon, state, dragging,
  onDragOver, onDragEnter, onDragLeave, onDrop,
  onClick, onRemove, disabled, required,
}: UploadCardProps) {
  const { file, uploaded, uploading } = state;

  return (
    <div
      className={`border-2 border-dashed rounded-2xl p-5 text-center transition-all ${
        uploaded
          ? "border-emerald-300 bg-emerald-50/30"
          : dragging
            ? "border-blue-500 bg-blue-50/50"
            : required && !uploaded
              ? "border-amber-300 bg-amber-50/20"
              : "border-slate-300 bg-slate-50/50 hover:bg-slate-100/50"
      } ${disabled ? "opacity-60 pointer-events-none" : "cursor-pointer"}`}
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onClick={onClick}
    >
      {uploaded ? (
        <div className="flex flex-col items-center gap-2">
          <div className="w-10 h-10 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center">
            <CircleCheck size={22} />
          </div>
          <p className="text-sm text-emerald-700 font-semibold">{title} - 上传成功</p>
          <p className="text-xs text-emerald-500 truncate max-w-full">{state.path || file?.name}</p>
          {!disabled && (
            <button
              onClick={(e) => { e.stopPropagation(); onRemove(); }}
              className="text-xs text-slate-400 hover:text-red-500 transition-colors mt-1 cursor-pointer"
            >
              移除文件
            </button>
          )}
        </div>
      ) : uploading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 size={24} className="text-blue-600 animate-spin" />
          <p className="text-sm text-blue-600 font-medium">上传中...</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <div className={dragging ? "text-blue-600" : "text-slate-400"}>{icon}</div>
          <p className="text-sm text-slate-600 font-medium">
            {dragging ? "释放以上传文件" : title}
          </p>
          <p className="text-xs text-slate-400">{subtitle}</p>
          {required && (
            <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full font-medium">必需</span>
          )}
          <div className="flex items-center gap-1.5 mt-1 px-3 py-1.5 bg-white/80 rounded-lg border border-slate-200">
            <Upload size={14} className="text-slate-400" />
            <span className="text-xs text-slate-500">拖拽或点击上传 .docx</span>
          </div>
        </div>
      )}
    </div>
  );
}
