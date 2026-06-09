import { ChatMessage as ChatMessageType } from "../types";
import QuestionCard from "./QuestionCard";

interface Props {
  message: ChatMessageType;
  onAnswer: (answer: string) => void;
}

export default function ChatMessage({ message, onAnswer }: Props) {
  const colors: Record<string, string> = {
    user: "#60a5fa",
    claude: "#4ade80",
    system: "#fbbf24",
  };

  return (
    <div style={{ marginBottom: 12, fontFamily: "monospace", fontSize: 13, lineHeight: 1.6 }}>
      <span style={{ color: colors[message.role] }}>
        {message.role === "user" ? "You" : message.role === "claude" ? "Claude" : "System"}
      </span>
      <div style={{ color: "#ccc", whiteSpace: "pre-wrap", marginTop: 4 }}>
        {message.content}
      </div>
      {message.questions && message.questions.length > 0 && (
        <QuestionCard questions={message.questions} onAnswer={onAnswer} />
      )}
    </div>
  );
}
