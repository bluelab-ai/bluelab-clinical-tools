import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import api from "../services/api";
import {
  FileCheck,
  Table2,
  ListChecks,
  LogOut,
  ChevronRight,
  Lock,
  Settings,
  X,
  Save,
  Loader2,
  CheckCircle2,
  FolderArchive,
  Trash2,
  Download,
  AlertTriangle,
} from "lucide-react";

interface QCOption {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  enabled: boolean;
  route: string;
  comingSoon?: string;
}

export default function QCHomePage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const options: QCOption[] = [
    {
      id: "protocol-table",
      title: "方案表格一致性质控",
      description:
        "核查临床试验方案与 TFL 表格之间的一致性，包括分析人群、统计方法、指标定义等关键要素的对应关系。",
      icon: <FileCheck size={28} />,
      enabled: true,
      route: "/qc/protocol-table",
    },
    {
      id: "table-internal",
      title: "表格内部一致性质控",
      description:
        "检查 TFL 表格内部的逻辑一致性，包括合计行、百分比、样本量、表内交叉引用等数据的正确性。",
      icon: <Table2 size={28} />,
      enabled: true,
      route: "/qc/table-internal",
    },
    {
      id: "table-listing-cross",
      title: "表格清单一致性质控",
      description:
        "通过清单反向核查表格数据，自动建立表格-清单映射对，逐对进行深度质控，生成完整的核查报告。",
      icon: <ListChecks size={28} />,
      enabled: true,
      route: "/qc/table-listing-cross",
    },
  ];

  // ─── 设置侧边栏状态 ────────────────────────────────────────────────
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [llmConfig, setLlmConfig] = useState({
    LLM_API_BASE: "",
    LLM_MODEL: "",
    LLM_API_KEY_masked: "",
  });
  const [form, setForm] = useState({ api_key: "", api_base: "", model: "" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // ─── 日志归档弹窗 ────────────────────────────────────────────────
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logUnlocked, setLogUnlocked] = useState(false);
  const [adminPassword, setAdminPassword] = useState("");
  const [adminChecking, setAdminChecking] = useState(false);
  const [adminError, setAdminError] = useState("");
  const [logAction, setLogAction] = useState<"idle" | "clearing" | "downloading">("idle");
  const [logError, setLogError] = useState("");
  const [userCount, setUserCount] = useState<number | null>(null);

  const openLogModal = () => {
    setLogModalOpen(true);
    setLogUnlocked(false);
    setAdminPassword("");
    setAdminError("");
    setLogAction("idle");
    setLogError("");
    setUserCount(null);
  };

  const closeLogModal = () => {
    setLogModalOpen(false);
    setLogUnlocked(false);
    setAdminPassword("");
    setAdminError("");
  };

  const handleAdminVerify = async () => {
    setAdminChecking(true);
    setAdminError("");
    try {
      await api.post("/auth/admin/verify", { password: adminPassword });
      setLogUnlocked(true);
      fetchUserCount();
    } catch {
      setAdminError("密码错误");
    } finally {
      setAdminChecking(false);
    }
  };

  const fetchUserCount = async () => {
    try {
      const res = await api.get("/auth/users/count");
      setUserCount(res.data.count);
    } catch {
      // 静默失败
    }
  };

  const handleClearArchive = async () => {
    setLogAction("clearing");
    setLogError("");
    try {
      await api.post("/files/archive/clear");
      setLogAction("idle");
    } catch {
      setLogError("清空失败，请重试");
      setLogAction("idle");
    }
  };

  const handleDownloadArchive = () => {
    setLogAction("downloading");
    setLogError("");
    const a = document.createElement("a");
    a.href = "/api/files/archive/download-zip";
    a.download = "files_archive.zip";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // 延迟重置，给浏览器下载启动时间
    setTimeout(() => setLogAction("idle"), 1500);
  };

  const fetchConfig = async () => {
    try {
      const res = await api.get("/config/llm");
      setLlmConfig(res.data);
      setForm({
        api_key: "",
        api_base: res.data.LLM_API_BASE || "",
        model: res.data.LLM_MODEL || "",
      });
    } catch {
      // 静默失败
    }
  };

  const openSidebar = () => {
    setSidebarOpen(true);
    setSaved(false);
    fetchConfig();
  };

  const saveConfig = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await api.put("/config/llm", {
        LLM_API_KEY: form.api_key,
        LLM_API_BASE: form.api_base,
        LLM_MODEL: form.model,
      });
      setSaved(true);
      setForm((prev) => ({ ...prev, api_key: "" }));
      fetchConfig();
    } catch {
      // 保存失败
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans antialiased">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/70 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="Logo" className="h-8" />
            <div>
              <h1 className="text-lg font-bold text-slate-900">TFL QC Platform</h1>
              <p className="text-xs text-slate-500">临床试验 TFL 质控平台</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-500">
              欢迎，<span className="font-semibold text-slate-700">{user?.username}</span>
            </span>
            <button
              onClick={openSidebar}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-blue-500 transition-colors cursor-pointer"
              title="LLM 模型配置"
            >
              <Settings size={18} />
            </button>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-red-500 transition-colors cursor-pointer"
            >
              <LogOut size={16} />
              退出
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-5xl mx-auto px-6 py-12">
        <div className="mb-10">
          <h2 className="text-2xl font-bold text-slate-900 mb-2">选择质控类型</h2>
          <p className="text-slate-500 text-sm">
            请选择您需要执行的质控任务类型。目前已开放全部三种质控功能。
          </p>
        </div>

        {/* QC Option Cards */}
        <div className="grid gap-5 md:grid-cols-3">
          {options.map((option, idx) => (
            <button
              key={option.id}
              onClick={() => option.enabled && navigate(option.route)}
              disabled={!option.enabled}
              className={`relative text-left p-6 rounded-2xl border transition-all qc-card-enter ${
                option.enabled
                  ? "bg-white border-slate-200/70 shadow-sm hover:border-blue-400 hover:shadow-md hover:-translate-y-0.5 cursor-pointer active:scale-[0.98]"
                  : "bg-slate-100/60 border-slate-200/40 cursor-not-allowed opacity-70"
              }`}
              style={{ animationDelay: `${idx * 100}ms` }}
            >
              {/* Coming Soon Badge */}
              {!option.enabled && option.comingSoon && (
                <div className="absolute top-3 right-3 flex items-center gap-1 bg-amber-100 text-amber-700 text-xs font-semibold px-2.5 py-1 rounded-full">
                  <Lock size={10} />
                  {option.comingSoon}
                </div>
              )}

              {/* Icon */}
              <div
                className={`w-14 h-14 rounded-xl flex items-center justify-center mb-4 ${
                  option.enabled
                    ? "bg-blue-600 text-white"
                    : "bg-slate-300 text-slate-500"
                }`}
              >
                {option.icon}
              </div>

              {/* Title */}
              <h3
                className={`text-lg font-bold mb-2 ${
                  option.enabled ? "text-slate-900" : "text-slate-500"
                }`}
              >
                {option.title}
              </h3>

              {/* Description */}
              <p className="text-sm text-slate-500 leading-relaxed mb-4">
                {option.description}
              </p>

              {/* Action indicator */}
              {option.enabled && (
                <div className="flex items-center gap-1 text-blue-600 text-sm font-semibold">
                  进入质控
                  <ChevronRight size={16} />
                </div>
              )}
            </button>
          ))}
        </div>

        {/* Footer info — 三大模块简介 */}
        <div className="mt-12 space-y-4">
          <div className="p-5 bg-blue-50/50 rounded-2xl border border-blue-100/50">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center flex-shrink-0 mt-0.5">
                <FileCheck size={16} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900 mb-1">方案表格一致性质控</h4>
                <p className="text-xs text-slate-600 leading-relaxed">
                  比对临床试验方案与 TFL 表格，自动提取方案中的统计分析要素（分析人群、终点指标、
                  统计方法等），与表格标题索引进行匹配校验，核查条目覆盖度、统计方法一致性、分析人群
                  对应关系等关键维度。
                </p>
              </div>
            </div>
          </div>

          <div className="p-5 bg-emerald-50/50 rounded-2xl border border-emerald-100/50">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-emerald-600 text-white flex items-center justify-center flex-shrink-0 mt-0.5">
                <Table2 size={16} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900 mb-1">表格内部一致性质控</h4>
                <p className="text-xs text-slate-600 leading-relaxed">
                  对 TFL 表格进行表内自洽性核查，自动识别表型（标准定性定量表/事件表/交叉表/病例分布表
                  等），按表型匹配核查规则，逐表验证合计行、百分比、N值、分析集边界等数据正确性。
                </p>
              </div>
            </div>
          </div>

          <div className="p-5 bg-violet-50/50 rounded-2xl border border-violet-100/50">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-violet-600 text-white flex items-center justify-center flex-shrink-0 mt-0.5">
                <ListChecks size={16} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900 mb-1">表格清单一致性质控</h4>
                <p className="text-xs text-slate-600 leading-relaxed">
                  通过上传表格与清单文件，自动建立表格-清单映射关系并生成交互式复核页面。
                  经人工确认后，AI 引擎逐对反向核查——从清单反推表格中的每个数字，验证人数、
                  例次、百分比、统计量的一致性，最终生成分级质控报告。
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* ─── 右下角日志按钮 ────────────────────────────────────────── */}
      <button
        onClick={openLogModal}
        className="fixed bottom-6 right-6 z-30 w-12 h-12 rounded-full bg-slate-800 text-white shadow-lg hover:bg-slate-700 hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
        title="日志归档管理"
      >
        <FolderArchive size={20} />
      </button>

      {/* ─── 日志归档弹窗 ────────────────────────────────────────── */}
      {logModalOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/30 z-40"
            onClick={closeLogModal}
          />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-96 bg-white rounded-2xl shadow-2xl p-6">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-slate-800 text-white flex items-center justify-center">
                  {logUnlocked ? <FolderArchive size={18} /> : <Lock size={18} />}
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">
                    {logUnlocked ? "日志归档管理" : "管理员验证"}
                  </h3>
                  <p className="text-xs text-slate-500">
                    {logUnlocked ? "管理后端 file 文件夹" : "请输入管理员密码以继续"}
                  </p>
                </div>
              </div>
              <button
                onClick={closeLogModal}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            {!logUnlocked ? (
              <>
                <p className="text-sm text-slate-600 mb-4 leading-relaxed">
                  此功能包含敏感操作，需要管理员密码验证。
                </p>

                {adminError && (
                  <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
                    <AlertTriangle size={16} />
                    {adminError}
                  </div>
                )}

                <input
                  type="password"
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAdminVerify(); }}
                  placeholder="请输入管理员密码"
                  autoFocus
                  className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all mb-4"
                />

                <button
                  onClick={handleAdminVerify}
                  disabled={adminChecking || !adminPassword}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-slate-800 text-white text-sm font-semibold hover:bg-slate-700 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {adminChecking ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Lock size={16} />
                  )}
                  验证
                </button>
              </>
            ) : (
              <>
                <p className="text-sm text-slate-600 mb-4 leading-relaxed">
                  上传的文件会归档到 <code className="bg-slate-100 px-1 rounded text-xs">backend/files</code>。
                  您可以清空所有归档文件，或将它们打包下载用于排查问题。
                </p>

                {userCount !== null && (
                  <div className="mb-4 p-3 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-700 flex items-center gap-2">
                    <span className="text-base">👥</span>
                    当前系统已注册 <span className="font-bold text-slate-900">{userCount}</span> 位用户
                  </div>
                )}

                {logError && (
                  <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
                    <AlertTriangle size={16} />
                    {logError}
                  </div>
                )}

                <div className="flex gap-3">
                  <button
                    onClick={handleClearArchive}
                    disabled={logAction !== "idle"}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-red-200 text-red-600 text-sm font-semibold hover:bg-red-50 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {logAction === "clearing" ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Trash2 size={16} />
                    )}
                    清空文件
                  </button>
                  <button
                    onClick={handleDownloadArchive}
                    disabled={logAction !== "idle"}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-slate-800 text-white text-sm font-semibold hover:bg-slate-700 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {logAction === "downloading" ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Download size={16} />
                    )}
                    打包下载
                  </button>
                </div>
              </>
            )}
          </div>
        </>
      )}

      {/* ─── 右侧设置侧边栏 ────────────────────────────────────────── */}
      {/* 遮罩层 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 transition-opacity"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 侧边栏抽屉 */}
      <div
        className={`fixed top-0 right-0 h-full w-96 bg-white shadow-2xl z-50 transform transition-transform duration-300 ease-in-out flex flex-col ${
          sidebarOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-200">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-blue-600 text-white flex items-center justify-center">
              <Settings size={18} />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900">LLM 模型配置</h3>
              <p className="text-xs text-slate-500">设置您的 API Key 和模型参数</p>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="w-8 h-8 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* 表单区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* 当前配置提示 */}
          <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-500 space-y-1">
            <p className="font-semibold text-slate-700 mb-1">当前配置</p>
            <p>密钥：<code className="bg-slate-200 px-1 rounded">{llmConfig.LLM_API_KEY_masked || "（未设置）"}</code></p>
            <p>模型：<code className="bg-slate-200 px-1 rounded">{llmConfig.LLM_MODEL || "—"}</code></p>
            <p>端点：<code className="bg-slate-200 px-1 rounded text-[11px]">{llmConfig.LLM_API_BASE || "—"}</code></p>
          </div>

          {/* API Key */}
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">
              API Key
            </label>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm((prev) => ({ ...prev, api_key: e.target.value }))}
              placeholder="填写以覆盖，留空则保持现有配置"
              className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
            />
            <p className="text-xs text-slate-400 mt-1">密钥加密存储，填写后仅显示脱敏信息</p>
          </div>

          {/* Model */}
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">
              Model
            </label>
            <input
              type="text"
              value={form.model}
              onChange={(e) => setForm((prev) => ({ ...prev, model: e.target.value }))}
              placeholder="例如: deepseek-v4-pro"
              className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
            />
          </div>

          {/* Base URL */}
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">
              Base URL
            </label>
            <input
              type="text"
              value={form.api_base}
              onChange={(e) => setForm((prev) => ({ ...prev, api_base: e.target.value }))}
              placeholder="例如: https://api.deepseek.com/anthropic"
              className="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
            />
            <p className="text-xs text-slate-400 mt-1">Anthropic 兼容端点地址</p>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="px-6 py-4 border-t border-slate-200 flex items-center gap-3">
          {saved && (
            <span className="text-xs text-emerald-600 flex items-center gap-1 flex-1">
              <CheckCircle2 size={14} />
              保存成功，下次质控生效
            </span>
          )}
          <button
            onClick={() => setSidebarOpen(false)}
            className="px-4 py-2.5 rounded-xl border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={saveConfig}
            disabled={saving}
            className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {saving ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Save size={16} />
            )}
            {saving ? "保存中..." : "保存配置"}
          </button>
        </div>
      </div>
    </div>
  );
}
