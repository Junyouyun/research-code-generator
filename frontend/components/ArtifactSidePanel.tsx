"use client";

import { CodeFile } from "../lib/api";

type ArtifactKind = "report" | "code";

type ArtifactSidePanelProps = {
  open: boolean;
  collapsed: boolean;
  kind: ArtifactKind;
  reportContent: string;
  reportError: string;
  files: CodeFile[];
  activePath: string;
  codeError: string;
  artifactUrl: string;
  onOpen: () => void;
  onClose: () => void;
  onToggleCollapse: () => void;
  onSelectKind: (kind: ArtifactKind) => void;
  onSelectFile: (path: string) => void;
};

export function ArtifactSidePanel({
  open,
  collapsed,
  kind,
  reportContent,
  reportError,
  files,
  activePath,
  codeError,
  artifactUrl,
  onOpen,
  onClose,
  onToggleCollapse,
  onSelectKind,
  onSelectFile,
}: ArtifactSidePanelProps) {
  const activeFile = files.find((file) => file.path === activePath) ?? files[0];

  if (!open) {
    return null;
  }

  if (collapsed) {
    return (
      <aside className="artifact-rail">
        <button type="button" onClick={onToggleCollapse}>
          展开
        </button>
        <button type="button" onClick={onClose}>
          关闭
        </button>
      </aside>
    );
  }

  return (
    <aside className="artifact-side-panel">
      <header className="artifact-panel-header">
        <div>
          <strong>{kind === "report" ? "研究报告" : activeFile?.path ?? "生成代码"}</strong>
          <span>{kind === "report" ? "Markdown" : "Code Artifact"}</span>
        </div>
        <div className="artifact-panel-actions">
          <button type="button" onClick={onToggleCollapse}>
            最小化
          </button>
          <button type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </header>

      <div className="artifact-tabs">
        <button className={kind === "report" ? "active" : ""} type="button" onClick={() => onSelectKind("report")}>
          报告
        </button>
        <button className={kind === "code" ? "active" : ""} type="button" onClick={() => onSelectKind("code")}>
          代码
        </button>
        {files.length ? (
          <a href={artifactUrl}>
            下载 zip
          </a>
        ) : null}
      </div>

      {kind === "report" ? (
        <div className="artifact-content">
          {reportContent ? (
            <pre className="markdown-preview side-preview">{reportContent}</pre>
          ) : (
            <p className="muted">{reportError || "报告还在生成中。"}</p>
          )}
        </div>
      ) : (
        <div className="artifact-code-view">
          <div className="side-file-list">
            {files.map((file) => (
              <button
                className={file.path === activeFile?.path ? "active" : ""}
                key={file.path}
                type="button"
                onClick={() => onSelectFile(file.path)}
              >
                {file.path}
              </button>
            ))}
          </div>
          <div className="artifact-content code-content">
            {activeFile ? (
              <pre className="code-preview side-preview">{activeFile.content}</pre>
            ) : (
              <p className="muted">{codeError || "代码文件还在生成中。"}</p>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
