"use client";

import { useEffect, useState } from "react";

import { getReport } from "../lib/api";

type ReportViewerProps = {
  projectId: string;
  projectStatus?: string;
};

export function ReportViewer({ projectId, projectStatus }: ReportViewerProps) {
  const [content, setContent] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function loadReport() {
      try {
        const data = await getReport(projectId);
        if (!active) {
          return;
        }

        setContent(data.content);
        setError("");
      } catch (loadError) {
        if (!active) {
          return;
        }

        if (projectStatus === "failed") {
          setError("任务处理失败，无法生成报告。");
          return;
        }

        setError(loadError instanceof Error ? loadError.message : "报告暂未生成。");
        if (projectStatus !== "completed") {
          timer = window.setTimeout(loadReport, 3000);
        }
      }
    }

    if (projectId && !content) {
      loadReport();
    }

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [content, projectId, projectStatus]);

  return (
    <section className="chat-thread">
      <div className="message-row assistant">
        <div className="avatar">AI</div>
        <div className="message-bubble">
          <p className="message-label">研究报告</p>
          {content ? (
            <pre className="markdown-preview">{content}</pre>
          ) : (
            <p className="muted">{error || "等待报告生成..."}</p>
          )}
        </div>
      </div>
    </section>
  );
}
