import { useState, FormEvent } from "react";

interface Props {
  onSend: (message: string) => void;
  onStartDMP: () => void;
  disabled: boolean;
  canGenerate: boolean;
}

export default function ChatInput({ onSend, onStartDMP, disabled, canGenerate }: Props) {
  const [text, setText] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid #333" }}>
      <input
        style={{ flex: 1, padding: 10, borderRadius: 6, border: "1px solid #555", background: "#111", color: "#fff", fontSize: 13 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? "Claude is working..." : "Type a message..."}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled} style={{ padding: "8px 16px", cursor: disabled ? "not-allowed" : "pointer" }}>
        Send
      </button>
      <button
        type="button"
        disabled={disabled || !canGenerate}
        onClick={onStartDMP}
        style={{ padding: "8px 16px", background: canGenerate ? "#2a5a3a" : "#333", cursor: canGenerate && !disabled ? "pointer" : "not-allowed" }}
      >
        Generate DMP
      </button>
    </form>
  );
}
