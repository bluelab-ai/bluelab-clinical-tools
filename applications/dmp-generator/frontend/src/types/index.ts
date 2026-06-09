export interface User {
  username: string;
  workspace: string;
  token: string;
}

export interface LogEntry {
  [key: string]: string;
}

export interface LogData {
  entries: LogEntry[];
  latest: LogEntry | null;
}

export interface FileInfo {
  name: string;
  size: number;
  modified_at: string;
  category: "log" | "protocol" | "dmp";
}

export interface SSEMessage {
  type: string;
  content?: string;
  questions?: Question[];
  message?: string;
  output_file?: string;
  report?: string;
}

export interface Question {
  id: string;
  text: string;
  type: "choice" | "input";
  options?: string[];
}

export interface ChatMessage {
  role: "user" | "claude" | "system";
  content: string;
  questions?: Question[];
}
