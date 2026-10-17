import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Arena, DecisionEvent } from "../../types";

export function useDecisionEvents(
  arenaId: number,
  onState?: (arena: Arena) => void,
) {
  const [events, setEvents] = useState<DecisionEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    let source: EventSource | undefined;
    const controller = new AbortController();
    setEvents([]);
    const start = async () => {
      const history: DecisionEvent[] = [];
      let cursor = 0;
      while (!disposed) {
        const batch = await api<DecisionEvent[]>(
          `/arenas/${arenaId}/timeline?after=${cursor}&limit=1000`,
          { signal: controller.signal },
        );
        history.push(...batch);
        if (batch.length) cursor = batch[batch.length - 1].id;
        if (batch.length < 1000) break;
      }
      if (disposed) return;
      setEvents(history);
      let lastId = cursor;
      source = new EventSource(`/api/arenas/${arenaId}/events?after=${cursor}`);
      source.onopen = () => {
        setConnected(true);
        setError("");
      };
      source.onerror = () => {
        setConnected(false);
        setError("连接恢复中，已记录的执行事件会自动补齐");
      };
      source.addEventListener("decision", (event) => {
        const item = JSON.parse(
          (event as MessageEvent<string>).data,
        ) as DecisionEvent;
        if (item.id <= lastId) return;
        lastId = item.id;
        setEvents((current) => [...current, item]);
      });
      source.addEventListener("state", (event) =>
        onState?.(JSON.parse((event as MessageEvent<string>).data) as Arena),
      );
    };
    start().catch((cause: Error) => {
      if (!disposed && cause.name !== "AbortError") setError(cause.message);
    });
    return () => {
      disposed = true;
      controller.abort();
      source?.close();
      setConnected(false);
    };
  }, [arenaId, onState]);
  return { events, connected, error };
}
