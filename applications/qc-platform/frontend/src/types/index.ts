export interface User {
  username: string;
  token: string;
}

export interface FileInfo {
  name: string;
  size: number;
  category: string;
}

export interface SSEMessage {
  type: string;
  content?: string;
  pair_id?: number;
  total_pairs?: number;
  phase?: string;
  error?: string;
  report_path?: string;
  html_path?: string;
}
