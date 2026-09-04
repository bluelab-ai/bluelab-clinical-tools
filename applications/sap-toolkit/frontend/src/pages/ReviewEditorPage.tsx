import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, FileSpreadsheet, Loader2, Save, Play, Plus, Trash2,
  CheckCircle2, AlertCircle, ChevronRight, ToggleLeft, ToggleRight,
  Download, RotateCcw,
} from "lucide-react";
import api from "../services/api";
import { useSSE } from "../hooks/useSSE";
import ProgressRing from "../components/ProgressRing";
import type { Project, ManualProject } from "../types";

interface TableInfo {
  filename: string | null;
  table_name: string;
  projects: ManualProject[];
  status: "normal" | "no_fill_needed" | "no_extraction";
}

export default function ReviewEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { connect, cancel } = useSSE();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [dirty, setDirty] = useState(false);

  // Phase 2b 状态
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
    } catch {} finally {
      setLoading(false);
    }
  };

  const fetchTableInfo = async () => {
    try {
      const res = await api.get(`/projects/${id}/table-info`);
      setTables(res.data.tables || []);
    } catch (err: any) {
      console.error("加载表格信息失败:", err);
    }
  };

  useEffect(() => {
    fetchProject();
    fetchTableInfo();
    return () => cancel();
  }, [id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [phaseMessages]);

  const selectedTable = tables[selectedIdx] || null;

  // 保存当前表格
  const saveCurrentTable = async () => {
    if (!selectedTable || !selectedTable.filename) return;
    setSaving(true);
    setSaveMsg("");
    try {
      await api.put(`/projects/${id}/table-info/${selectedTable.filename}`, {
        projects: selectedTable.projects,
      });
      setDirty(false);
      setSaveMsg("已保存");
      setTimeout(() => setSaveMsg(""), 2000);
    } catch {
      setSaveMsg("保存失败");
    } finally {
      setSaving(false);
    }
  };

  // 保存全部表格
  const saveAllTables = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      for (const table of tables) {
        if (!table.filename) continue; // 跳过无文件的表格
        await api.put(`/projects/${id}/table-info/${table.filename}`, {
          projects: table.projects,
        });
      }
      setDirty(false);
      setSaveMsg("全部保存成功");
      setTimeout(() => setSaveMsg(""), 2000);
    } catch {
      setSaveMsg("保存失败");
    } finally {
      setSaving(false);
    }
  };

  // 修改 project 字段
  const updateProject = (pi: number, field: string, value: any) => {
    if (!selectedTable) return;
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects];
    newProjects[pi] = { ...newProjects[pi], [field]: value };
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 切换定性/定量
  const toggleProjectType = (pi: number) => {
    if (!selectedTable) return;
    const proj = selectedTable.projects[pi];
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects];
    if ("categories" in proj) {
      // 定性 → 定量
      newProjects[pi] = { name: proj.name, unit: "" };
    } else {
      // 定量 → 定性
      newProjects[pi] = { name: proj.name, categories: [] };
    }
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 添加 project
  const addProject = () => {
    if (!selectedTable) return;
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects, { name: "", categories: [""] }];
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 删除 project
  const deleteProject = (pi: number) => {
    if (!selectedTable) return;
    const newTables = [...tables];
    const newProjects = selectedTable.projects.filter((_, i) => i !== pi);
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 修改分类选项
  const updateCategory = (pi: number, ci: number, value: string) => {
    if (!selectedTable) return;
    const proj = selectedTable.projects[pi];
    if (!("categories" in proj)) return;
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects];
    const newCats = [...(proj.categories || [])];
    newCats[ci] = value;
    newProjects[pi] = { ...proj, categories: newCats };
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 添加分类选项
  const addCategory = (pi: number) => {
    if (!selectedTable) return;
    const proj = selectedTable.projects[pi];
    if (!("categories" in proj)) return;
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects];
    newProjects[pi] = { ...proj, categories: [...(proj.categories || []), ""] };
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 删除分类选项
  const deleteCategory = (pi: number, ci: number) => {
    if (!selectedTable) return;
    const proj = selectedTable.projects[pi];
    if (!("categories" in proj)) return;
    const newTables = [...tables];
    const newProjects = [...selectedTable.projects];
    newProjects[pi] = { ...proj, categories: (proj.categories || []).filter((_, i) => i !== ci) };
    newTables[selectedIdx] = { ...selectedTable, projects: newProjects };
    setTables(newTables);
    setDirty(true);
  };

  // 重置生成状态，回到编辑模式
  const resetGenerate = () => {
    setCompleted(false);
    setIsRunning(false);
    setErrorMsg("");
    setProgress(0);
    setCurrentPhase("");
    setPhaseMessages([]);
  };

  // 启动 Phase 2b
  const startGenerate = async () => {
    // 先保存所有
    await saveAllTables();

    setIsRunning(true);
    setErrorMsg("");
    setProgress(0);
    setPhaseMessages([]);
    setCompleted(false);

    connect(
      `/api/projects/${id}/run-phase2b`,
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
          setPhaseMessages((prev) => [...prev, "✅ " + (evt.message || "表格生成完成")]);
          fetchProject();
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
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(`/project/${id}/catalog`)}
              className="w-9 h-9 rounded-xl hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="w-9 h-9 rounded-xl bg-emerald-600 text-white flex items-center justify-center">
              <FileSpreadsheet size={18} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">{project?.name}</h1>
              <p className="text-xs text-slate-500">审核编辑 — 检查并修改提取的指标</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {saveMsg && (
              <span className={`text-sm font-medium ${saveMsg.includes("失败") ? "text-red-500" : "text-emerald-500"}`}>
                {saveMsg}
              </span>
            )}
            {!isRunning && !completed && (
              <>
                <button
                  onClick={saveAllTables}
                  disabled={saving || !dirty}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Save size={16} /> {saving ? "保存中..." : "保存全部"}
                </button>
                <button
                  onClick={startGenerate}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors cursor-pointer"
                >
                  <Play size={16} /> 确认并生成表格
                </button>
              </>
            )}
            {completed && (
              <>
                <button
                  onClick={resetGenerate}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer"
                >
                  <RotateCcw size={16} /> 重新编辑
                </button>
                <button
                  onClick={() => handleDownload("docx")}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors cursor-pointer"
                >
                  <Download size={16} /> 下载 Word 文档
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6 flex gap-6" style={{ height: "calc(100vh - 73px)" }}>
        {/* 左侧：表格列表 */}
        <aside className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-200/70 shadow-sm overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-700">表格列表（{tables.length}）</h2>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {tables.map((t, i) => {
              const isSelected = i === selectedIdx;
              const isDisabled = t.status !== "normal";
              return (
                <button
                  key={`${t.table_name}-${i}`}
                  onClick={() => { setSelectedIdx(i); setDirty(false); }}
                  className={`w-full text-left px-4 py-2.5 text-sm border-b border-slate-50 transition-colors flex items-center gap-2 ${
                    isDisabled
                      ? "cursor-default text-slate-400 bg-slate-50/50"
                      : isSelected
                        ? "bg-blue-50 text-blue-700 font-medium cursor-pointer"
                        : "text-slate-600 hover:bg-slate-50 cursor-pointer"
                  }`}
                >
                  <ChevronRight size={14} className={isSelected ? "text-blue-400" : "text-slate-300"} />
                  <span className="truncate">{t.table_name}</span>
                  {t.status === "normal" && (
                    <span className="ml-auto text-xs text-slate-400 flex-shrink-0">{t.projects.length}项</span>
                  )}
                  {t.status === "no_fill_needed" && (
                    <span className="ml-auto text-xs text-slate-400 flex-shrink-0">无需填充</span>
                  )}
                  {t.status === "no_extraction" && (
                    <span className="ml-auto text-xs text-amber-500 flex-shrink-0">未提取</span>
                  )}
                </button>
              );
            })}
          </div>
        </aside>

        {/* 右侧：项目编辑区 */}
        <main className="flex-1 bg-white rounded-2xl border border-slate-200/70 shadow-sm overflow-hidden flex flex-col">
          {selectedTable ? (
            <>
              <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-slate-900">{selectedTable.table_name}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {selectedTable.status === "normal" && (
                      <>
                        {selectedTable.projects.length} 个指标项目
                        {dirty && <span className="text-amber-500 ml-2">● 未保存</span>}
                      </>
                    )}
                    {selectedTable.status === "no_fill_needed" && (
                      <span className="text-slate-400">此表格无需填充指标</span>
                    )}
                    {selectedTable.status === "no_extraction" && (
                      <span className="text-amber-500">未能在 CRF 中提取到项目</span>
                    )}
                  </p>
                </div>
                {selectedTable.status === "normal" && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={addProject}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors cursor-pointer"
                    >
                      <Plus size={14} /> 添加指标
                    </button>
                    <button
                      onClick={saveCurrentTable}
                      disabled={saving || !dirty}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 bg-slate-50 hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Save size={14} /> 保存
                    </button>
                  </div>
                )}
              </div>

              <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-4">
                {/* 无需填充提示 */}
                {selectedTable.status === "no_fill_needed" && (
                  <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                    <FileSpreadsheet size={48} className="mb-4 text-slate-300" />
                    <p className="text-sm font-medium">此表格无需填充指标</p>
                    <p className="text-xs mt-1">该类别的表格不需要从 CRF 中提取指标</p>
                  </div>
                )}

                {/* 未能提取提示 */}
                {selectedTable.status === "no_extraction" && (
                  <div className="flex flex-col items-center justify-center py-16 text-amber-500">
                    <AlertCircle size={48} className="mb-4 text-amber-400" />
                    <p className="text-sm font-medium">未能在 CRF 中提取到项目</p>
                    <p className="text-xs mt-1 text-slate-400">请检查 CRF 文件是否包含此表格的相关内容</p>
                  </div>
                )}

                {/* 正常编辑区 */}
                {selectedTable.status === "normal" && selectedTable.projects.length === 0 && (
                  <div className="text-center py-12 text-slate-400">
                    <p className="text-sm">暂无指标项目</p>
                    <button
                      onClick={addProject}
                      className="mt-3 text-sm text-blue-500 hover:text-blue-600 cursor-pointer"
                    >
                      + 添加第一个指标
                    </button>
                  </div>
                )}

                {selectedTable.status === "normal" && selectedTable.projects.map((proj, pi) => {
                  const isQualitative = "categories" in proj;
                  return (
                    <div
                      key={pi}
                      className="border border-slate-200 rounded-xl p-4 space-y-3"
                    >
                      {/* 项目头部 */}
                      <div className="flex items-center gap-3">
                        <input
                          type="text"
                          value={proj.name}
                          onChange={(e) => updateProject(pi, "name", e.target.value)}
                          placeholder="指标名称"
                          className="flex-1 px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
                        />
                        <button
                          onClick={() => toggleProjectType(pi)}
                          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium border border-slate-200 hover:bg-slate-50 transition-colors cursor-pointer"
                          title={isQualitative ? "切换为定量" : "切换为定性"}
                        >
                          {isQualitative ? (
                            <><ToggleLeft size={14} className="text-blue-500" /> 定性</>
                          ) : (
                            <><ToggleRight size={14} className="text-emerald-500" /> 定量</>
                          )}
                        </button>
                        <button
                          onClick={() => deleteProject(pi)}
                          className="w-8 h-8 rounded-lg hover:bg-red-50 flex items-center justify-center text-slate-400 hover:text-red-500 transition-colors cursor-pointer"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>

                      {/* 定性：分类选项 */}
                      {isQualitative && (
                        <div className="pl-4 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-slate-500">分类选项</span>
                            <button
                              onClick={() => addCategory(pi)}
                              className="text-xs text-blue-500 hover:text-blue-600 cursor-pointer"
                            >
                              + 添加选项
                            </button>
                          </div>
                          {(proj.categories || []).map((cat, ci) => (
                            <div key={ci} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={cat}
                                onChange={(e) => updateCategory(pi, ci, e.target.value)}
                                placeholder={`选项 ${ci + 1}`}
                                className="flex-1 px-2.5 py-1 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
                              />
                              <button
                                onClick={() => deleteCategory(pi, ci)}
                                className="w-6 h-6 rounded hover:bg-red-50 flex items-center justify-center text-slate-400 hover:text-red-500 transition-colors cursor-pointer"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          ))}
                          {(!proj.categories || proj.categories.length === 0) && (
                            <p className="text-xs text-slate-400">暂无分类选项</p>
                          )}
                        </div>
                      )}

                      {/* 定量：单位 */}
                      {!isQualitative && (
                        <div className="pl-4">
                          <label className="text-xs font-medium text-slate-500 block mb-1">单位</label>
                          <input
                            type="text"
                            value={(proj as any).unit || ""}
                            onChange={(e) => updateProject(pi, "unit", e.target.value)}
                            placeholder="如：mL、kg、次/分"
                            className="w-48 px-2.5 py-1 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-slate-400">
              <p>请选择一个表格</p>
            </div>
          )}

          {/* Phase 2b 进度区域 */}
          {(isRunning || completed || errorMsg) && (
            <div className="border-t border-slate-100 p-6">
              <div className="flex items-center gap-6 mb-4">
                <ProgressRing percent={progress} size={80} />
                <div className="flex-1">
                  <h3 className="text-sm font-bold text-slate-900">
                    {completed ? "表格生成完成！" : isRunning ? "正在生成表格..." : ""}
                  </h3>
                  {currentPhase && (
                    <p className={`text-xs font-medium mt-1 ${completed ? "text-emerald-600" : "text-blue-600"}`}>
                      {currentPhase}
                    </p>
                  )}
                  {completed && (
                    <div className="flex items-center gap-2 mt-2">
                      <CheckCircle2 size={16} className="text-emerald-500" />
                      <span className="text-xs text-emerald-600 font-medium">所有表格已生成完毕</span>
                    </div>
                  )}
                </div>
              </div>

              {phaseMessages.length > 0 && (
                <div className="max-h-32 overflow-y-auto custom-scrollbar bg-slate-50 rounded-xl p-3 space-y-1 mb-3">
                  {phaseMessages.map((msg, i) => (
                    <p key={i} className="text-xs text-slate-600 font-mono">{msg}</p>
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              )}

              {errorMsg && (
                <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2 mb-3">
                  <AlertCircle size={14} /> {errorMsg}
                </div>
              )}

              {completed && (
                <div className="flex gap-3">
                  <button
                    onClick={resetGenerate}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-sm font-semibold hover:bg-slate-50 transition-all cursor-pointer"
                  >
                    <RotateCcw size={16} /> 重新编辑并生成
                  </button>
                  <button
                    onClick={() => handleDownload("docx")}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
                  >
                    <Download size={16} /> 下载 Word 文档
                  </button>
                </div>
              )}

              {errorMsg && !isRunning && (
                <button
                  onClick={startGenerate}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer"
                >
                  <Play size={16} /> 重试
                </button>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
