export interface User {
  username: string;
  token: string;
}

export interface Project {
  id: number;
  name: string;
  sap_filename: string;
  crf_filename: string | null;
  status: "pending" | "running" | "completed" | "failed";
  phase: "pending" | "phase1" | "catalog" | "prompts" | "phase2" | "review" | "completed";
  tables_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface ManualProject {
  name: string;
  categories?: string[];
  unit?: string;
}

export interface CatalogItem {
  category: string;
  index: number;
  name: string;
  data_source?: "auto" | "manual" | "none" | "title" | "crf" | "fill";
  locked?: boolean;
  projects?: ManualProject[];
}

export interface TablesCatalog {
  total: number;
  tables: CatalogItem[];
}

export interface PromptCommon {
  extract_rules: string;
  output_format: string;
  notes: string;
}

export interface PromptItem {
  name: string;
  category: string;
  instruction: string;
  enabled: boolean;
}

export interface PromptsCatalog {
  common: PromptCommon;
  items: PromptItem[];
}
