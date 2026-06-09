import { useState } from "react";
import { Question } from "../types";

interface Props {
  questions: Question[];
  onAnswer: (answer: string) => void;
}

export default function QuestionCard({ questions, onAnswer }: Props) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  return (
    <div style={{ marginTop: 8, padding: 12, background: "#1a2a1a", borderRadius: 6, borderLeft: "3px solid #fbbf24" }}>
      <div style={{ color: "#fbbf24", fontSize: 12, marginBottom: 8 }}>Action Required</div>
      {questions.map((q) => (
        <div key={q.id} style={{ marginBottom: 8 }}>
          <p style={{ color: "#ccc", fontSize: 13, margin: "0 0 6px" }}>{q.text}</p>
          {q.type === "choice" && q.options ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {q.options.map((opt, i) => (
                <button
                  key={i}
                  style={{ padding: "4px 12px", background: "#2a5a3a", border: "none", borderRadius: 4, color: "#fff", cursor: "pointer", fontSize: 12 }}
                  onClick={() => onAnswer(opt)}
                >
                  {String.fromCharCode(65 + i)}: {opt}
                </button>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <input
                style={{ flex: 1, padding: 6, borderRadius: 4, border: "1px solid #555", background: "#111", color: "#fff", fontSize: 12 }}
                value={inputs[q.id] || ""}
                onChange={(e) => setInputs({ ...inputs, [q.id]: e.target.value })}
                placeholder="Type your answer..."
              />
              <button
                style={{ padding: "4px 12px", background: "#3a3a5a", border: "none", borderRadius: 4, color: "#fff", cursor: "pointer", fontSize: 12 }}
                onClick={() => inputs[q.id] && onAnswer(inputs[q.id])}
              >
                Submit
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
