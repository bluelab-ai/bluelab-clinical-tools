import { useState, useEffect, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Save, MessageSquare, FolderOpen, Trash2, HelpCircle } from "lucide-react";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { useProject } from "../hooks/useProject";

const FORM_FIELDS = [
  { key: "DMP版本号", type: "text", placeholder: "示例：V0.1" },
  { key: "DMP版本日期", type: "date", placeholder: "示例：2026-04-02" },
  { key: "临床监查方名称", type: "text", placeholder: "示例：ABC科技有限公司" },
  { key: "统计分析方名称", type: "text", placeholder: "示例：北京大学临床研究所" },
  { key: "版本修订记录", type: "text", placeholder: "示例：初稿" },
  { key: "撰写者/修订者", type: "text", placeholder: "示例：小张" },
  { key: "数据管理单位审核人", type: "text", placeholder: "示例：小李" },
  { key: "申办者审核人", type: "text", placeholder: "示例：小王" },
  { key: "CRO审核人", type: "text", placeholder: "示例：小赵" },
  { key: "统计分析单位审核人", type: "text", placeholder: "示例：小孙" },
  { key: "项目类型：药物 / 器械", type: "select", options: ["药物项目", "器械项目"] },
  { key: "项目数据采集模式：EDC / PDC", type: "select", options: ["EDC", "PDC"] },
  { key: "EDC系统供应商/系统类型", type: "select", options: ["赛美斯系统", "青蜂系统", "里恩系统", "太美系统V5", "太美系统V6", "易迪希系统", "其他"], dependsOn: { key: "项目数据采集模式：EDC / PDC", value: "EDC" } },
  { key: "EDC其他系统供应商名称", type: "text", placeholder: "示例：供应商A", dependsOn: { key: "EDC系统供应商/系统类型", value: "其他" } },
  { key: "EDC其他系统名称", type: "text", placeholder: "示例：系统A", dependsOn: { key: "EDC系统供应商/系统类型", value: "其他" } },
  { key: "EDC其他系统维护负责方", type: "text", placeholder: "示例：维护方A", dependsOn: { key: "EDC系统供应商/系统类型", value: "其他" } },
  { key: "EDC其他系统版本号", type: "text", placeholder: "示例：V1", dependsOn: { key: "EDC系统供应商/系统类型", value: "其他" } },
  { key: "EDC其他系统服务器地址", type: "text", placeholder: "示例：www.123.com", dependsOn: { key: "EDC系统供应商/系统类型", value: "其他" } },
  { key: "是否使用登记系统", type: "select", options: ["是", "否"] },
  { key: "是否使用随机系统", type: "select", options: ["是", "否"] },
  { key: "随机系统供应商/系统类型", type: "select", options: ["医墨随机系统", "易迪希随机系统", "赛美斯随机系统", "其他"], dependsOn: { key: "是否使用随机系统", value: "是" } },
  { key: "随机其他系统供应商名称", type: "text", placeholder: "示例：供应商B", dependsOn: { key: "随机系统供应商/系统类型", value: "其他" } },
  { key: "随机其他系统搭建负责方", type: "text", placeholder: "示例：搭建负责方B", dependsOn: { key: "随机系统供应商/系统类型", value: "其他" } },
  { key: "随机其他系统维护负责方", type: "text", placeholder: "示例：维护负责方B", dependsOn: { key: "随机系统供应商/系统类型", value: "其他" } },
  { key: "随机其他系统版本号", type: "text", placeholder: "示例：V1", dependsOn: { key: "随机系统供应商/系统类型", value: "其他" } },
  { key: "随机其他系统服务器地址", type: "text", placeholder: "示例：www.456.com", dependsOn: { key: "随机系统供应商/系统类型", value: "其他" } },
  { key: "是否涉及外部数据", type: "select", options: ["是", "否"] },
  { key: "设计的外部数据类型", type: "text", placeholder: "示例：中心实验室电子化数据（Central Lab Data）、中心阅片数据（Imaging Data）", dependsOn: { key: "是否涉及外部数据", value: "是" } },
  { key: "是否涉及医学编码", type: "select", options: ["是", "否"] },
  { key: "是否涉及针对有药物警戒系统的项目", type: "select", options: ["是", "否"] },
  { key: "是否有阶段性分析/中期分析", type: "select", options: ["是", "否"] },
  { key: "阶段性分析目的和阶段要求", type: "text", placeholder: "示例：目的为年中安全性评估；阶段为入组满 50 例受试者；触发时间点为第 50 例受试者入组后满 28 天", dependsOn: { key: "是否有阶段性分析/中期分析", value: "是" } },
  { key: "是否需要预递交", type: "select", options: ["是", "否"] },
  { key: "是否需要数据管理报告", type: "select", options: ["是", "否"] },
  { key: "是否包含向申办者数据递交服务范围", type: "select", options: ["是", "否"] },
  { key: "项目质量控制等级/模板", type: "select", options: ["高标准项目", "低标准项目"] },
];

export default function LogFormPage() {
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [projects, setProjects] = useState<string[]>([]);
  const [showNewInput, setShowNewInput] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const navigate = useNavigate();
  const { user } = useAuth();
  const { project, setProject } = useProject();

  // Fetch available projects
  useEffect(() => {
    api.get("/projects").then((res) => {
      const list: string[] = res.data.projects || [];
      setProjects(list.includes(project) ? list : [...list, project]);
    }).catch(() => {});
  }, [project]);

  // Load log data on mount and when project switches
  useEffect(() => {
    api.get("/log/current").then((res) => {
      if (res.data.latest) {
        setFormData(res.data.latest);
      } else {
        setFormData({});
      }
    }).catch(() => {});
  }, [project]);

  const handleProjectSelect = (name: string) => {
    if (name === "__new__") {
      setShowNewInput(true);
      setNewProjectName("");
    } else if (name !== project) {
      setProject(name);
    }
  };

  const handleCreateProject = () => {
    const trimmed = newProjectName.trim();
    if (trimmed && trimmed !== project) {
      setProject(trimmed);
    }
    setShowNewInput(false);
    setNewProjectName("");
  };

  const handleDeleteProject = async () => {
    if (project === "default") return;
    if (!confirm(`Delete project "${project}" and all its files? This cannot be undone.`)) return;
    try {
      await api.delete(`/projects/${project}`);
      const remaining = projects.filter((p) => p !== project);
      setProject(remaining.length > 0 ? remaining[0] : "default");
    } catch (err: any) {
      alert("Delete failed: " + (err.response?.data?.detail || "Error"));
    }
  };

  const handleChange = (key: string, value: string) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const isVisible = (field: typeof FORM_FIELDS[0]) => {
    if (!field.dependsOn) return true;
    if (formData[field.dependsOn.key] !== field.dependsOn.value) return false;
    const parent = FORM_FIELDS.find((f) => f.key === field.dependsOn!.key);
    if (!parent) return true;
    return isVisible(parent);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      // Check if identical to latest entry
      const curr = await api.get("/log/current");
      const latest = curr.data.latest;
      if (latest) {
        const allSame = FORM_FIELDS.every(
          (f) => (latest[f.key] || "") === (formData[f.key] || "")
        );
        if (allSame) {
          alert("数据未修改，与上次保存内容一致，无需重复保存");
          return;
        }
      }
      const res = await api.post("/log/save", { data: formData });
      setMessage(`保存成功，当前版本数：${res.data.version_count}`);
    } catch (err: any) {
      setMessage("保存失败：" + (err.response?.data?.detail || err.message || "未知错误"));
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans antialiased">
      <div className="max-w-2xl mx-auto py-10 px-4">
        {/* Header */}
        <div className="mb-8">
          <img src="/logo-text.png" alt="Logo" className="h-12 mb-3" />
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">DMP 日志信息填写</h1>
          <div className="flex items-center gap-3 mt-2 text-slate-500 text-sm">
            <div className="flex items-center gap-1.5">
              <FolderOpen size={14} />
              <span className="font-mono text-xs">{user?.workspace}</span>
            </div>
            <span className="text-slate-300">|</span>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-slate-400">Project:</label>
              {showNewInput ? (
                <div className="flex items-center gap-1">
                  <input
                    type="text"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleCreateProject(); if (e.key === "Escape") setShowNewInput(false); }}
                    onBlur={() => { if (!newProjectName.trim()) setShowNewInput(false); }}
                    placeholder="project name..."
                    className="w-32 px-2 py-0.5 text-xs font-mono bg-white border border-blue-300 rounded focus:outline-none focus:border-blue-500"
                    autoFocus
                  />
                  <button onClick={handleCreateProject} className="text-xs text-blue-600 hover:text-blue-800 font-medium">OK</button>
                </div>
              ) : (
                <select
                  value={project}
                  onChange={(e) => handleProjectSelect(e.target.value)}
                  className="w-36 px-2 py-0.5 text-xs font-mono bg-white border border-slate-200 rounded focus:outline-none focus:border-blue-400 cursor-pointer"
                >
                  {projects.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                  <option value="__new__">+ New project...</option>
                </select>
              )}
              {project !== "default" && (
                <button
                  onClick={handleDeleteProject}
                  className="text-slate-300 hover:text-red-500 cursor-pointer p-0.5"
                  title={`Delete project "${project}"`}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
            <Link
              to="/help"
              className="text-xs text-slate-500 hover:text-blue-600 transition-colors flex items-center gap-1 ml-auto"
              title="使用帮助"
            >
              <HelpCircle size={14} />
              帮助
            </Link>
          </div>
        </div>

        {/* Form Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8">
          <form onSubmit={handleSubmit} className="space-y-5">
            {FORM_FIELDS.filter(isVisible).map((field) => (
              <div key={field.key}>
                <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500 block mb-1.5">
                  {field.key}
                </label>
                {field.type === "select" ? (
                  <select
                    className="w-full bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none appearance-none cursor-pointer"
                    value={formData[field.key] || ""}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                  >
                    <option value="">-- 请选择 --</option>
                    {field.options?.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    placeholder={(field as any).placeholder || ""}
                    className="w-full bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none placeholder:text-slate-300"
                    value={formData[field.key] || ""}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                  />
                )}
              </div>
            ))}

            {/* Actions */}
            <div className="flex flex-wrap gap-3 pt-4 border-t border-slate-100">
              <button
                type="submit"
                className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer flex items-center gap-2"
              >
                <Save size={16} />
                保存日志
              </button>
              <button
                type="button"
                className="px-6 py-3 bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer flex items-center gap-2"
                onClick={() => navigate("/chat")}
              >
                <MessageSquare size={16} />
                进入聊天 →
              </button>
            </div>
          </form>

          {message && (
            <p className={`mt-4 text-sm font-medium px-4 py-3 rounded-xl ${message.includes("失败") ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-700"}`}>
              {message}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
