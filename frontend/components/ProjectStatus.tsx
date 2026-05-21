"use client";

import { useEffect, useState } from "react";

import { getProject, ProjectStatus as ProjectStatusData } from "../lib/api";

type ProjectStatusProps = {
  projectId: string;
  onProjectChange?: (project: ProjectStatusData) => void;
};

function isFinalStatus(status: string) {
  return status === "completed" || status === "failed";
}

function formatDuration(durationMs?: number | null) {
  if (durationMs === undefined || durationMs === null) {
    return "";
  }

  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }

  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function ProjectStatus({ projectId, onProjectChange }: ProjectStatusProps) {
  const [project, setProject] = useState<ProjectStatusData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function loadProject() {
      try {
        const data = await getProject(projectId);
        if (!active) {
          return;
        }

        setProject(data);
        onProjectChange?.(data);
        setError("");

        if (!isFinalStatus(data.status)) {
          timer = window.setTimeout(loadProject, 2000);
        }
      } catch (loadError) {
        if (!active) {
          return;
        }

        setError(loadError instanceof Error ? loadError.message : "读取项目状态失败");
        timer = window.setTimeout(loadProject, 3000);
      }
    }

    if (projectId) {
      loadProject();
    }

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [onProjectChange, projectId]);

  return (
    <section className="status-panel">
      <div className="section-title">
        <h2>处理状态</h2>
        <span>{project?.status ?? "loading"}</span>
      </div>
      <p className="muted breakable">{projectId}</p>
      <div className="progress-track">
        <div className="progress-bar" style={{ width: `${project?.progress ?? 0}%` }} />
      </div>
      <p>{project?.current_step ?? "正在读取状态..."}</p>
      {project?.error_message ? <p className="error-text">{project.error_message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}

      {project?.events?.length ? (
        <div className="progress-log">
          {project.events.map((event, index) => (
            <div className={`progress-log-item ${event.level}`} key={`${event.created_at}-${index}`}>
              <span>{event.message}</span>
              {event.duration_ms !== undefined && event.duration_ms !== null ? (
                <strong>{formatDuration(event.duration_ms)}</strong>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
