import { useCallback, useEffect, useState } from "react";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const error = (await response.json()) as {
      detail?: string | { msg: string }[];
    };
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : error.detail?.map((item) => item.msg).join("；") || "请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => setData(null), [path]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<T>(path, { signal: controller.signal })
      .then(setData)
      .catch((cause: Error) => {
        if (cause.name !== "AbortError") setError(cause.message);
      });
    return () => controller.abort();
  }, [path, version]);
  return { data, setData, error, reload };
}

export const money = (value: number, compact = false): string => {
  const amount = value / 100;
  if (compact && Math.abs(amount) >= 10000)
    return `${(amount / 10000).toFixed(1)}万`;
  return amount.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
};
export const signedMoney = (value: number): string =>
  `${value >= 0 ? "+" : "−"}¥${money(Math.abs(value))}`;
export const count = (value: number): string => value.toLocaleString("zh-CN");
export const date = (value: string): string =>
  new Date(value).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
