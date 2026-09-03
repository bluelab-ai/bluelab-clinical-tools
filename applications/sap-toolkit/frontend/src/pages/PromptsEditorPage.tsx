import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../services/api";
import type { Project, PromptsCatalog, PromptItem, PromptCommon } from "../types";

export default function PromptsEditorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [prompts, setPrompts] = useState<PromptsCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [showCommon, setShowCommon] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const pRes = await api.get(`/projects/${id}`);
        setProject(pRes.data);
      } catch {}

      try {
        const res = await api.get(`/projects/${id}/prompts`);
        setPrompts(res.data);
      } catch {
        try {
          const res = await api.post(`/projects/${id}/generate-prompts`);
          setPrompts(res.data);
        } catch (e: any) {
          setError(e.response?.data?.detail || "加载 prompts 失败");
        }
      }

      setLoading(false);
    };
    load();
  }, [id]);

  const updateCommon = (field: keyof PromptCommon, value: string) => {
    if (!prompts?.common) return;
    setPrompts({ ...prompts, common: { ...prompts.common, [field]: value } });
  };

  const updateInstruction = (index: number, value: string) => {
    if (!prompts) return;
    const items = [...prompts.items];
    items[index] = { ...items[index], instruction: value };
    setPrompts({ ...prompts, items });
  };

  const toggleEnabled = (index: number) => {
    if (!prompts) return;
    const items = [...prompts.items];
    items[index] = { ...items[index], enabled: !items[index].enabled };
    setPrompts({ ...prompts, items });
  };

  const handleSave = async () => {
    if (!prompts) return;
    setSaving(true);
    setError("");
    try {
      await api.put(`/projects/${id}/prompts`, prompts);
    } catch (e: any) {
      setError(e.response?.data?.detail || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async () => {
    await handleSave();
    navigate(`/project/${id}/phase2`);
  };

  const categoryGroups: Record<string, { item: PromptItem; idx: number }[]> = {};
  if (prompts?.items) {
    prompts.items.forEach((item, idx) => {
      const cat = item.category || "其他";
      if (!categoryGroups[cat]) categoryGroups[cat] = [];
      categoryGroups[cat].push({ item, idx });
    });
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between max-w-5xl mx-auto">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">提取 Prompt 预览</h1>
            <p className="text-sm text-gray-500 mt-1">
              {project ? `项目: ${project.name}` : ""} — 查看和编辑每张表格的 CRF 提取指令
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => navigate(`/project/${id}/catalog`)} className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors">返回目录</button>
            {prompts && (
              <>
                <button onClick={handleSave} disabled={saving} className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50">{saving ? "保存中..." : "保存修改"}</button>
                <button onClick={handleGenerate} disabled={saving} className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50">保存并开始生成</button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>
        )}

        {!prompts && !error && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
            <p className="font-medium">未能加载 Prompt 数据</p>
            <p className="mt-1">请先完成阶段一并生成表格目录。</p>
            <button onClick={() => navigate(`/project/${id}/catalog`)} className="mt-3 px-4 py-2 bg-yellow-100 border border-yellow-300 rounded-lg text-yellow-800 hover:bg-yellow-200 transition-colors">返回目录编辑</button>
          </div>
        )}

        {prompts?.common && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <button onClick={() => setShowCommon(!showCommon)} className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors">
              <div className="flex items-center gap-3">
                <span>📋</span>
                <span className="font-medium text-gray-900">公共规则</span>
                <span className="text-xs text-gray-400">所有表格共享的提取规则和输出格式</span>
              </div>
              <svg className={`w-4 h-4 text-gray-400 transition-transform ${showCommon ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
            </button>
            {showCommon && (
              <div className="px-5 pb-5 space-y-4 border-t border-gray-100 pt-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">提取要求</label>
                  <textarea value={prompts.common.extract_rules} onChange={(e) => updateCommon("extract_rules", e.target.value)} rows={8} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y font-mono" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">输出格式</label>
                  <textarea value={prompts.common.output_format} onChange={(e) => updateCommon("output_format", e.target.value)} rows={10} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y font-mono" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">注意事项</label>
                  <textarea value={prompts.common.notes} onChange={(e) => updateCommon("notes", e.target.value)} rows={3} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y font-mono" />
                </div>
              </div>
            )}
          </div>
        )}

        {Object.entries(categoryGroups).map(([category, items]) => (
          <div key={category} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="flex items-center gap-3 px-5 py-3 bg-gray-50 border-b border-gray-200">
              <span className="font-medium text-gray-900">{category}</span>
              <span className="text-xs text-gray-400">{items.length} 张表</span>
            </div>
            <div className="divide-y divide-gray-100">
              {items.map((entry) => (
                <div key={entry.idx} className={`px-5 py-4 transition-colors ${entry.item.enabled ? "" : "bg-gray-50 opacity-60"}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className={`font-medium text-sm ${entry.item.enabled ? "text-gray-900" : "text-gray-400 line-through"}`}>{entry.item.name}</span>
                    <button onClick={() => toggleEnabled(entry.idx)} className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${entry.item.enabled ? "bg-indigo-600" : "bg-gray-300"}`}>
                      <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${entry.item.enabled ? "translate-x-4.5" : "translate-x-1"}`} style={{ transform: entry.item.enabled ? "translateX(18px)" : "translateX(4px)" }} />
                    </button>
                  </div>
                  <textarea value={entry.item.instruction} onChange={(e) => updateInstruction(entry.idx, e.target.value)} disabled={!entry.item.enabled} rows={4} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y disabled:bg-gray-100 disabled:cursor-not-allowed" />
                </div>
              ))}
            </div>
          </div>
        ))}

        {prompts?.items && (
          <div className="flex items-center justify-between text-sm text-gray-500">
            <span>共 {prompts.items.length} 张表，已启用 {prompts.items.filter((i) => i.enabled).length} 张</span>
            <div className="flex gap-3">
              <button onClick={() => navigate(`/project/${id}/catalog`)} className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors">返回目录</button>
              <button onClick={handleSave} disabled={saving} className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50">{saving ? "保存中..." : "保存修改"}</button>
              <button onClick={handleGenerate} disabled={saving} className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50">保存并开始生成</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
