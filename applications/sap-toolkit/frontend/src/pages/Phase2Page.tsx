import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, FileSpreadsheet, CheckCircle2, AlertCircle,
  Loader2, Play, Download, RotateCcw,
} from "lucide-react";
import api from "../services/api";
import { useSSE } from "../hooks/useSSE";
import ProgressRing from "../components/ProgressRing";
import type { Project } from "../types";

export default function Phase2Page() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { connect, cancel } = useSSE();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentPhase, setCurrentPhase] = useState("");
  const [phaseMessages, setPhaseMessages] = useState<string[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [completed, setCompleted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchProject = async () => {
    try {
      const res = await api.get(`/projects/${id}`);
      setProject(res.data);
      if (res.data.phase === "completed") {
        setCompleted(true);
      }
    } catch {} finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProject();
    return () => cancel();
  }, [id]);

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [phaseMessages]);

  const startWorkflow = () => {
    if (!id) return;
    setIsRunning(true);
    setErrorMsg("");
    setProgress(0);
    setPhaseMessages([]);
    setCompleted(false);

    connect(
      `/api/projects/${id}/run-phase2a`,
      {},
      (data) => {
        const evt = data as any;
        if (evt._eventType === "progress" && evt.percent !== undefined) {
          setProgress(evt.percent);
          if (evt.node) setCurrentPhase(evt.node);
        }
        if (evt._eventType === "phase" && evt.message) {
          setCurrentPhase(evt.message);
          setPhaseMessages((prev) => [...prev, evt.message]);
        }
        if (evt._eventType === "complete") {
          setIsRunning(false);
          setProgress(100);
          setCompleted(true);
          setCurrentPhase(evt.message || "完成");
          setPhaseMessages((prev) => [...prev, "✅ " + (evt.message || "指标提取完成")]);
          // 自动跳转到审核页面
          setTimeout(() => navigate(`/project/${id}/review`), 1000);
        }
        if (evt._eventType === "error") {
          setIsRunning(false);
          setErrorMsg(evt.message || "处理失败");
        }
      },
      (err) => {
        setIsRunning(false);
        setErrorMsg(err);
      },
    );
  };

  const handleDownload = async (type: string) => {
    try {
      const token = localStorage.getItem("token");
      const res = await fetch(`/api/projects/${id}/download/${type}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "下载失败" }));
        alert(err.detail || "下载失败");
        return;
      }
      const blob = await res.blob();
      const ext = type === "docx" ? ".docx" : type === "markdown" ? ".md" : ".json";
      const filename = `${project?.name || "result"}${ext}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      alert("下载失败");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <Loader2 size={32} className="text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/70 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(`/project/${id}/catalog`)}
              className="w-9 h-9 rounded-xl hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <FileSpreadsheet size={18} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">{project?.name}</h1>
              <p className="text-xs text-slate-500">阶段二：提取指标</p>
            </div>
          </div>
          {completed && (
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate(`/project/${id}/review`)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors cursor-pointer"
              >
                <FileSpreadsheet size={16} /> 进入审核
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="bg-white rounded-2xl border border-slate-200/70 shadow-sm p-8">
          {/* Progress */}
          <div className="flex items-center gap-10 mb-8">
            <ProgressRing percent={progress} size={180} />
            <div className="flex-1">
              <h2 className="text-xl font-bold text-slate-900 mb-2">
                {completed ? "指标提取完成！" : isRunning ? "正在提取指标..." : "准备就绪"}
              </h2>
              {currentPhase && (
                <p className={`text-sm font-medium mb-2 ${completed ? "text-emerald-600" : "text-blue-600"}`}>
                  {currentPhase}
                </p>
              )}
              {!isRunning && !completed && (
                <p className="text-sm text-slate-500">
                  从 CRF 文档中提取各表格的指标项目，提取完成后进入审核编辑页面
                </p>
              )}
              {completed && (
                <div className="flex items-center gap-2 mt-3">
                  <CheckCircle2 size={20} className="text-emerald-500" />
                  <span className="text-sm text-emerald-600 font-medium">指标提取完成，正在跳转审核页面...</span>
                </div>
              )}
            </div>
          </div>

          {/* Log Messages */}
          {phaseMessages.length > 0 && (
            <div className="mb-6 max-h-48 overflow-y-auto custom-scrollbar bg-slate-50 rounded-xl p-4 space-y-1">
              {phaseMessages.map((msg, i) => (
                <p key={i} className="text-xs text-slate-600 font-mono">{msg}</p>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}

          {/* Error */}
          {errorMsg && (
            <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
              <AlertCircle size={16} /> {errorMsg}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            {!isRunning && !completed && (
              <button
                onClick={startWorkflow}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
              >
                <Play size={18} /> 开始提取
              </button>
            )}
            {completed && (
              <>
                <button
                  onClick={() => navigate(`/project/${id}/catalog`)}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-slate-200 text-slate-600 font-semibold hover:bg-slate-50 transition-all cursor-pointer"
                >
                  <RotateCcw size={18} /> 返回目录编辑
                </button>
                <button
                  onClick={() => navigate(`/project/${id}/review`)}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
                >
                  <FileSpreadsheet size={18} /> 进入审核编辑
                </button>
              </>
            )}
            {errorMsg && !isRunning && (
              <button
                onClick={startWorkflow}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
              >
                <Play size={18} /> 重试
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
