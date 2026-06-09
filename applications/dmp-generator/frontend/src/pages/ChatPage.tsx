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
import { Loader2, Trash2, HelpCircle } from "lucide-react";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [canGenerate, setCanGenerate] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [statusText, setStatusText] = useState("");
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
    setStatusText("");
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
        addMessage({ role: "system", content: "", questions: data.questions });
        break;
      case "tool_use":
        setStatusText(`${data.tool || "script"} — ${data.status}`);
        break;
      case "file_update":
        setSidebarRefresh((prev) => prev + 1);
        break;
      case "error":
        setStatusText(`Error: ${data.message}`);
        break;
      case "done":
        setStatusText("");
        setSidebarRefresh((prev) => prev + 1);
        break;
    }
  }, [addMessage]);

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
    setIsGenerating(true);
    setStatusText("Starting DMP generation...");
    connect(`/api/${project}/chat/start-dmp`, handleSSEEvent, handleDone);
  };

  const handleAnswer = (answer: string) => {
    handleSend(answer);
  };

  const handleClearSession = async () => {
    try {
      await api.post("/chat/clear");
      setMessages([]);
      setStatusText("Session cleared — fresh context");
      setTimeout(() => setStatusText(""), 2000);
    } catch {
      setStatusText("Failed to clear session");
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 font-sans antialiased">
      <FileSidebar refreshTrigger={sidebarRefresh} />

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
            <button
              onClick={handleClearSession}
              disabled={isGenerating}
              className="text-xs text-slate-500 hover:text-red-600 disabled:text-slate-300 transition-colors flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
              title="Clear conversation context"
            >
              <Trash2 size={14} />
              New Session
            </button>
            <span className="text-xs text-slate-400 font-mono">{user?.workspace}</span>
          </div>
        </header>

        {/* Upload Area */}
        <div className="px-6 pt-4 shrink-0">
          <FileUpload onUploaded={() => { setSidebarRefresh((p) => p + 1); setCanGenerate(true); }} />
        </div>

        {/* Status Bar — single-line system output */}
        {statusText && (
          <div className="mx-6 mt-2 px-4 py-2 bg-slate-100 border border-slate-200 rounded-lg flex items-center gap-2 text-sm text-slate-600 font-mono shrink-0">
            {isGenerating && <Loader2 size={14} className="animate-spin text-blue-500 shrink-0" />}
            <span className="truncate">{statusText}</span>
          </div>
        )}

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1">
          {messages.map((msg, i) => (
            <ChatMessage key={i} message={msg} onAnswer={handleAnswer} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <ChatInput
          onStartDMP={handleStartDMP}
          disabled={isGenerating}
          canGenerate={canGenerate}
        />
      </div>
    </div>
  );
}
