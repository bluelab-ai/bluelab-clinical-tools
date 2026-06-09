import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { FolderOpen, Trash2, LogOut, Settings, ChevronUp, Sun, Moon, ChevronRight } from "lucide-react";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import { FileInfo } from "../types";

interface Props {
  refreshTrigger: number;
  workspace?: string;
}

const labels: Record<string, string> = { log: "Logs", protocol: "Protocols", dmp: "DMP Outputs" };

export default function FileSidebar({ refreshTrigger, workspace }: Props) {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);
  const { logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    api.get("/files/list").then((res) => setFiles(res.data.files)).catch(() => {});
  }, [refreshTrigger]);

  // Close menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        badgeRef.current && !badgeRef.current.contains(e.target as Node)
      ) {
        setShowMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showMenu]);

  const handleLogout = useCallback(() => {
    logout();
    navigate("/login");
  }, [logout, navigate]);

  const handleDownload = async (name: string) => {
    const res = await api.get(`/files/download/${name}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete ${name}?`)) return;
    await api.delete(`/files/delete/${name}`);
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const byCategory = (cat: string) => files.filter((f) => f.category === cat);

  return (
    <aside className="w-60 bg-white dark:bg-slate-900 border-r border-slate-200/80 dark:border-slate-800 p-4 overflow-y-auto flex flex-col gap-5 shrink-0">
      <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
        <FolderOpen size={18} className="text-blue-600 dark:text-blue-400" />
        <h3 className="font-bold text-sm">Workspace</h3>
      </div>

      {(["log", "protocol", "dmp"] as const).map((cat) => {
        const items = byCategory(cat);
        return (
          <div key={cat}>
            <div className="font-mono text-[10px] tracking-wider uppercase font-semibold text-slate-400 mb-2">
              {labels[cat]}
            </div>
            {items.length === 0 ? (
              <p className="text-xs text-slate-300 italic">None</p>
            ) : (
              items.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-50 transition-colors group"
                  title={`${f.name} (${(f.size / 1024).toFixed(1)} KB)`}
                >
                  <span
                    onClick={() => handleDownload(f.name)}
                    className="text-xs text-slate-600 cursor-pointer hover:text-blue-600 transition-colors truncate flex-1"
                  >
                    {f.name}
                  </span>
                  <button
                    onClick={() => handleDelete(f.name)}
                    className="text-slate-300 hover:text-red-500 cursor-pointer ml-1 opacity-0 group-hover:opacity-100 transition-all p-0.5"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        );
      })}

      {/* User badge — bottom of sidebar */}
      {workspace && (
        <div className="mt-auto pt-3 border-t border-slate-100 dark:border-slate-800 relative">
          <div
            ref={badgeRef}
            onClick={() => setShowMenu(!showMenu)}
            className="flex items-center justify-between gap-2 px-3 py-2 rounded-full bg-slate-50/80 dark:bg-slate-800/80 border border-slate-100 dark:border-slate-700 text-xs font-mono text-slate-600 dark:text-slate-300 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700 hover:border-slate-200 dark:hover:border-slate-600 transition-all select-none"
          >
            <span className="truncate">{workspace}</span>
            <ChevronUp size={12} className={`text-slate-400 dark:text-slate-500 transition-transform duration-200 shrink-0 ${showMenu ? "" : "rotate-180"}`} />
          </div>

          {/* Popup menu */}
          {showMenu && (
            <div
              ref={menuRef}
              className="absolute bottom-full left-3 right-3 mb-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg shadow-slate-200/50 dark:shadow-slate-900/50 animate-in slide-in-from-bottom-2 fade-in duration-150"
            >
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors cursor-pointer rounded-t-xl"
              >
                <LogOut size={14} className="text-slate-400 dark:text-slate-500" />
                退出登录
              </button>
              <div className="h-px bg-slate-100 dark:bg-slate-700 mx-3" />
              <div className="relative group/settings">
                <div className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors cursor-pointer rounded-b-xl">
                  <div className="flex items-center gap-2.5">
                    <Settings size={14} className="text-slate-400 dark:text-slate-500" />
                    系统设置
                  </div>
                  <ChevronRight size={12} className="text-slate-400 dark:text-slate-500" />
                </div>
                {/* Sub-menu — appears on hover */}
                <div className="absolute left-full top-0 ml-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg shadow-slate-200/50 dark:shadow-slate-900/50 overflow-hidden opacity-0 invisible group-hover/settings:opacity-100 group-hover/settings:visible transition-all duration-150 min-w-[100px]">
                  <button
                    onClick={() => { toggleTheme("light"); setShowMenu(false); }}
                    className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-sm cursor-pointer transition-colors ${
                      theme === "light"
                        ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
                        : "text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                    }`}
                  >
                    <Sun size={14} className={theme === "light" ? "text-blue-500" : "text-slate-400 dark:text-slate-500"} />
                    浅色
                  </button>
                  <div className="h-px bg-slate-100 dark:bg-slate-700 mx-3" />
                  <button
                    onClick={() => { toggleTheme("dark"); setShowMenu(false); }}
                    className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-sm cursor-pointer transition-colors ${
                      theme === "dark"
                        ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
                        : "text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                    }`}
                  >
                    <Moon size={14} className={theme === "dark" ? "text-blue-500" : "text-slate-400 dark:text-slate-500"} />
                    深色
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
