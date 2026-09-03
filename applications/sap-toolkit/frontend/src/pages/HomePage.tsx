import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import api from "../services/api";
import {
  LogOut, FileSpreadsheet, Clock, CheckCircle2, AlertCircle,
  Loader2, ChevronRight, Play, RotateCcw, RefreshCw, Trash2,
} from "lucide-react";
import type { Project } from "../types";
import UploadCard from "../components/UploadCard";

export default function HomePage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  // Upload state
  const [projectName, setProjectName] = useState("");
  const [sapFile, setSapFile] = useState<File | null>(null);
  const [crfFile, setCrfFile] = useState<File | null>(null);
  const [sapUploaded, setSapUploaded] = useState(false);
  const [crfUploaded, setCrfUploaded] = useState(false);
  const [sapPath, setSapPath] = useState("");
  const [crfPath, setCrfPath] = useState("");
  const [uploading, setUploading] = useState<"sap" | "crf" | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const fetchProjects = async () => {
    try {
      const res = await api.get("/projects");
      setProjects(res.data);
    } catch {} finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProjects(); }, []);

  const uploadFile = async (file: File, category: "sap" | "crf") => {
    const setters = category === "sap"
      ? { file: setSapFile, uploaded: setSapUploaded, path: setSapPath }
      : { file: setCrfFile, uploaded: setCrfUploaded, path: setCrfPath };

    setters.file(file);
    setUploading(category);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("category", category);
    try {
      const res = await api.post("/files/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setters.uploaded(true);
      setters.path(res.data.path || file.name);
    } catch (err: any) {
      alert("上传失败: " + (err.response?.data?.detail || "请重试"));
      setters.file(null);
    } finally {
      setUploading(null);
    }
  };

  const removeFile = (category: "sap" | "crf") => {
    if (category === "sap") {
      setSapFile(null); setSapUploaded(false); setSapPath("");
    } else {
      setCrfFile(null); setCrfUploaded(false); setCrfPath("");
    }
  };

  const handleCreate = async () => {
    if (!sapUploaded || !projectName.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      const res = await api.post("/projects", {
        name: projectName.trim(),
        sap_path: sapPath,
        crf_path: crfPath || null,
      });
      // Navigate to phase1 page
      navigate(`/project/${res.data.id}/phase1`);
    } catch (err: any) {
      setCreateError(err.response?.data?.detail || "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const getPhaseRoute = (p: Project) => {
    switch (p.phase) {
      case "phase1": return `/project/${p.id}/phase1`;
      case "catalog": return `/project/${p.id}/catalog`;
      case "prompts": return `/project/${p.id}/prompts`;
      case "phase2": return `/project/${p.id}/phase2`;
      case "review": return `/project/${p.id}/review`;
      case "completed": return `/project/${p.id}/review`;
      default: return `/project/${p.id}/phase1`;
    }
  };

  const phaseLabel = (p: Project) => {
    switch (p.phase) {
      case "phase1": return "阶段一进行中";
      case "catalog": return "待生成表格";
      case "prompts": return "编辑 Prompt";
      case "phase2": return "提取指标中";
      case "review": return "待审核指标";
      case "completed": return "已完成";
      default: return p.status === "running" ? "处理中" : "待处理";
    }
  };

  const handleLogout = () => { logout(); navigate("/login"); };

  const handleReset = async (e: React.MouseEvent, projectId: number) => {
    e.stopPropagation();
    try {
      await api.post(`/projects/${projectId}/reset`);
      fetchProjects();
    } catch {}
  };

  const handleDelete = async (e: React.MouseEvent, projectId: number, projectName: string) => {
    e.stopPropagation();
    if (!confirm(`确定要删除项目「${projectName}」吗？此操作不可撤销。`)) return;
    try {
      await api.delete(`/projects/${projectId}`);
      fetchProjects();
    } catch (err: any) {
      alert("删除失败: " + (err.response?.data?.detail || "请重试"));
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/70 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <FileSpreadsheet size={18} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">SAP Toolkit</h1>
              <p className="text-xs text-slate-500">统计分析计划工具包</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-500">
              欢迎，<span className="font-semibold text-slate-700">{user?.username}</span>
            </span>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-red-500 transition-colors cursor-pointer"
            >
              <LogOut size={16} /> 退出
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-12">
        {/* Upload Section */}
        <div className="bg-white rounded-2xl border border-slate-200/70 shadow-sm p-8 mb-10">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <Play size={20} />
            </div>
            <div>
              <h2 className="text-xl font-bold text-slate-900">新建项目</h2>
              <p className="text-sm text-slate-500">上传 SAP PDF 开始提取表格目录</p>
            </div>
          </div>

          <div className="space-y-4 mb-6">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">项目名称</label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="例如：奇致 SAP 提取"
                className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-1.5">
                  SAP 文件 <span className="text-red-400">*</span>
                </label>
                <UploadCard
                  label="上传 SAP PDF"
                  accept=".pdf"
                  uploaded={sapUploaded}
                  uploading={uploading === "sap"}
                  filename={sapFile?.name || ""}
                  onUpload={(f) => uploadFile(f, "sap")}
                  onRemove={() => removeFile("sap")}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-1.5">
                  CRF 文件 <span className="text-slate-400 text-xs font-normal">（可选，阶段二需要）</span>
                </label>
                <UploadCard
                  label="上传 CRF PDF"
                  accept=".pdf"
                  uploaded={crfUploaded}
                  uploading={uploading === "crf"}
                  filename={crfFile?.name || ""}
                  onUpload={(f) => uploadFile(f, "crf")}
                  onRemove={() => removeFile("crf")}
                />
              </div>
            </div>
          </div>

          {createError && (
            <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
              {createError}
            </div>
          )}

          <button
            onClick={handleCreate}
            disabled={!sapUploaded || !projectName.trim() || creating}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {creating ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
            {creating ? "创建中..." : "生成目录"}
          </button>
        </div>

        {/* Project List */}
        <div className="mb-6">
          <h2 className="text-xl font-bold text-slate-900 mb-1">我的项目</h2>
          <p className="text-slate-500 text-sm">点击项目卡片继续处理</p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={32} className="text-blue-500 animate-spin" />
          </div>
        ) : projects.length === 0 ? (
          <div className="text-center py-16">
            <FileSpreadsheet size={48} className="text-slate-300 mx-auto mb-4" />
            <p className="text-slate-500 text-lg font-medium mb-2">暂无项目</p>
            <p className="text-slate-400 text-sm">上传 SAP PDF 开始您的第一个提取任务</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {projects.map((p, idx) => (
              <div
                key={p.id}
                onClick={() => navigate(getPhaseRoute(p))}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") navigate(getPhaseRoute(p)); }}
                className="card-enter text-left p-5 bg-white rounded-2xl border border-slate-200/70 shadow-sm hover:border-blue-400 hover:shadow-md hover:-translate-y-0.5 transition-all cursor-pointer active:scale-[0.99]"
                style={{ animationDelay: `${idx * 60}ms` }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-11 h-11 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
                      <FileSpreadsheet size={20} />
                    </div>
                    <div>
                      <h3 className="font-bold text-slate-900">{p.name}</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        {p.sap_filename}
                        {p.crf_filename && <span className="text-slate-400"> + {p.crf_filename}</span>}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1.5">
                      {p.status === "completed" && p.phase === "completed" ? (
                        <CheckCircle2 size={16} className="text-emerald-500" />
                      ) : p.status === "running" ? (
                        <Loader2 size={16} className="text-blue-500 animate-spin" />
                      ) : p.status === "failed" ? (
                        <AlertCircle size={16} className="text-red-500" />
                      ) : (
                        <Clock size={16} className="text-slate-400" />
                      )}
                      <span className="text-sm text-slate-600">{phaseLabel(p)}</span>
                    </div>
                    {(p.status === "running" || p.status === "failed") && (
                      <button
                        onClick={(e) => handleReset(e, p.id)}
                        className="w-8 h-8 rounded-lg hover:bg-amber-100 flex items-center justify-center text-slate-400 hover:text-amber-600 transition-colors cursor-pointer"
                        title="重置状态"
                      >
                        <RefreshCw size={14} />
                      </button>
                    )}
                    <button
                      onClick={(e) => handleDelete(e, p.id, p.name)}
                      className="w-8 h-8 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-400 hover:text-red-600 transition-colors cursor-pointer"
                      title="删除项目"
                    >
                      <Trash2 size={14} />
                    </button>
                    {p.tables_count != null && (
                      <span className="text-xs bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full font-semibold">
                        {p.tables_count} 张表格
                      </span>
                    )}
                    <ChevronRight size={18} className="text-slate-300" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
