import { useCallback, useRef } from "react";

export function useSSE() {
  const readerRef = useRef<ReadableStreamDefaultReader | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(
    (url: string, onEvent: (type: string, data: any) => void, onDone: () => void, body?: any) => {
      abortRef.current = new AbortController();

      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("token")}`,
        },
        body: body ? JSON.stringify(body) : "{}",
        signal: abortRef.current.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            onEvent("error", { message: `HTTP ${response.status}` });
            onDone();
            return;
          }
          const reader = response.body.getReader();
          readerRef.current = reader;
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
                  const data = JSON.parse(line.slice(6));
                  onEvent(currentEvent, data);
                  if (currentEvent === "done") {
                    onDone();
                    return;
                  }
                } catch {}
              }
            }
          }
          onDone();
        })
        .catch((err) => {
          if (err.name !== "AbortError") {
            onEvent("error", { message: err.message });
            onDone();
          }
        });
    },
    []
  );

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    readerRef.current?.cancel();
  }, []);

  return { connect, disconnect };
}
