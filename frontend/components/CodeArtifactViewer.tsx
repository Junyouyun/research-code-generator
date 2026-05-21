"use client";

import { useEffect, useMemo, useState } from "react";

import { CodeFile, getArtifactUrl, getCodeFiles } from "../lib/api";

type CodeArtifactViewerProps = {
  projectId: string;
  projectStatus?: string;
};

export function CodeArtifactViewer({ projectId, projectStatus }: CodeArtifactViewerProps) {
  const [files, setFiles] = useState<CodeFile[]>([]);
  const [activePath, setActivePath] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function loadCodeFiles() {
      try {
        const data = await getCodeFiles(projectId);
        if (!active) {
          return;
        }

        setFiles(data.files);
        setActivePath((current) => current || data.files[0]?.path || "");
        setError("");
      } catch (loadError) {
        if (!active) {
          return;
        }

        if (projectStatus === "failed") {
          setError("任务处理失败，无法生成代码。");
          return;
        }

        setError(loadError instanceof Error ? loadError.message : "代码暂未生成。");
        if (projectStatus !== "completed") {
          timer = window.setTimeout(loadCodeFiles, 3000);
        }
      }
    }

    if (projectId && files.length === 0) {
      loadCodeFiles();
    }

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [files.length, projectId, projectStatus]);

  const activeFile = useMemo(
    () => files.find((file) => file.path === activePath) ?? files[0],
    [activePath, files],
  );

  return (
    <section className="artifact-panel">
      <div className="section-title">
        <h2>生成代码</h2>
        {files.length ? (
          <a className="secondary-button" href={getArtifactUrl(projectId)}>
            下载 zip
          </a>
        ) : null}
      </div>

      {files.length ? (
        <div className="code-layout">
          <div className="file-list">
            {files.map((file) => (
              <button
                className={file.path === activeFile?.path ? "file-tab active" : "file-tab"}
                key={file.path}
                type="button"
                onClick={() => setActivePath(file.path)}
              >
                {file.path}
              </button>
            ))}
          </div>
          <pre className="code-preview">{activeFile?.content}</pre>
        </div>
      ) : (
        <p className="muted">{error || "等待代码生成..."}</p>
      )}
    </section>
  );
}
