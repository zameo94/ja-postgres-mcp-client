"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { streamChat } from "@/lib/chat-stream";
import {
  ApiKeyMissingError,
  ApiKeyUnavailableError,
  ApiKeyUnreadableError,
} from "@/lib/provider-settings";
import type { ChatError, ChatHistoryMessage, ProviderConfig, UiMessage } from "@/lib/types";

export interface UseChatResult {
  messages: UiMessage[];
  isStreaming: boolean;
  error: ChatError | null;
  send: (text: string) => Promise<boolean>;
  stop: () => void;
}

let idCounter = 0;
function newId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

function mapApiKeyError(error: unknown): ChatError {
  if (error instanceof ApiKeyMissingError) {
    return { code: "missing_api_key", message: "No API key is configured." };
  }
  if (error instanceof ApiKeyUnavailableError) {
    return { code: "secure_storage_unavailable", message: "Secure storage is unavailable." };
  }
  if (error instanceof ApiKeyUnreadableError) {
    return { code: "api_key_unreadable", message: "The saved API key could not be read." };
  }
  return { code: "internal_error", message: "An unexpected error occurred." };
}

export function useChat(
  provider: ProviderConfig,
  resolveApiKey: () => Promise<string>,
): UseChatResult {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);

  useEffect(() => () => abortRef.current?.abort(), []);

  const startTurn = useCallback(
    (question: string, request: ProviderConfig): void => {
      const history: ChatHistoryMessage[] = messages.map((message) => ({
        role: message.role,
        content: message.content,
      }));
      const assistantId = newId("assistant");

      setMessages((current) => [
        ...current,
        { id: newId("user"), role: "user", content: question, tools: [] },
        { id: assistantId, role: "assistant", content: "", tools: [] },
      ]);
      setError(null);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const updateAssistant = (update: (message: UiMessage) => UiMessage): void => {
        setMessages((current) =>
          current.map((message) => (message.id === assistantId ? update(message) : message)),
        );
      };

      void streamChat(
        { messages: [...history, { role: "user", content: question }], provider: request },
        {
          onToken: (token) =>
            updateAssistant((message) => ({ ...message, content: message.content + token })),
          onToolCall: (call) =>
            updateAssistant((message) => ({
              ...message,
              tools: [
                ...message.tools.filter((tool) => tool.id !== call.id),
                { id: call.id, name: call.name, status: "running" },
              ],
            })),
          onToolResult: (result) =>
            updateAssistant((message) => ({
              ...message,
              tools: message.tools.map((tool) =>
                tool.id === result.id
                  ? { ...tool, status: result.isError ? "error" : "done" }
                  : tool,
              ),
            })),
          onError: (streamError) => {
            setError(streamError);
            updateAssistant((message) => ({
              ...message,
              tools: message.tools.map((tool) =>
                tool.status === "running" ? { ...tool, status: "error" } : tool,
              ),
            }));
          },
        },
        controller.signal,
      ).finally(() => {
        sendingRef.current = false;
        setIsStreaming(false);
        abortRef.current = null;
        setMessages((current) => {
          const last = current[current.length - 1];
          if (
            last &&
            last.id === assistantId &&
            last.content === "" &&
            last.tools.length === 0
          ) {
            return current.slice(0, -1);
          }
          return current;
        });
      });
    },
    [messages],
  );

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const question = text.trim();
      if (!question || sendingRef.current) return false;
      sendingRef.current = true;
      try {
        let request = provider;
        if (provider.provider === "external_api") {
          request = { ...provider, api_key: await resolveApiKey() };
        }
        startTurn(question, request);
        return true;
      } catch (cause) {
        sendingRef.current = false;
        setError(mapApiKeyError(cause));
        return false;
      }
    },
    [provider, resolveApiKey, startTurn],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, isStreaming, error, send, stop };
}
