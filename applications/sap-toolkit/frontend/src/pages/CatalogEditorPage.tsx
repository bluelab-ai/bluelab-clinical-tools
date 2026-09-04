import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, FileSpreadsheet, Loader2, Save, Play, Plus, Trash2,
  ChevronDown, ChevronRight, CheckCircle2, AlertCircle, Pencil, X,
} from "lucide-react";
import api from "../services/api";
import type { Project, CatalogItem, ManualProject } from "../types";

interface CategoryGroup {
  category: string;
  items: CatalogItem[];
  collapsed: boolean;
}

const SOURCE_BADGES: Record<string, { label: string; color: string }> = {
  none:  { label: "固定项目", color: "bg-slate-100 text-slate-500" },
  title: { label: "标题提取", color: "bg-violet-50 text-violet-600" },
  crf:   { label: "CRF自动提取", color: "bg-emerald-50 text-emerald-600" },
  fill:  { label: "根据表格名填充", color: "bg-amber-50 text-amber-600" },
};

interface AddTableForm {
  show: boolean;
  gi: number | null;
  position: number | null;
  tableName: string;
  dataSource: "auto" | "manual";
  projects: ManualProject[];
}

const emptyForm: AddTableForm = {
  show: false,
  gi: null,
  position: null,
  tableName: "",
  dataSource: "auto",
  projects: [],
};

export default function CatalogEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [groups, setGroups] = useState<CategoryGroup[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [editingCell, setEditingCell] = useState<{ gi: number; ii: number } | null>(null);
  const [editValue, setEditValue] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const [showAddCategory, setShowAddCategory] = useState(false);
  const [addForm, setAddForm] = useState<AddTableForm>(emptyForm);

  const fetchProject = async () => {
    try {
      const res = await api.get(`/projects/${id}`);
      setProject(res.data);
    } catch {} finally {
      setLoading(false);
    }
  };

  const fetchTables = async () => {
    try {
      const res = await api.get(`/projects/${id}/tables`);
      const tables: CatalogItem[] = res.data.tables || [];
      // Group by category
      const map = new Map<string, CatalogItem[]>();
      for (const t of tables) {
        if (!map.has(t.category)) map.set(t.category, []);
        map.get(t.category)!.push(t);
      }
      setGroups(
        Array.from(map.entries()).map(([category, items]) => ({
          category,
          items,
          collapsed: false,
        }))
      );
    } catch (err: any) {
      console.error("加载表格目录失败:", err);
    }
  };

  useEffect(() => {
    fetchProject();
    fetchTables();
  }, [id]);

  const toggleCollapse = (gi: number) => {
    setGroups((prev) => prev.map((g, i) => i === gi ? { ...g, collapsed: !g.collapsed } : g));
  };

  const startEdit = (gi: number, ii: number, currentValue: string) => {
    setEditingCell({ gi, ii });
    setEditValue(currentValue);
  };

  const confirmEdit = () => {
    if (!editingCell) return;
    setGroups((prev) =>
      prev.map((g, gi) =>
        gi === editingCell.gi
          ? {
              ...g,
              items: g.items.map((item, ii) =>
                ii === editingCell.ii ? { ...item, name: editValue } : item
              ),
            }
          : g
      )
    );
    setEditingCell(null);
    setEditValue("");
  };

  const cancelEdit = () => {
    setEditingCell(null);
    setEditValue("");
  };

  const deleteItem = (gi: number, ii: number) => {
    setGroups((prev) =>
      prev.map((g, i) =>
        i === gi ? { ...g, items: g.items.filter((_, j) => j !== ii) } : g
      ).filter((g) => g.items.length > 0) // Remove empty categories
    );
  };

  const showAddForm = (gi: number, position?: number) => {
    setAddForm({
      ...emptyForm,
      show: true,
      gi,
      position: position ?? groups[gi].items.length,
    });
  };

  const confirmAddTable = () => {
    const { gi, position, tableName, dataSource, projects } = addForm;
    if (gi === null || position === null || !tableName.trim()) return;

    const group = groups[gi];
    const newItem: CatalogItem = {
      category: group.category,
      index: 0,
      name: tableName.trim(),
      data_source: dataSource,
      ...(dataSource === "manual" ? { projects } : {}),
    };

    setGroups((prev) =>
      prev.map((g, i) => {
        if (i !== gi) return g;
        const newItems = [...g.items];
        newItems.splice(position, 0, newItem);
        return { ...g, items: newItems };
      })
    );
    setAddForm(emptyForm);
  };

  const addProjectToForm = () => {
    setAddForm((prev) => ({
      ...prev,
      projects: [...prev.projects, { name: "", categories: [] }],
    }));
  };

  const removeProjectFromForm = (pi: number) => {
    setAddForm((prev) => ({
      ...prev,
      projects: prev.projects.filter((_, i) => i !== pi),
    }));
  };

  const updateFormProject = (pi: number, field: keyof ManualProject, value: any) => {
    setAddForm((prev) => ({
      ...prev,
      projects: prev.projects.map((p, i) => (i === pi ? { ...p, [field]: value } : p)),
    }));
  };

  const toggleProjectType = (pi: number, type: "qualitative" | "quantitative") => {
    setAddForm((prev) => ({
      ...prev,
      projects: prev.projects.map((p, i) => {
        if (i !== pi) return p;
        if (type === "qualitative") {
          // Toggle qualitative: if already selected, deselect; otherwise select and remove unit
          if (p.categories !== undefined) {
            return { ...p, categories: undefined };
          }
          return { ...p, categories: p.categories ?? [], unit: undefined };
        } else {
          // Toggle quantitative: if already selected, deselect; otherwise select and remove categories
          if (p.unit !== undefined) {
            return { ...p, unit: undefined };
          }
          return { ...p, unit: p.unit ?? "", categories: undefined };
        }
      }),
    }));
  };

  const addCategory = () => {
    if (!newCategoryName.trim()) return;
    setGroups((prev) => [
      ...prev,
      { category: newCategoryName.trim(), items: [], collapsed: false },
    ]);
    setNewCategoryName("");
    setShowAddCategory(false);
  };

  const deleteCategory = (gi: number) => {
    setGroups((prev) => prev.filter((_, i) => i !== gi));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      // Flatten groups back to tables array, preserving all fields
      const tables = groups.flatMap((g) =>
        g.items.map((item) => {
          const entry: any = { category: g.category, name: item.name, index: 0 };
          if (item.data_source) entry.data_source = item.data_source;
          if (item.projects) entry.projects = item.projects;
          return entry;
        })
      );
      await api.put(`/projects/${id}/tables`, { tables });
      setSaveMsg("保存成功");
      setTimeout(() => setSaveMsg(""), 2000);
    } catch (err: any) {
      setSaveMsg("保存失败: " + (err.response?.data?.detail || "请重试"));
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async () => {
    // Save first, then navigate to phase2
    setSaving(true);
    try {
      const tables = groups.flatMap((g) =>
        g.items.map((item) => {
          const entry: any = { category: g.category, name: item.name, index: 0 };
          if (item.data_source) entry.data_source = item.data_source;
          if (item.projects) entry.projects = item.projects;
          return entry;
        })
      );
      await api.put(`/projects/${id}/tables`, { tables });
      navigate(`/project/${id}/prompts`);
    } catch (err: any) {
      setSaveMsg("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const totalItems = groups.reduce((sum, g) => sum + g.items.length, 0);

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
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
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
              <h1 className="text-lg font-bold text-slate-900">{project?.name}</h1>
              <p className="text-xs text-slate-500">编辑表格目录 · {totalItems} 张表格 · {groups.length} 个分类</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {saveMsg && (
              <span className={`text-sm font-medium ${saveMsg.includes("成功") ? "text-emerald-600" : "text-red-500"}`}>
                {saveMsg}
              </span>
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer disabled:opacity-60"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              保存
            </button>
            <button
              onClick={handleGenerate}
              disabled={saving || totalItems === 0}
              className="flex items-center gap-1.5 px-5 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <Play size={16} /> 预览提取 Prompt
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Info Banner */}
        <div className="mb-6 p-4 rounded-xl bg-blue-50 border border-blue-100 text-sm text-blue-700 flex items-center gap-2">
          <AlertCircle size={16} />
          目录已从 SAP 文档中自动提取。您可以修改表格名称、删除不需要的项目、添加新项目，完成后点击"预览提取 Prompt"查看和编辑 CRF 提取指令。
        </div>

        {/* Category Groups */}
        <div className="space-y-4">
          {groups.map((group, gi) => (
            <div key={gi} className="bg-white rounded-2xl border border-slate-200/70 shadow-sm overflow-hidden">
              {/* Category Header */}
              <div
                className="flex items-center justify-between px-5 py-3.5 bg-slate-50 border-b border-slate-200/70 cursor-pointer select-none"
                onClick={() => toggleCollapse(gi)}
              >
                <div className="flex items-center gap-3">
                  {group.collapsed ? (
                    <ChevronRight size={18} className="text-slate-400" />
                  ) : (
                    <ChevronDown size={18} className="text-slate-400" />
                  )}
                  <h3 className="font-bold text-slate-800">{group.category}</h3>
                  <span className="text-xs bg-slate-200 text-slate-600 px-2 py-0.5 rounded-full font-medium">
                    {group.items.length}
                  </span>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteCategory(gi); }}
                  className="w-7 h-7 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-400 hover:text-red-500 transition-colors cursor-pointer"
                  title="删除此分类"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              {/* Items */}
              {!group.collapsed && (
                <div className="divide-y divide-slate-100">
                  {group.items.map((item, ii) => (
                    <div
                      key={ii}
                      className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/50 transition-colors group"
                    >
                      <span className="text-xs text-slate-400 font-mono w-8 text-right">
                        {ii + 1}
                      </span>

                      {editingCell?.gi === gi && editingCell?.ii === ii ? (
                        <div className="flex-1 flex items-center gap-2">
                          <input
                            type="text"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") confirmEdit();
                              if (e.key === "Escape") cancelEdit();
                            }}
                            autoFocus
                            className="flex-1 px-2 py-1 border border-blue-400 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-100"
                          />
                          <button
                            onClick={confirmEdit}
                            className="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-600 flex items-center justify-center hover:bg-emerald-200 cursor-pointer"
                          >
                            <CheckCircle2 size={14} />
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="w-7 h-7 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center hover:bg-slate-200 cursor-pointer"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <>
                          <span
                            className={`flex-1 text-sm ${item.locked ? "text-slate-400" : "text-slate-700 cursor-pointer hover:text-blue-600"}`}
                            onClick={() => !item.locked && startEdit(gi, ii, item.name)}
                          >
                            {item.name}
                          </span>
                          {item.data_source && SOURCE_BADGES[item.data_source] && (
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${SOURCE_BADGES[item.data_source].color}`}>
                              {SOURCE_BADGES[item.data_source].label}
                            </span>
                          )}
                          {item.locked ? (
                            <span className="text-xs text-slate-400 px-1.5">🔒</span>
                          ) : (
                            <>
                              <button
                                onClick={() => showAddForm(gi, ii + 1)}
                                className="w-7 h-7 rounded-lg hover:bg-blue-100 flex items-center justify-center text-slate-300 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                                title="在此行后插入"
                              >
                                <Plus size={13} />
                              </button>
                              <button
                                onClick={() => startEdit(gi, ii, item.name)}
                                className="w-7 h-7 rounded-lg hover:bg-blue-100 flex items-center justify-center text-slate-300 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                              >
                                <Pencil size={13} />
                              </button>
                              <button
                                onClick={() => deleteItem(gi, ii)}
                                className="w-7 h-7 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                              >
                                <Trash2 size={13} />
                              </button>
                            </>
                          )}
                        </>
                      )}
                    </div>
                  ))}

                  {/* Add item button */}
                  <button
                    onClick={() => showAddForm(gi)}
                    className="w-full flex items-center gap-2 px-5 py-3 text-sm text-blue-600 hover:bg-blue-50/50 transition-colors cursor-pointer"
                  >
                    <Plus size={16} /> 添加表格
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Add Category */}
        <div className="mt-4">
          {showAddCategory ? (
            <div className="bg-white rounded-2xl border border-slate-200/70 shadow-sm p-5">
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={newCategoryName}
                  onChange={(e) => setNewCategoryName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addCategory(); }}
                  placeholder="输入分类名称"
                  autoFocus
                  className="flex-1 px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                />
                <button
                  onClick={addCategory}
                  disabled={!newCategoryName.trim()}
                  className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 cursor-pointer disabled:opacity-60"
                >
                  添加
                </button>
                <button
                  onClick={() => { setShowAddCategory(false); setNewCategoryName(""); }}
                  className="px-4 py-2 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 cursor-pointer"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowAddCategory(true)}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-2xl border-2 border-dashed border-slate-200 text-sm text-slate-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50/30 transition-all cursor-pointer"
            >
              <Plus size={18} /> 添加新分类
            </button>
          )}
        </div>
      </main>

      {/* Add Table Modal */}
      {addForm.show && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <h3 className="font-bold text-slate-900">添加表格</h3>
              <button
                onClick={() => setAddForm(emptyForm)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-400 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-6 space-y-5">
              {/* Table Name */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">表格名称</label>
                <input
                  type="text"
                  value={addForm.tableName}
                  onChange={(e) => setAddForm((prev) => ({ ...prev, tableName: e.target.value }))}
                  placeholder="输入表格名称"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              {/* Data Source */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">数据来源</label>
                <div className="flex gap-3">
                  <button
                    onClick={() => setAddForm((prev) => ({ ...prev, dataSource: "auto" }))}
                    className={`flex-1 px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors cursor-pointer ${
                      addForm.dataSource === "auto"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    从 CRF 自动抓取
                  </button>
                  <button
                    onClick={() => setAddForm((prev) => ({ ...prev, dataSource: "manual" }))}
                    className={`flex-1 px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors cursor-pointer ${
                      addForm.dataSource === "manual"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    手动填写
                  </button>
                </div>
              </div>

              {/* Manual Projects */}
              {addForm.dataSource === "manual" && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-700">指标列表</label>
                    <button
                      onClick={addProjectToForm}
                      className="text-sm text-blue-600 hover:text-blue-700 cursor-pointer flex items-center gap-1"
                    >
                      <Plus size={14} /> 添加指标
                    </button>
                  </div>

                  {addForm.projects.map((proj, pi) => (
                    <div key={pi} className="bg-slate-50 rounded-xl p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={proj.name}
                          onChange={(e) => updateFormProject(pi, "name", e.target.value)}
                          placeholder="指标名称"
                          className="flex-1 px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                        />
                        <button
                          onClick={() => removeProjectFromForm(pi)}
                          className="w-7 h-7 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-400 hover:text-red-500 cursor-pointer"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>

                      {/* Type toggle */}
                      <div className="flex gap-2">
                        <button
                          onClick={() => toggleProjectType(pi, "qualitative")}
                          className={`px-3 py-1 rounded-lg text-xs font-medium cursor-pointer ${
                            proj.categories !== undefined
                              ? "bg-blue-100 text-blue-700"
                              : "bg-slate-200 text-slate-500"
                          }`}
                        >
                          定性
                        </button>
                        <button
                          onClick={() => toggleProjectType(pi, "quantitative")}
                          className={`px-3 py-1 rounded-lg text-xs font-medium cursor-pointer ${
                            proj.unit !== undefined
                              ? "bg-blue-100 text-blue-700"
                              : "bg-slate-200 text-slate-500"
                          }`}
                        >
                          定量
                        </button>
                      </div>

                      {/* Categories or Unit */}
                      {proj.categories !== undefined && (
                        <div className="space-y-2">
                          {proj.categories.map((cat, ci) => (
                            <div key={ci} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={cat}
                                onChange={(e) => {
                                  const newCats = [...proj.categories!];
                                  newCats[ci] = e.target.value;
                                  updateFormProject(pi, "categories", newCats);
                                }}
                                placeholder={`分类 ${ci + 1}`}
                                className="flex-1 px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                              />
                              <button
                                onClick={() => {
                                  const newCats = proj.categories!.filter((_, i) => i !== ci);
                                  updateFormProject(pi, "categories", newCats);
                                }}
                                className="w-7 h-7 rounded-lg hover:bg-red-100 flex items-center justify-center text-slate-400 hover:text-red-500 cursor-pointer"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          ))}
                          <button
                            onClick={() => {
                              updateFormProject(pi, "categories", [...(proj.categories || []), ""]);
                            }}
                            className="flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700 cursor-pointer"
                          >
                            <Plus size={14} /> 添加分类
                          </button>
                        </div>
                      )}
                      {proj.unit !== undefined && (
                        <input
                          type="text"
                          value={proj.unit}
                          onChange={(e) => updateFormProject(pi, "unit", e.target.value)}
                          placeholder="单位（如：次、mmHg、%）"
                          className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
                        />
                      )}
                    </div>
                  ))}

                  {addForm.projects.length === 0 && (
                    <p className="text-sm text-slate-400 text-center py-4">暂无指标，请点击"添加指标"</p>
                  )}
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-3">
              <button
                onClick={() => setAddForm(emptyForm)}
                className="px-4 py-2 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={confirmAddTable}
                disabled={!addForm.tableName.trim()}
                className="px-5 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 cursor-pointer disabled:opacity-60"
              >
                确认添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
