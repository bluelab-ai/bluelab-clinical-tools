import { useRef, useCallback, useEffect } from "react";

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  useEffect(() => {
    const handleBeforeUnload = () => cancel();
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      cancel();
    };
  }, [cancel]);

  const connect = useCallback(
    (
      url: string,
      body: Record<string, unknown>,
      onEvent: (data: Record<string, unknown>) => void,
      onError?: (error: string) => void,
      onDone?: () => void,
    ) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const token = localStorage.getItem("token");

      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok) {
            const errText = await response.text();
            let errMsg = `HTTP ${response.status}`;
            try {
              const errJson = JSON.parse(errText);
              errMsg = errJson.detail || errMsg;
            } catch {
              errMsg = errText || errMsg;
            }
            onError?.(errMsg);
            return;
          }

          const reader = response.body?.getReader();
          if (!reader) { onError?.("无法读取响应流"); return; }

          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let currentEvent = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                try {
                  const parsed = JSON.parse(line.slice(6));
                  parsed._eventType = currentEvent;
                  onEvent(parsed);
                } catch {
                  onEvent({ type: currentEvent, content: line.slice(6) });
                }
              }
            }
          }
          onDone?.();
        })
        .catch((err) => {
          if (err.name !== "AbortError") onError?.(err.message || "连接失败");
        });
    },
    [],
  );

  return { connect, cancel };
}
