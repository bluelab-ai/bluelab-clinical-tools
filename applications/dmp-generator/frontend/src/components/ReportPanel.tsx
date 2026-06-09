import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { X } from "lucide-react";

interface Props {
  content: string;
  width: number;
  onClose: () => void;
}

function extractTextContent(children: any): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractTextContent).join("");
  if (children && typeof children === "object" && "props" in children) {
    return extractTextContent(children.props.children);
  }
  return "";
}

export default function ReportPanel({ content, width, onClose }: Props) {
  const [closing, setClosing] = useState(false);

  const handleClose = () => {
    setClosing(true);
    setTimeout(onClose, 200);
  };

  return (
    <aside
      style={{ width }}
      className={`bg-white flex flex-col shrink-0 h-screen report-panel-enter ${
        closing ? "opacity-0 translate-x-6 transition-all duration-200 ease-in" : ""
      }`}
    >
      {/* Header — refined with subtle gradient */}
      <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between shrink-0 bg-gradient-to-b from-white to-slate-50/50">
        <div className="flex items-center gap-2.5">
          <div className="w-1.5 h-4 rounded-full bg-blue-500/70" />
          <span className="font-semibold text-sm text-slate-700 tracking-tight">DMP 生成报告</span>
        </div>
        <button
          onClick={handleClose}
          className="p-1.5 hover:bg-slate-200/80 rounded-lg text-slate-400 hover:text-slate-600 cursor-pointer transition-all duration-150 hover:scale-110 active:scale-95"
        >
          <X size={15} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4 report-panel-scroll">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => (
              <h1 className="text-lg font-bold text-slate-900 mt-6 mb-3 first:mt-0 tracking-tight">
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2 className="text-base font-semibold text-slate-800 mt-5 mb-2.5 first:mt-0 flex items-center gap-2">
                <span className="w-1 h-4 rounded-full bg-blue-400/60 inline-block shrink-0" />
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 className="text-sm font-semibold text-slate-700 mt-4 mb-2 first:mt-0">
                {children}
              </h3>
            ),
            p: ({ children }) => {
              const text = extractTextContent(children);
              const statusMatch = text.match(
                /^(\*\*已完成\*\*|\*\*需确认\*\*|\*\*已跳过\*\*)([\s\S]*)/
              );
              if (statusMatch) {
                const statusLabel = statusMatch[1].replace(/\*\*/g, "");
                const restText = statusMatch[2] || "";
                const isDone = statusLabel === "已完成";
                const isConfirm = statusLabel === "需确认";
                return (
                  <p className="mb-1.5 last:mb-0 flex items-start gap-2">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold border shrink-0 mt-0.5 transition-colors ${
                        isDone
                          ? "bg-emerald-50/80 border-emerald-200 text-emerald-700"
                          : isConfirm
                            ? "bg-amber-50/80 border-amber-200 text-amber-700"
                            : "bg-slate-50 border-slate-200 text-slate-500"
                      }`}
                    >
                      {statusLabel}
                    </span>
                    <span className="text-slate-600 text-sm leading-relaxed">{restText}</span>
                  </p>
                );
              }
              return (
                <p className="mb-2 last:mb-0 text-sm text-slate-600 leading-relaxed">
                  {children}
                </p>
              );
            },
            strong: ({ children }) => (
              <strong className="font-semibold text-slate-900">{children}</strong>
            ),
            ul: ({ children }) => (
              <ul className="list-disc pl-5 mb-3 space-y-1 text-sm text-slate-600 marker:text-slate-400">
                {children}
              </ul>
            ),
            ol: ({ children }) => (
              <ol className="list-decimal pl-5 mb-3 space-y-1 text-sm text-slate-600 marker:text-slate-400">
                {children}
              </ol>
            ),
            li: ({ children }) => <li className="text-slate-600">{children}</li>,
            code: ({ className, children, ...props }: any) => {
              const isInline = !className;
              if (isInline) {
                return (
                  <code
                    className="bg-slate-100 text-rose-600 text-xs px-1.5 py-0.5 rounded-md font-mono"
                    {...props}
                  >
                    {children}
                  </code>
                );
              }
              return (
                <pre className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-3 overflow-x-auto shadow-sm">
                  <code
                    className="text-xs text-slate-700 font-mono leading-relaxed"
                    {...props}
                  >
                    {children}
                  </code>
                </pre>
              );
            },
            blockquote: ({ children }) => {
              const text = extractTextContent(children);
              if (
                text.includes("警告") ||
                text.includes("注意") ||
                text.includes("不一致") ||
                text.includes("缺失") ||
                text.includes("冲突")
              ) {
                return (
                  <blockquote className="border-l-4 border-amber-400 bg-amber-50/70 pl-4 py-3 rounded-r-xl my-3 shadow-sm">
                    <div className="text-sm text-amber-800 [&>p]:mb-1">{children}</div>
                  </blockquote>
                );
              }
              return (
                <blockquote className="border-l-4 border-blue-300 bg-blue-50/50 pl-4 py-3 rounded-r-xl my-3 text-slate-600 italic text-sm">
                  {children}
                </blockquote>
              );
            },
            a: ({ href, children }) => (
              <a
                href={href}
                className="text-blue-600 hover:text-blue-700 underline decoration-blue-200 hover:decoration-blue-400 transition-colors text-sm"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            ),
            table: ({ children }) => (
              <div className="overflow-x-auto my-3 rounded-xl border border-slate-200 shadow-sm">
                <table className="w-full border-collapse text-sm">{children}</table>
              </div>
            ),
            th: ({ children }) => (
              <th className="bg-slate-50 text-slate-600 font-semibold px-4 py-2.5 text-left border-b border-slate-200 whitespace-nowrap text-xs uppercase tracking-wide">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="px-4 py-2.5 border-b border-slate-50 text-slate-600 text-sm">
                {children}
              </td>
            ),
            hr: () => <hr className="border-slate-100 my-4" />,
            em: ({ children }) => (
              <em className="italic text-slate-500">{children}</em>
            ),
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </aside>
  );
}
