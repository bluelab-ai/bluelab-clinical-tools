import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage as ChatMessageType, Question } from "../types";
import QuestionCard from "./QuestionCard";

interface Props {
  message: ChatMessageType;
  onAnswer: (answer: string) => void;
}

/** Extract plain text from React children for pattern matching */
function extractTextContent(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractTextContent).join("");
  if (children && typeof children === "object" && "props" in children) {
    return extractTextContent((children as any).props.children);
  }
  return "";
}

/** Map status label to visual config */
function getStatusConfig(label: string) {
  const map: Record<string, { bg: string; border: string; text: string; icon: string }> = {
    "已完成": { bg: "bg-emerald-50", border: "border-emerald-300", text: "text-emerald-700", icon: "✓" },
    "需确认": { bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-700", icon: "?" },
    "已跳过": { bg: "bg-slate-100", border: "border-slate-300", text: "text-slate-500", icon: "—" },
  };
  return map[label] || map["已完成"];
}

const roleStyles: Record<string, { label: string; color: string; bg: string }> = {
  user: { label: "You", color: "text-blue-600", bg: "bg-blue-50" },
  claude: { label: "Claude", color: "text-emerald-600", bg: "bg-emerald-50" },
  system: { label: "", color: "text-amber-600", bg: "bg-amber-50" },
};

/** Clean streamed text from DeepSeek V4 Pro:
 *  1. Fix ### headings that arrive mid-line (missing newline before #)
 *  2. Strip leaked thinking: plain-text "阶段 N/M：..." lines that duplicate
 *     the markdown heading that follows
 *  3. Split body text that leaked onto the heading line so ReactMarkdown
 *     parses them as separate h3 + p elements */
function cleanStreamedText(text: string): string {
  // Ensure ### always starts on a new line for markdown heading parsing.
  // Use [^\n#] to prevent splitting a ### heading itself (e.g. "###" → "#\n##").
  let cleaned = text.replace(/([^\n#])(#{1,6}\s)/g, "$1\n$2");

  // Remove plain-text "阶段 N/M：..." lines that are leaked thinking.
  cleaned = cleaned.replace(
    /(?:^|\n)(阶段\s*\d+\s*\/\s*\d+\s*[：:][^\n]*)\n(?:([^\n]*)\n)?(?=\s*#{1,6}\s*阶段)/g,
    (_full, _header, desc) => {
      if (desc && desc.trim() && !/[#*\[\]|>]/.test(desc)) {
        return "\n";
      }
      return "\n";
    },
  );

  // Split body text that leaked onto the phase heading line.
  // "### 阶段 8/9：质量检查QA 通过：..." → "### 阶段 8/9：质量检查\n\nQA 通过：..."
  cleaned = cleaned.replace(
    /^(#{1,6}\s*阶段\s*\d+\s*\/\s*\d+\s*[：:]\s*)(.*)$/gm,
    (full, prefix, rest) => {
      const bodyIdx = rest.search(
        /[A-Z]{2,}|QA\s|已完成|需确认|已跳过|通过[：:]|无残留|无冲突|步骤\s*\d|开始|正在|已经|继续|目前/,
      );
      if (bodyIdx > 0) {
        return (
          prefix +
          rest.slice(0, bodyIdx).trimEnd() +
          "\n\n" +
          rest.slice(bodyIdx)
        );
      }
      return full;
    },
  );

  return cleaned;
}

/** Parse [[QUESTION:...]]...[[END_QUESTION]] blocks from text. Returns clean text + extracted questions. */
function parseQuestionBlocks(content: string): { cleanText: string; questions: Question[] } {
  const questions: Question[] = [];
  let cleanText = cleanStreamedText(content);

  // Match complete question blocks: [[QUESTION:type:...]] ... [[END_QUESTION]]
  const blockRegex = /\[\[QUESTION:type:([^\]]+)\]\]([\s\S]*?)\[\[END_QUESTION\]\]/g;

  let match: RegExpExecArray | null;
  while ((match = blockRegex.exec(content)) !== null) {
    const [fullMatch, typeStr, bodyText] = match;

    // Parse QUESTION_TEXT
    const textMatch = bodyText.match(/\[\[QUESTION_TEXT:([^\]]*?)\]\]/);
    const rawQuestionText = textMatch ? textMatch[1].trim() : "";

    // Parse OPTIONs
    const optionRegex = /\[\[OPTION:([A-Z]+):([^\]]*)\]\]/g;
    const options: string[] = [];
    let optMatch: RegExpExecArray | null;
    while ((optMatch = optionRegex.exec(bodyText)) !== null) {
      options.push(optMatch[2].trim());
    }

    const qType: "choice" | "input" =
      typeStr.includes("input") && !typeStr.includes("choice") ? "input" : "choice";

    // Split sub-questions by "问题N" pattern for one-at-a-time display
    const subQuestionRegex = /问题(\d+)[（(][^)）]*[)）][：:]\s*/g;
    const subQuestions: { id: string; text: string }[] = [];
    let lastIndex = 0;
    let subMatch: RegExpExecArray | null;
    const subRegex = new RegExp(subQuestionRegex.source, "g");

    while ((subMatch = subRegex.exec(rawQuestionText)) !== null) {
      if (lastIndex > 0) {
        // Save previous sub-question
        subQuestions[subQuestions.length - 1].text = rawQuestionText.slice(lastIndex, subMatch.index).trim();
      }
      const qNum = subMatch[1];
      const label = subMatch[0];
      subQuestions.push({ id: `q${qNum}`, text: "" });
      lastIndex = subMatch.index;
    }
    // Last sub-question
    if (subQuestions.length > 0 && lastIndex > 0) {
      subQuestions[subQuestions.length - 1].text = rawQuestionText.slice(lastIndex).trim();
    }

    if (subQuestions.length > 0) {
      // Create one Question per sub-question, each with the same options
      for (const sq of subQuestions) {
        const displayText = sq.text || rawQuestionText;
        if (displayText) {
          questions.push({
            id: sq.id,
            text: displayText,
            type: qType,
            options: qType === "choice" && options.length > 0 ? options : undefined,
          });
        }
      }
    } else if (rawQuestionText) {
      // No sub-questions found, treat as single question
      questions.push({
        id: "q1",
        text: rawQuestionText,
        type: qType,
        options: qType === "choice" && options.length > 0 ? options : undefined,
      });
    }

    cleanText = cleanText.replace(fullMatch, "");
  }

  // Also strip any dangling partial markers (incomplete blocks during streaming)
  cleanText = cleanText
    .replace(/\[\[QUESTION:type:[^\]]*\]\]/g, "")
    .replace(/\[\[QUESTION_TEXT:[^\]]*\]\]/g, "")
    .replace(/\[\[OPTION:[A-Z]+:[^\]]*\]\]/g, "")
    .replace(/\[\[END_QUESTION\]\]/g, "")
    .trim();

  return { cleanText, questions };
}

export default function ChatMessage({ message, onAnswer }: Props) {
  const style = roleStyles[message.role] || roleStyles.system;

  // System messages without questions are handled by the status bar in ChatPage
  if (message.role === "system" && !message.questions) {
    return null;
  }

  // Parse question blocks from claude text (always, to catch streaming completions)
  let displayContent = message.content || "";
  let parsedQuestions: Question[] = [];

  if (message.role === "claude" && message.content) {
    const result = parseQuestionBlocks(message.content);
    displayContent = result.cleanText;
    parsedQuestions = result.questions;
  }

  // Merge SSE-provided questions with parsed questions
  const allQuestions = [...(message.questions || []), ...parsedQuestions];

  // If nothing to show, don't render
  if (!displayContent && allQuestions.length === 0) {
    return null;
  }

  return (
    <div className="mb-4">
      {/* Role label */}
      {style.label && (
        <span className={`inline-block px-2 py-0.5 rounded-md text-xs font-semibold ${style.color} ${style.bg}`}>
          {style.label}
        </span>
      )}

      {/* Clean text content — only show if there's non-question text */}
      {displayContent && (
        <div className="mt-1.5 text-sm leading-relaxed text-slate-700">
          {message.role === "claude" ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => (
                  <h1 className="text-xl font-bold text-slate-900 mt-5 mb-2 first:mt-0">{children}</h1>
                ),
                h2: ({ children }) => (
                  <h2 className="text-lg font-bold text-slate-900 mt-4 mb-2 first:mt-0">{children}</h2>
                ),
                h3: ({ children }) => {
                  const text = extractTextContent(children);
                  const isPhaseHeader = /^阶段\s*\d+\/\d+/.test(text);
                  if (isPhaseHeader) {
                    return (
                      <div className="flex items-center gap-3 mt-6 mb-3 first:mt-0">
                        <div className="h-px flex-1 bg-gradient-to-r from-blue-200 to-blue-100" />
                        <h3 className="text-sm font-bold text-blue-700 bg-blue-50 px-4 py-1.5 rounded-full border border-blue-200 whitespace-nowrap">
                          {children}
                        </h3>
                        <div className="h-px flex-1 bg-gradient-to-l from-blue-200 to-blue-100" />
                      </div>
                    );
                  }
                  return <h3 className="text-base font-bold text-slate-800 mt-3 mb-1.5 first:mt-0">{children}</h3>;
                },
                p: ({ children }) => {
                  const text = extractTextContent(children);
                  // AI disclosure paragraphs (may not be in a blockquote)
                  if (/^(以下字段经过|AI.*(?:处理|审核|生成|介入|参与))/.test(text) || text.includes("请人工确认准确性")) {
                    return (
                      <div className="border-l-4 border-purple-400 bg-purple-50/60 pl-4 py-3 rounded-r-lg my-3">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold text-purple-700 uppercase tracking-wide">AI 处理披露</span>
                        </div>
                        <p className="text-sm text-purple-800 mb-1 last:mb-0">{children}</p>
                      </div>
                    );
                  }
                  const statusMatch = text.match(/^(\*\*已完成\*\*|\*\*需确认\*\*|\*\*已跳过\*\*)([\s\S]*)/);
                  if (statusMatch) {
                    const statusLabel = statusMatch[1].replace(/\*\*/g, "");
                    const restTextRaw = statusMatch[2] || "";
                    const cfg = getStatusConfig(statusLabel);
                    return (
                      <p className="mb-1.5 last:mb-0 flex items-start gap-2">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold border ${cfg.bg} ${cfg.border} ${cfg.text} shrink-0 mt-0.5`}>
                          {cfg.icon} {statusLabel}
                        </span>
                        <span className="text-slate-700 text-sm">{restTextRaw}</span>
                      </p>
                    );
                  }
                  return <p className="mb-2 last:mb-0">{children}</p>;
                },
                strong: ({ children }) => (
                  <strong className="font-semibold text-slate-900">{children}</strong>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>
                ),
                li: ({ children }) => (
                  <li className="text-slate-700">{children}</li>
                ),
                code: ({ className, children, ...props }: any) => {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code className="bg-slate-100 text-rose-600 text-xs px-1.5 py-0.5 rounded font-mono" {...props}>
                        {children}
                      </code>
                    );
                  }
                  return (
                    <pre className="bg-slate-100 border border-slate-200 rounded-xl p-4 mb-3 overflow-x-auto">
                      <code className="text-xs text-slate-700 font-mono leading-relaxed" {...props}>
                        {children}
                      </code>
                    </pre>
                  );
                },
                blockquote: ({ children }) => {
                  const text = extractTextContent(children);
                  if (text.includes("AI处理披露") || text.includes("AI 处理披露") || text.includes("请人工确认准确性")) {
                    return (
                      <blockquote className="border-l-4 border-purple-400 bg-purple-50/60 pl-4 py-3 rounded-r-lg my-3">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold text-purple-700 uppercase tracking-wide">AI 处理披露</span>
                        </div>
                        <div className="text-sm text-purple-800 [&>p]:mb-1">{children}</div>
                      </blockquote>
                    );
                  }
                  if (text.includes("警告") || text.includes("注意") || text.includes("不一致") || text.includes("缺失") || text.includes("冲突")) {
                    return (
                      <blockquote className="border-l-4 border-amber-400 bg-amber-50/60 pl-4 py-3 rounded-r-lg my-3">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold text-amber-700 uppercase tracking-wide">注意</span>
                        </div>
                        <div className="text-sm text-amber-800 [&>p]:mb-1">{children}</div>
                      </blockquote>
                    );
                  }
                  return (
                    <blockquote className="border-l-4 border-blue-300 bg-blue-50/50 pl-4 py-2 rounded-r-lg my-2 text-slate-600 italic">
                      {children}
                    </blockquote>
                  );
                },
                a: ({ href, children }) => (
                  <a href={href} className="text-blue-600 hover:text-blue-700 underline decoration-blue-200 hover:decoration-blue-400 transition-colors" target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto my-3 rounded-xl border border-slate-200 shadow-sm">
                    <table className="w-full border-collapse text-sm">
                      {children}
                    </table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="bg-slate-100 text-slate-700 font-semibold px-4 py-2.5 text-left border-b border-slate-200 whitespace-nowrap">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="px-4 py-2.5 border-b border-slate-100 text-slate-700">
                    {children}
                  </td>
                ),
                hr: () => (
                  <hr className="border-slate-200 my-4" />
                ),
                em: ({ children }) => (
                  <em className="italic text-slate-600">{children}</em>
                ),
              }}
            >
              {displayContent}
            </ReactMarkdown>
          ) : (
            <div className="whitespace-pre-wrap">{displayContent}</div>
          )}
        </div>
      )}

      {/* Question Cards — one per question for "一个一个问" */}
      {allQuestions.map((q, i) => (
        <div key={`${q.id}-${i}`} className="mt-3">
          <QuestionCard questions={[q]} onAnswer={onAnswer} />
        </div>
      ))}
    </div>
  );
}
