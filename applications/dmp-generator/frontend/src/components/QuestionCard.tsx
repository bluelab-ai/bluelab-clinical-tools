import { useState } from "react";
import { Question } from "../types";
import { AlertTriangle, Send } from "lucide-react";

interface Props {
  questions: Question[];
  onAnswer: (answer: string) => void;
}

export default function QuestionCard({ questions, onAnswer }: Props) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  return (
    <div className="mt-3 p-4 bg-amber-50/50 rounded-xl border-l-4 border-amber-400">
      <div className="flex items-center gap-2 text-amber-700 text-xs font-semibold font-mono uppercase tracking-wider mb-3">
        <AlertTriangle size={14} />
        Action Required
      </div>
      {questions.map((q) => (
        <div key={q.id} className="mb-3 last:mb-0">
          <p className="text-slate-700 text-sm font-medium mb-2">{q.text}</p>
          {q.type === "choice" && q.options ? (
            <div className="flex gap-2 flex-wrap">
              {q.options.map((opt, i) => (
                <button
                  key={i}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold cursor-pointer active:scale-95 transition-all"
                  onClick={() => onAnswer(opt)}
                >
                  {String.fromCharCode(65 + i)}: {opt}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                className="flex-1 bg-white border border-slate-200 focus:border-blue-500 rounded-lg px-3 py-2 text-sm text-slate-800 outline-none focus:ring-2 focus:ring-blue-100 transition-all"
                value={inputs[q.id] || ""}
                onChange={(e) => setInputs({ ...inputs, [q.id]: e.target.value })}
                placeholder="Type your answer..."
              />
              <button
                className="px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold cursor-pointer active:scale-95 transition-all flex items-center gap-1.5"
                onClick={() => inputs[q.id] && onAnswer(inputs[q.id])}
              >
                <Send size={12} />
                Submit
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
