import { Sparkles, Play } from "lucide-react";

interface Props {
  onStartDMP: () => void;
  onContinueDMP: () => void;
  disabled: boolean;
  canGenerate: boolean;
  hasSession: boolean;
}

export default function ChatInput({ onStartDMP, onContinueDMP, disabled, canGenerate, hasSession }: Props) {
  return (
    <div className="flex justify-center gap-3 p-4 bg-white dark:bg-slate-900 border-t border-slate-200/80 dark:border-slate-800">
      <button
        type="button"
        disabled={disabled || !canGenerate}
        className={`px-6 py-3 font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer disabled:cursor-not-allowed flex items-center gap-2 text-base ${
          canGenerate && !disabled
            ? "bg-slate-900 dark:bg-slate-100 hover:bg-slate-800 dark:hover:bg-white text-white dark:text-slate-900"
            : "bg-slate-200 dark:bg-slate-800 text-slate-400 dark:text-slate-600"
        }`}
        onClick={onStartDMP}
      >
        <Sparkles size={16} />
        Generate DMP
      </button>
      <button
        type="button"
        disabled={disabled || !hasSession}
        className={`px-6 py-3 font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer disabled:cursor-not-allowed flex items-center gap-2 text-base ${
          hasSession && !disabled
            ? "bg-blue-600 hover:bg-blue-700 text-white"
            : "bg-slate-200 dark:bg-slate-800 text-slate-400 dark:text-slate-600"
        }`}
        onClick={onContinueDMP}
      >
        <Play size={16} />
        Continue
      </button>
    </div>
  );
}
