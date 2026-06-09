import { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import { ChatMessage as ChatMessageType } from "../types";
import { useAuth } from "../hooks/useAuth";
import { useProject } from "../hooks/useProject";
import { useSSE } from "../hooks/useSSE";
import FileSidebar from "../components/FileSidebar";
import FileUpload from "../components/FileUpload";
import ChatMessage from "../components/ChatMessage";
import ChatInput from "../components/ChatInput";
import ReportPanel from "../components/ReportPanel";
import { Loader2, Trash2, HelpCircle, PanelRight } from "lucide-react";

/** Map internal tool names to user-facing Chinese labels */
function getToolDisplayName(tool: string, argsSummary?: string): string {
  const nameMap: Record<string, string> = {
    "Bash": "运行命令",
    "Read": "读取文件",
    "Write": "写入文件",
    "Edit": "编辑文件",
    "Grep": "搜索文件",
    "Glob": "查找文件",
  };
  const label = nameMap[tool] || tool;
  if (argsSummary) return `${label} (${argsSummary})`;
  return label;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [canGenerate, setCanGenerate] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [toolLabel, setToolLabel] = useState("");
  const [currentStage, setCurrentStage] = useState("");
  const [hasSession, setHasSession] = useState(false);
  const [reportContent, setReportContent] = useState("");
  const [showReport, setShowReport] = useState(false);
  const [panelWidth, setPanelWidth] = useState(420);
  const [isDragging, setIsDragging] = useState(false);
  const [errorPopup, setErrorPopup] = useState("");
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);
  const [projects, setProjects] = useState<string[]>([]);
  const [showNewInput, setShowNewInput] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();
  const { project, setProject } = useProject();
  const { connect } = useSSE();
  const navigate = useNavigate();

  // Fetch available projects
  useEffect(() => {
    api.get("/projects").then((res) => {
      const list: string[] = res.data.projects || [];
      setProjects(list.includes(project) ? list : [...list, project]);
    }).catch(() => {});
  }, [project]);

  // When project switches, reset page state and refresh
  useEffect(() => {
    setMessages([]);
    setHasSession(false);
    setStatusText("");
    setCurrentStage("");
    setSidebarRefresh((p) => p + 1);
    api.post("/chat/clear").catch(() => {});
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

  useEffect(() => {
    api.get("/files/list").then((res) => {
      const hasLog = res.data.files.some((f: any) => f.name === "dm-log.json");
      const hasProtocol = res.data.files.some((f: any) => f.category === "protocol");
      setCanGenerate(hasLog && hasProtocol);
    }).catch(() => {});
  }, [sidebarRefresh]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Resize handle drag logic
  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      setIsDragging(true);
      dragStartX.current = e.clientX;
      dragStartWidth.current = panelWidth;
      e.preventDefault();
    },
    [panelWidth]
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = dragStartX.current - e.clientX;
      setPanelWidth(Math.min(640, Math.max(300, dragStartWidth.current + delta)));
    };

    const handleMouseUp = () => setIsDragging(false);

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isDragging]);

  const addMessage = useCallback((msg: ChatMessageType) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      // Merge consecutive same-role text (only for user/claude, never system)
      if (last && last.role === msg.role &&
          !last.questions && !msg.questions &&
          last.role !== "system") {
        return [...prev.slice(0, -1), { ...last, content: last.content + msg.content }];
      }
      return [...prev, msg];
    });
  }, []);

  const handleSSEEvent = useCallback((type: string, data: any) => {
    switch (type) {
      case "text":
        addMessage({ role: "claude", content: data.content || "" });
        break;
      case "question":
        // NOTE: This event type is reserved for future use when the backend
        // accumulates streamed text and emits structured question events.
        // Currently, questions are parsed client-side from Claude's text output
        // via parseQuestionBlocks() in ChatMessage.tsx.
        addMessage({ role: "system", content: "", questions: data.questions });
        break;
      case "tool_use":
        if (data.status === "running") {
          const label = getToolDisplayName(data.tool, data.args_summary);
          setToolLabel(label);
          setStatusText(`${label} — 运行中`);
        } else if (data.status === "completed") {
          setStatusText(`${toolLabel || data.tool} — 完成`);
          // Clear after 4 seconds unless replaced by next tool
          setTimeout(() => {
            setStatusText((prev) => prev.includes("完成") ? "" : prev);
          }, 4000);
        }
        break;
      case "file_update":
        setSidebarRefresh((prev) => prev + 1);
        if (data.filename) {
          setStatusText(`文件已更新: ${data.filename}`);
          setTimeout(() => setStatusText((prev) => prev.startsWith("文件已更新") ? "" : prev), 2000);
        }
        break;
      case "error":
        setStatusText(`错误: ${data.message}`);
        setErrorPopup(data.message);
        break;
      case "stage":
        setCurrentStage(data.content || "");
        break;
      case "done":
        setStatusText("");
        setSidebarRefresh((prev) => prev + 1);
        api.get("/files/read/DMP生成报告.md")
          .then(res => { setReportContent(res.data.content); setShowReport(true); })
          .catch(() => {});
        break;
    }
  }, [addMessage, toolLabel]);

  const handleDone = useCallback(() => {
    setIsGenerating(false);
    setStatusText("");
  }, []);

  const handleSend = (text: string) => {
    addMessage({ role: "user", content: text });
    setIsGenerating(true);
    setStatusText("Processing...");
    connect(`/api/${project}/chat/send`, handleSSEEvent, handleDone, { message: text });
  };

  const handleStartDMP = () => {
    setCurrentStage("");
    setReportContent("");
    setShowReport(false);
    setHasSession(true);
    setIsGenerating(true);
    setStatusText("Starting DMP generation...");
    connect(`/api/${project}/chat/start-dmp`, handleSSEEvent, handleDone);
  };

  const handleContinueDMP = () => {
    setCurrentStage("");
    setReportContent("");
    setShowReport(false);
    setIsGenerating(true);
    setStatusText("Continuing DMP session...");
    connect(`/api/${project}/chat/continue-dmp`, handleSSEEvent, handleDone);
  };

  const handleAnswer = (answer: string) => {
    handleSend(answer);
  };

  const handleClearSession = async () => {
    try {
      await api.post("/chat/clear");
      setMessages([]);
      setHasSession(false);
      setStatusText("Session cleared — fresh context");
      setTimeout(() => setStatusText(""), 2000);
    } catch {
      setStatusText("Failed to clear session");
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950 font-sans antialiased">
      <FileSidebar refreshTrigger={sidebarRefresh} workspace={user?.workspace} />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="bg-white border-b border-slate-200/80 px-6 py-3 flex items-center justify-between shadow-sm shrink-0">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="Logo" className="h-7" />
            <span className="font-bold text-slate-900">DMP Generation Chat</span>
            <span className="text-slate-300">|</span>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-slate-400 font-mono">Project:</label>
              {showNewInput ? (
                <div className="flex items-center gap-1">
                  <input
                    type="text"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleCreateProject(); if (e.key === "Escape") setShowNewInput(false); }}
                    onBlur={() => { if (!newProjectName.trim()) setShowNewInput(false); }}
                    placeholder="project name..."
                    className="w-32 px-2 py-1 text-xs font-mono bg-white border border-blue-300 rounded-md focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-100"
                    autoFocus
                  />
                  <button onClick={handleCreateProject} className="text-xs text-blue-600 hover:text-blue-800 font-medium">OK</button>
                </div>
              ) : (
                <select
                  value={project}
                  onChange={(e) => handleProjectSelect(e.target.value)}
                  className="w-36 px-2 py-1 text-xs font-mono bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:border-blue-400 cursor-pointer"
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
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("/help")}
              className="text-xs text-slate-500 hover:text-blue-600 transition-colors flex items-center gap-1 cursor-pointer"
              title="使用帮助"
            >
              <HelpCircle size={14} />
              帮助
            </button>
            {reportContent && (
              <button
                onClick={() => setShowReport(!showReport)}
                className={`text-xs transition-colors flex items-center gap-1 cursor-pointer ${
                  showReport ? "text-blue-600" : "text-slate-500 hover:text-blue-600"
                }`}
                title="切换生成报告"
              >
                <PanelRight size={14} />
                报告
              </button>
            )}
            <button
              onClick={handleClearSession}
              disabled={isGenerating}
              className="text-xs text-slate-500 hover:text-red-600 disabled:text-slate-300 transition-colors flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
              title="Clear conversation context"
            >
              <Trash2 size={14} />
              New Session
            </button>
          </div>
        </header>

        {/* Upload Area */}
        <div className="px-6 pt-4 shrink-0">
          <FileUpload onUploaded={() => { setSidebarRefresh((p) => p + 1); setCanGenerate(true); }} />
        </div>

        {/* Status Area — two-tier: tool status bar + stage progress */}
        {(statusText || currentStage) && (
          <div className="mx-6 mt-2 space-y-1.5 shrink-0">
            {/* Tier 1: Tool running / error / transient status */}
            {statusText && (
              <div className={`px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-mono transition-colors duration-300 ${
                statusText.includes("错误") || statusText.includes("Error")
                  ? "bg-red-50 border border-red-200 text-red-700"
                  : statusText.includes("完成") || statusText.includes("文件已更新")
                    ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                    : "bg-slate-100 border border-slate-200 text-slate-600"
              }`}>
                {isGenerating && !statusText.includes("完成") && !statusText.includes("错误") && (
                  <Loader2 size={14} className="animate-spin text-blue-500 shrink-0" />
                )}
                <span className="truncate">{statusText}</span>
              </div>
            )}

            {/* Tier 2: Current stage — single line, jumps to latest */}
            {currentStage && (
              <div className="px-4 py-2 rounded-lg bg-white/60 border border-slate-100 text-xs font-mono text-slate-500 truncate shadow-sm transition-all duration-300">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 mr-2 align-middle shadow-[0_0_4px_rgba(96,165,250,0.5)]" />
                {currentStage}
              </div>
            )}
          </div>
        )}

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1 messages-area">
          {messages.map((msg, i) => (
            <ChatMessage key={i} message={msg} onAnswer={handleAnswer} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <ChatInput
          onStartDMP={handleStartDMP}
          onContinueDMP={handleContinueDMP}
          disabled={isGenerating}
          canGenerate={canGenerate}
          hasSession={hasSession}
        />
      </div>

      {/* Resize Handle + Right Panel */}
      {showReport && reportContent && (
        <>
          {/* Drag handle */}
          <div
            onMouseDown={handleResizeStart}
            className={`w-1.5 shrink-0 cursor-col-resize relative -ml-px z-10 transition-colors duration-150 ${
              isDragging
                ? "resize-handle-active"
                : "bg-transparent hover:bg-blue-200/70"
            }`}
          >
            {/* Wider hit area */}
            <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
          </div>

          <ReportPanel
            content={reportContent}
            width={panelWidth}
            onClose={() => setShowReport(false)}
          />
        </>
      )}
      {errorPopup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
            <div className="bg-red-50 border-b border-red-100 px-6 py-4 flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <span className="text-red-500 text-xl font-bold">!</span>
              </div>
              <h3 className="text-lg font-semibold text-red-800">生成中断</h3>
            </div>
            <div className="px-6 py-4">
              <p className="text-gray-700 text-sm leading-relaxed">{errorPopup}</p>
            </div>
            <div className="px-6 py-3 bg-gray-50 flex justify-end gap-3">
              <button
                onClick={() => setErrorPopup("")}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-100 transition-colors"
              >
                关闭
              </button>
              <button
                onClick={() => {
                  setErrorPopup("");
                  setIsGenerating(false);
                }}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
              >
                确认并重试
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
