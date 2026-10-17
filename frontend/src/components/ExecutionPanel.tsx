import { useEffect } from "react";
import { Clock3, RefreshCw } from "lucide-react";
import { useResource } from "../api";
import type { ExecutionJob } from "../types";
import { Button, Empty, ErrorState, Loading } from "./ui";

const STATES = {
  queued: "等待执行",
  running: "执行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "执行失败",
};

export function ExecutionPanel({ arenaId }: { arenaId: number }) {
  const { data, error, reload } = useResource<ExecutionJob[]>(
    `/arenas/${arenaId}/tasks`,
  );
  useEffect(() => {
    if (!data?.some((job) => job.state === "running" || job.state === "queued"))
      return;
    const timer = setInterval(reload, 1500);
    return () => clearInterval(timer);
  }, [data, reload]);
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <section className="panel execution-panel">
      <div className="panel-heading">
        <h2>执行记录</h2>
        <Button variant="ghost" onClick={reload}>
          <RefreshCw size={14} />
          刷新
        </Button>
      </div>
      {!data.length ? (
        <Empty title="暂无后台任务" />
      ) : (
        data.map((job) => (
          <article key={job.id} className="execution-job">
            <div className="section-heading small">
              <h3>任务 {String(job.id).padStart(3, "0")}</h3>
              <span
                className={job.state === "failed" ? "negative" : "positive"}
              >
                {STATES[job.state]}
              </span>
            </div>
            <div className="execution-facts">
              <span>
                <Clock3 size={14} />
                {new Date(job.created_at).toLocaleString("zh-CN")}
              </span>
              <span>执行 {job.attempts} 次</span>
              <span>接管版本 {job.lease_version}</span>
            </div>
            {job.error && (
              <p className={job.state === "failed" ? "negative" : ""}>
                {job.error}
              </p>
            )}
            {job.owner && (
              <details className="context-data">
                <summary>执行节点</summary>
                <code>{job.owner}</code>
              </details>
            )}
          </article>
        ))
      )}
    </section>
  );
}
