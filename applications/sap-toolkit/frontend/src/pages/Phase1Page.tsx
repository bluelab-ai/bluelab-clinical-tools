import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, FileSpreadsheet, CheckCircle2, AlertCircle,
  Loader2, Play, Eye,
} from "lucide-react";
import api from "../services/api";
import { useSSE } from "../hooks/useSSE";
import ProgressRing from "../components/ProgressRing";
import type { Project } from "../types";

const TASK_NAMES = [
  "主要评价终点", "次要评价终点", "安全性评价",
  "统计分析计划", "基线分析", "试验样本", "统计方法",
];

export default function Phase1Page() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { connect, cancel } = useSSE();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentMessage, setCurrentMessage] = useState("");
  const [taskStatuses, setTaskStatuses] = useState<Record<string, string>>({});
  const [tablesCount, setTablesCount] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [completed, setCompleted] = useState(false);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchProject = async () => {
    try {
      const res = await api.get(`/projects/${id}`);
      setProject(res.data);
      if (["catalog", "phase2", "completed"].includes(res.data.phase)) {
        navigate(`/project/${id}/catalog`);
      }
    } catch {} finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProject();
    return () => {
      cancel();
      if (redirectTimer.current) clearTimeout(redirectTimer.current);
    };
  }, [id]);

  const startWorkflow = useCallback(() => {
    if (!id) return;
    setIsRunning(true);
    setErrorMsg("");
    setProgress(0);
    setTaskStatuses({});
    setCompleted(false);

    connect(
      `/api/projects/${id}/run`,
      {},
      (data) => {
        const evt = data as any;
        const evtType = evt._eventType;

        // Handle progress events
        if (evtType === "progress" || evt.percent != null) {
          setProgress(evt.percent ?? 0);
          if (evt.message) setCurrentMessage(evt.message);
        }

        // Handle task events
        if (evtType === "task" || evt.task) {
          if (evt.task) {
            setTaskStatuses((prev) => ({ ...prev, [evt.task]: evt.status || "running" }));
          }
          if (evt.percent != null) {
            setProgress(evt.percent);
          }
        }

        // Handle phase messages
        if (evtType === "phase" && evt.message) {
          setCurrentMessage(evt.message);
        }

        // Handle completion
        if (evtType === "complete") {
          setIsRunning(false);
          setProgress(100);
          setTablesCount(evt.tables_count || 0);
          setCompleted(true);
          setCurrentMessage("目录已生成！");
          // Mark all tasks as completed
          const allDone: Record<string, string> = {};
          TASK_NAMES.forEach((t) => (allDone[t] = "completed"));
          setTaskStatuses(allDone);
          // Auto-redirect after 2 seconds
          redirectTimer.current = setTimeout(() => {
            navigate(`/project/${id}/catalog`);
          }, 2000);
        }

        // Handle errors
        if (evtType === "error") {
          setIsRunning(false);
          setErrorMsg(evt.message || "处理失败");
        }
      },
      (err) => {
        setIsRunning(false);
        setErrorMsg(err);
      },
    );
  }, [id, connect, navigate]);

  // Auto-start if project is pending
  useEffect(() => {
    if (project && project.phase === "pending" && !isRunning && !completed) {
      startWorkflow();
    }
  }, [project]);

  const statusIcon = (status: string) => {
    switch (status) {
      case "completed": return <CheckCircle2 size={16} className="text-emerald-500" />;
      case "running": return <Loader2 size={16} className="text-blue-500 animate-spin" />;
      default: return <div className="w-4 h-4 rounded-full border-2 border-slate-200" />;
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
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center gap-3">
          <button
            onClick={() => navigate("/home")}
            className="w-9 h-9 rounded-xl hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
          >
            <ArrowLeft size={20} />
          </button>
          <div className="w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center">
            <FileSpreadsheet size={18} />
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-900">{project?.name || "项目"}</h1>
            <p className="text-xs text-slate-500">阶段一：提取表格目录</p>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="bg-white rounded-2xl border border-slate-200/70 shadow-sm p-8">
          {/* Progress Section */}
          <div className="flex items-center gap-10 mb-8">
            <ProgressRing percent={progress} size={180} />
            <div className="flex-1">
              <h2 className="text-xl font-bold text-slate-900 mb-2">
                {completed ? "阶段一完成！" : isRunning ? "正在提取中..." : "准备就绪"}
              </h2>
              {currentMessage && (
                <p className={`text-sm font-medium mb-4 ${completed ? "text-emerald-600" : "text-blue-600"}`}>
                  {currentMessage}
                </p>
              )}
              {completed && tablesCount > 0 && (
                <p className="text-sm text-slate-500 mb-4">
                  已生成 {tablesCount} 张表格，即将跳转到目录编辑页...
                </p>
              )}
              <div className="space-y-2.5">
                {TASK_NAMES.map((name) => (
                  <div key={name} className="flex items-center gap-2.5">
                    {statusIcon(taskStatuses[name] || "")}
                    <span className={`text-sm ${
                      taskStatuses[name] === "completed" ? "text-emerald-600" :
                      taskStatuses[name] === "running" ? "text-blue-600 font-medium" :
                      "text-slate-400"
                    }`}>
                      {name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Error */}
          {errorMsg && (
            <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
              <AlertCircle size={16} /> {errorMsg}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            {completed && (
              <button
                onClick={() => navigate(`/project/${id}/catalog`)}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
              >
                <Eye size={18} /> 查看目录
              </button>
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

        {/* File Info */}
        <div className="mt-6 grid grid-cols-2 gap-4">
          <div className="p-4 bg-white rounded-2xl border border-slate-200/70 shadow-sm">
            <span className="text-xs text-slate-400">SAP 文件</span>
            <p className="text-sm font-medium text-slate-800 mt-1">{project?.sap_filename}</p>
          </div>
          <div className="p-4 bg-white rounded-2xl border border-slate-200/70 shadow-sm">
            <span className="text-xs text-slate-400">CRF 文件</span>
            <p className="text-sm font-medium text-slate-800 mt-1">{project?.crf_filename || "未上传"}</p>
          </div>
        </div>
      </main>
    </div>
  );
}
