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
  ToggleLeft,
  ToggleRight,
  Eye,
  Download,
  AlertCircle,
  ListChecks,
  FileWarning,
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

export default function TFLListingQCPage() {
  const navigate = useNavigate();
  const { connect, cancel } = useSSE();

  // Upload states
  const [tableUpload, setTableUpload] = useState<UploadState>({
    file: null, uploaded: false, uploading: false, path: "",
  });
  const [listingUpload, setListingUpload] = useState<UploadState>({
    file: null, uploaded: false, uploading: false, path: "",
  });

  // QC states
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [completedPairs, setCompletedPairs] = useState(0);
  const [totalPairs, setTotalPairs] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [qcComplete, setQcComplete] = useState(false);
  const [resultFiles, setResultFiles] = useState<string[]>([]);

  // Manual QC toggle
  const [manualQC, setManualQC] = useState(false);

  // Temp folder lifecycle
  const [tempDir, setTempDir] = useState("");
  const [tempId, setTempId] = useState("");
  const [tempReady, setTempReady] = useState(false);  // temp folder 就绪前禁用所有操作
  const tempDirRef = useRef("");  // ref for beforeunload closure safety

  // Human review pending — 人工审核模式下 HTML 已生成、等待用户审核
  const [reviewPending, setReviewPending] = useState(false);
  const reviewPendingRef = useRef(false);  // ref 解决 SSE 闭包陈旧问题

  // SSE 回调中读取进度值的 ref（解决 startQC/resumeQC 内联闭包陈旧问题）
  const completedRef = useRef(0);
  const totalRef = useRef(0);
  const progressRef = useRef(0);

  // Human review states
  const [reviewJsonState, setReviewJsonState] = useState<UploadState>({
    file: null, uploaded: false, uploading: false, path: "",
  });
  const [sessionId, setSessionId] = useState("");
  const [projectDir, setProjectDir] = useState("");
  const reviewJsonInputRef = useRef<HTMLInputElement>(null);

  // Drag states
  const [tableDragging, setTableDragging] = useState(false);
  const [listingDragging, setListingDragging] = useState(false);
  const tableInputRef = useRef<HTMLInputElement>(null);
  const listingInputRef = useRef<HTMLInputElement>(null);

  // ── Temp folder lifecycle ─────────────────────────────────────────────

  // On mount: create temp folder
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

  // ── 清理函数（beforeunload + 组件卸载共用） ──
  const cleanupTempFolder = () => {
    const dir = tempDirRef.current;
    if (!dir) return;
    const blob = new Blob(
      [JSON.stringify({ temp_dir: dir })],
      { type: "application/json" },
    );
    if (navigator.sendBeacon) {
      // sendBeacon 专为页面卸载场景设计，比 fetch keepalive 可靠
      navigator.sendBeacon("/api/qc/cleanup", blob);
    }
  };

  useEffect(() => {
    window.addEventListener("beforeunload", cleanupTempFolder);
    return () => {
      window.removeEventListener("beforeunload", cleanupTempFolder);
      cleanupTempFolder();  // React 路由导航离开时也清理
    };
  }, []);

  // ── 共享 SSE 回调（ref 驱动，解决闭包陈旧） ─────────────────────────

  const buildSSECallback = (isResume: boolean) => {
    return {
      onEvent: (data: Record<string, unknown>) => {
        const eventType = data._eventType || data.type;

        switch (eventType) {
          case "total_pairs":
            totalRef.current = (data.total as number) || 0;
            setTotalPairs(totalRef.current);
            break;

          case "review_html_ready":
            if (isResume) break;  // 继续模式不会触发此事件
            if (data.session_id) setSessionId(data.session_id as string);
            if (data.project_dir) setProjectDir(data.project_dir as string);
            if (data.html_url) {
              window.open(data.html_url as string, "_blank", "noopener");
            }
            setProgressText("等待人工审核...");
            setReviewPending(true);
            reviewPendingRef.current = true;
            setIsRunning(false);
            break;

          case "pair_progress":
            if (data.completed !== undefined) {
              completedRef.current = data.completed as number;
              setCompletedPairs(completedRef.current);
            }
            if (data.total !== undefined && (data.total as number) > 0) {
              totalRef.current = data.total as number;
              setTotalPairs(totalRef.current);
            }
            if (data.percent !== undefined) {
              progressRef.current = data.percent as number;
              setProgress(progressRef.current);
            }
            setProgressText(`正在核查 Pair ${completedRef.current}/${totalRef.current}`);
            break;

          case "progress":
            if (data.percent !== undefined) {
              progressRef.current = data.percent as number;
              setProgress(progressRef.current);
            }
            if (data.text) setProgressText(data.text as string);
            break;

          case "warning":
            // 静默忽略（修订标记等非阻断性提醒）
            break;

          case "error":
            setErrorMsg((data.content as string) || "质控过程发生错误");
            setIsRunning(false);
            break;

          case "done":
            if (!reviewPendingRef.current) {
              progressRef.current = 100;
              setProgress(100);
              setProgressText("质控完成");
              setQcComplete(true);
              setIsRunning(false);
              if (data.session_id) setSessionId(data.session_id as string);
            }
            if (data.files) setResultFiles(data.files as string[]);
            break;
        }
      },
      onError: (error: string) => {
        setErrorMsg(error);
        setIsRunning(false);
      },
    };
  };

  // Upload a file
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

  // Upload reviewed JSON to resume workflow
  const uploadReviewedJson = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);
    setReviewJsonState((prev) => ({ ...prev, uploading: true }));
    try {
      const res = await api.post("/qc/upload-reviewed-json", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setReviewJsonState((prev) => ({
        ...prev, uploaded: true, uploading: false,
        path: res.data.path || res.data.filename || file.name,
      }));
    } catch (err: any) {
      setReviewJsonState((prev) => ({ ...prev, uploading: false }));
      alert("上传复核结果失败: " + (err.response?.data?.detail || "请重试"));
    }
  };

  // Start QC workflow
  const startQC = () => {
    if (!tableUpload.uploaded || !listingUpload.uploaded) {
      setErrorMsg("请先上传表格文件和清单文件");
      return;
    }
    setIsRunning(true);
    setProgress(0);
    progressRef.current = 0;
    setCompletedPairs(0);
    completedRef.current = 0;
    setTotalPairs(0);
    totalRef.current = 0;
    setErrorMsg("");
    setQcComplete(false);
    setResultFiles([]);
    setProgressText("正在启动...");
    setReviewPending(false);
    reviewPendingRef.current = false;
    setSessionId("");
    setProjectDir("");
    setReviewJsonState({ file: null, uploaded: false, uploading: false, path: "" });

    const { onEvent, onError } = buildSSECallback(false);
    connect(
      "/api/qc/table-listing-cross",
      {
        table_path: tableUpload.path,
        listing_path: listingUpload.path,
        manual_qc: manualQC,
        project_dir: tempDirRef.current,
      },
      onEvent,
      onError,
    );
  };

  const cancelQC = () => {
    cancel();
    setIsRunning(false);
    setReviewPending(false);
    reviewPendingRef.current = false;
    setProgress(0);
    progressRef.current = 0;
    setCompletedPairs(0);
    completedRef.current = 0;
    setTotalPairs(0);
    totalRef.current = 0;
    setProgressText("已取消");
    setSessionId("");
    setProjectDir("");
    setReviewJsonState({ file: null, uploaded: false, uploading: false, path: "" });
  };

  // 人工审核完成后继续质控（Phase 2→4）
  const resumeQC = () => {
    setIsRunning(true);
    setProgress(0);
    progressRef.current = 0;
    setCompletedPairs(0);
    completedRef.current = 0;
    setTotalPairs(0);
    totalRef.current = 0;
    setErrorMsg("");
    setQcComplete(false);
    setResultFiles([]);
    setReviewPending(false);
    reviewPendingRef.current = false;
    setProgressText("正在继续质控...");

    const { onEvent, onError } = buildSSECallback(true);
    connect(
      "/api/qc/table-listing-cross",
      {
        table_path: tableUpload.path,
        listing_path: listingUpload.path,
        manual_qc: manualQC,
        project_dir: projectDir,  // 复用已有项目目录
      },
      onEvent,
      onError,
    );
  };

  const resetQC = () => {
    setProgress(0);
    progressRef.current = 0;
    setProgressText("");
    setCompletedPairs(0);
    completedRef.current = 0;
    setTotalPairs(0);
    totalRef.current = 0;
    setQcComplete(false);
    setErrorMsg("");
    setResultFiles([]);
    setReviewPending(false);
    reviewPendingRef.current = false;
    setSessionId("");
    setProjectDir("");
    setReviewJsonState({ file: null, uploaded: false, uploading: false, path: "" });
  };

  const canStart = tableUpload.uploaded && listingUpload.uploaded && !isRunning && tempReady;

  // ── Circular progress ring calculations ──
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
                <h1 className="text-lg font-bold text-slate-900">表格清单一致性质控</h1>
                <p className="text-xs text-slate-500">Table-Listing Cross-Validation QC</p>
              </div>
            </div>
          </div>
          {/* Manual QC Toggle */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-600 font-medium">人工审核模式</span>
            <button
              onClick={() => setManualQC(!manualQC)}
              disabled={isRunning}
              className={`transition-colors cursor-pointer ${isRunning ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              {manualQC ? (
                <ToggleRight size={32} className="text-blue-600" />
              ) : (
                <ToggleLeft size={32} className="text-slate-300" />
              )}
            </button>
            {manualQC && (
              <span className="text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full font-medium">
                启用人工审核匹配结果
              </span>
            )}
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
                <ListChecks size={18} className="text-blue-600" />
                质控进度
              </h3>

              {/* Circular Progress Ring */}
              <div className="flex flex-col items-center">
                <div className="relative w-56 h-56 mb-6">
                  {/* Background ring */}
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
                      stroke={
                        qcComplete ? "#10b981" : reviewPending ? "#f59e0b" : "#2563eb"
                      }
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={ringCircumference}
                      strokeDashoffset={reviewPending ? ringCircumference : ringOffset}
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
                    ) : reviewPending ? (
                      <>
                        <Eye size={32} className="text-amber-500 mb-1" />
                        <span className="text-xl font-bold text-amber-600">等待审核</span>
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

                {/* Pair counter */}
                {totalPairs > 0 && !reviewPending && (
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    <ListChecks size={16} />
                    <span>
                      已完成{" "}
                      <span className="font-semibold text-slate-700">{completedPairs}</span>
                      {" / "}
                      <span className="font-semibold text-slate-700">{totalPairs}</span>
                      {" "}个 QC 对
                    </span>
                  </div>
                )}

                {/* Review pending pair count */}
                {reviewPending && totalPairs > 0 && (
                  <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 px-4 py-2 rounded-xl">
                    <AlertCircle size={16} />
                    <span>
                      共 <span className="font-semibold">{totalPairs}</span> 个 QC 对待审核完成后继续
                    </span>
                  </div>
                )}

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
              {/* 人工审核暂停中：单一按钮 */}
              {reviewPending && (
                <button
                  onClick={resumeQC}
                  disabled={!reviewJsonState.uploaded}
                  className={`flex-1 py-4 rounded-2xl font-bold text-white shadow-sm transition-all flex items-center justify-center gap-2 ${
                    reviewJsonState.uploaded
                      ? "bg-blue-600 hover:bg-blue-700 active:scale-[0.98] cursor-pointer"
                      : "bg-slate-300 cursor-not-allowed"
                  }`}
                >
                  <Upload size={20} />
                  {reviewJsonState.uploaded ? "继续质控" : "请先上传审核结果"}
                </button>
              )}

              {/* 初始状态 */}
              {!isRunning && !qcComplete && !reviewPending && (
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
                  点击进行表格清单一致性质控
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
                          const res = await api.get(`/qc/download-tfl-report/${sessionId}`, { responseType: "blob" });
                          const blob = new Blob([res.data], { type: "text/html" });
                          const url = window.URL.createObjectURL(blob);
                          const link = document.createElement("a");
                          link.href = url;
                          link.download = "表格清单一致性质控报告.html";
                          document.body.appendChild(link);
                          link.click();
                          document.body.removeChild(link);
                          window.URL.revokeObjectURL(url);
                        } catch {
                          // fallback: 直接打开
                          window.open(`/api/qc/download-tfl-report/${sessionId}`, "_blank");
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
            {/* Temp folder not ready yet — show loading */}
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

            {/* Table Upload */}
            <UploadCard
              title="上传表格文件"
              subtitle="Tables"
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

            {/* Listing Upload */}
            <UploadCard
              title="上传清单文件"
              subtitle="Listings"
              icon={<FileWarning size={22} />}
              state={listingUpload}
              dragging={listingDragging}
              onDragOver={(e) => { e.preventDefault(); setListingDragging(true); }}
              onDragEnter={(e) => { e.preventDefault(); setListingDragging(true); }}
              onDragLeave={() => setListingDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setListingDragging(false);
                if (e.dataTransfer.files[0]) {
                  const file = e.dataTransfer.files[0];
                  setListingUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "listing", (updater) => setListingUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
              onClick={() => !isRunning && listingInputRef.current?.click()}
              onRemove={() => removeFile((updater) => setListingUpload((prev) => ({ ...prev, ...updater(prev) })))}
              disabled={isRunning || !tempReady}
            />
            <input ref={listingInputRef} type="file" hidden accept=".docx"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  const file = e.target.files[0];
                  setListingUpload((prev) => ({ ...prev, file }));
                  uploadFile(file, "listing", (updater) => setListingUpload((prev) => ({ ...prev, ...updater(prev) })));
                }
              }}
            />

            {/* Reviewed JSON Upload — only visible when manual QC is on */}
            {manualQC && (
              <UploadCard
                title="上传人工审核匹配结果"
                subtitle="Reviewed JSON"
                icon={<Upload size={22} />}
                state={reviewJsonState}
                dragging={false}
                onDragOver={(e) => { e.preventDefault(); }}
                onDragEnter={(e) => { e.preventDefault(); }}
                onDragLeave={() => {}}
                onDrop={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer.files[0]) {
                    const file = e.dataTransfer.files[0];
                    setReviewJsonState((prev) => ({ ...prev, file }));
                    uploadReviewedJson(file);
                  }
                }}
                onClick={() => reviewJsonInputRef.current?.click()}
                onRemove={() => {
                  setReviewJsonState({ file: null, uploaded: false, uploading: false, path: "" });
                }}
                disabled={false}
              />
            )}
            <input
              ref={reviewJsonInputRef}
              type="file"
              hidden
              accept=".json"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  const file = e.target.files[0];
                  setReviewJsonState((prev) => ({ ...prev, file }));
                  uploadReviewedJson(file);
                }
              }}
            />

            {/* Status note when manual QC is on */}
            {manualQC && !sessionId && (
              <div className="bg-amber-50/50 rounded-2xl border border-amber-100/50 p-4">
                <p className="text-xs text-amber-700">
                  开启人工审核模式后，系统会先自动生成匹配复核页面供您审查。
                  审查完成后，将导出的 JSON 文件通过上方上传栏上传，管线将自动继续执行。
                </p>
              </div>
            )}

            {/* Review in progress indicator */}
            {manualQC && sessionId && !reviewJsonState.uploaded && (
              <div className="bg-blue-50/50 rounded-2xl border border-blue-100/50 p-4 flex items-start gap-3">
                <Loader2 size={18} className="text-blue-600 animate-spin flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-semibold text-slate-900 mb-1">等待人工审核</h4>
                  <p className="text-xs text-slate-600">
                    复核页面已在新标签页中打开。审查完成后，请导出
                    <code className="bg-blue-100 px-1 rounded">表格-清单-映射表-已复核.json</code>
                    ，并通过上方上传栏上传以继续管线。
                  </p>
                </div>
              </div>
            )}

            {/* Review JSON uploaded successfully */}
            {manualQC && reviewJsonState.uploaded && (
              <div className="bg-emerald-50/50 rounded-2xl border border-emerald-100/50 p-4 flex items-start gap-3">
                <CircleCheck size={18} className="text-emerald-500 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-semibold text-emerald-700 mb-1">复核结果已上传</h4>
                  <p className="text-xs text-emerald-600">
                    管线正在继续执行 Phase 2-4，请关注左侧进度更新。
                  </p>
                </div>
              </div>
            )}
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
}

function UploadCard({
  title, subtitle, icon, state, dragging,
  onDragOver, onDragEnter, onDragLeave, onDrop,
  onClick, onRemove, disabled,
}: UploadCardProps) {
  const { file, uploaded, uploading } = state;

  return (
    <div
      className={`border-2 border-dashed rounded-2xl p-5 text-center transition-all ${
        uploaded
          ? "border-emerald-300 bg-emerald-50/30"
          : dragging
            ? "border-blue-500 bg-blue-50/50"
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
          <div className="flex items-center gap-1.5 mt-1 px-3 py-1.5 bg-white/80 rounded-lg border border-slate-200">
            <Upload size={14} className="text-slate-400" />
            <span className="text-xs text-slate-500">拖拽或点击上传 .docx</span>
          </div>
        </div>
      )}
    </div>
  );
}
