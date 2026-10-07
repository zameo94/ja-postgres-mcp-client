export type ChatRole = "user" | "assistant";

export type ProviderId = "ollama" | "external_api";

export interface ChatHistoryMessage {
  role: ChatRole;
  content: string;
}

export interface ToolActivity {
  id: string;
  name: string;
  status: "running" | "done" | "error";
}

export interface UiMessage {
  id: string;
  role: ChatRole;
  content: string;
  tools: ToolActivity[];
}

export interface ChatError {
  code: string;
  message: string;
}
