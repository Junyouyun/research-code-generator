"use client";

import { useMemo } from "react";

import { CodeFile, ProjectEvent, ProjectStatus as ProjectStatusData, QuestionResult } from "../lib/api";

type ProjectStatusMessageProps = {
  project: ProjectStatusData | null;
  error: string;
};

type PaperFileMessageProps = {
  fileName: string;
  note?: string;
};

type ReportMessageProps = {
  ready: boolean;
  error: string;
  onOpen: () => void;
};

type ProjectAnalysisMessageProps = {
  project: ProjectStatusData | null;
  projectError: string;
  reportReady: boolean;
  reportError: string;
  files: CodeFile[];
  codeError: string;
  artifactUrl: string;
  onOpenReport: () => void;
  onOpenFile: (path: string) => void;
};

type QuestionAnswerMessageProps = {
  question: string;
  result: QuestionResult | null;
};

type CodeMessageProps = {
  files: CodeFile[];
  error: string;
  artifactUrl: string;
  onOpenFile: (path: string) => void;
};

function isThoughtEvent(event: ProjectEvent) {
  return event.details?.kind === "thought";
}

function isCompleted(status?: string) {
  return status === "completed";
}

function isFailed(status?: string) {
  return status === "failed";
}

function statusText(status?: string) {
  if (status === "completed") {
    return "分析完成";
  }
  if (status === "failed") {
    return "分析失败";
  }
  if (!status) {
    return "读取状态";
  }
  return "正在分析";
}

function eventTitle(event: ProjectEvent) {
  return event.details?.title || event.message || event.step;
}

function eventSummary(event: ProjectEvent) {
  return event.details?.summary || "";
}

function visibleAnalysisEvents(events: ProjectEvent[] = []) {
  return events.filter((event) => eventTitle(event)).slice(-7);
}

export function EmptyChat() {
  const prompts = ["研究简报", "论文内问答", "跨论文扩展", "复现代码包"];

  return (
    <div className="empty-chat">
      <div className="empty-mark">R</div>
      <h1>把论文转成可追问、可复现的研究工作台</h1>
      <p>选择论文文件后点击发送，系统会解析结构、建立索引、生成报告，并规划可运行代码包。</p>
      <div className="prompt-list">
        {prompts.map((prompt) => (
          <span key={prompt}>{prompt}</span>
        ))}
      </div>
    </div>
  );
}

export function PaperFileMessage({ fileName, note = "论文已发送" }: PaperFileMessageProps) {
  return (
    <div className="message-row user">
      <div className="message-bubble file-message">
        <p className="message-label subtle-label">{note}</p>
        <div className="artifact-chip user-chip">
          <span className="file-type">PDF</span>
          <div>
            <strong>{fileName}</strong>
            <small>等待分析任务接收</small>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ProjectAnalysisMessage({
  project,
  projectError,
  reportReady,
  reportError,
  files,
  codeError,
  artifactUrl,
  onOpenReport,
  onOpenFile,
}: ProjectAnalysisMessageProps) {
  const events = useMemo(() => visibleAnalysisEvents(project?.events), [project?.events]);
  const latestThought = useMemo(
    () => project?.events?.filter(isThoughtEvent).at(-1) ?? events.at(-1) ?? null,
    [events, project?.events],
  );
  const title = latestThought ? eventTitle(latestThought) : project?.current_step || statusText(project?.status);
  const summary =
    latestThought && eventSummary(latestThought)
      ? eventSummary(latestThought)
      : isCompleted(project?.status)
        ? "研究报告、问答索引和代码文件已经准备好。"
        : "我正在解析论文结构、提取关键信息，并整理可复现的代码实现。";
  const firstFilePath = files[0]?.path || "";

  return (
    <div className="message-row assistant">
      <div className="message-bubble analysis-message unified-analysis">
        {isCompleted(project?.status) ? (
          <>
            <strong className="assistant-line-title">已经总结完了</strong>
            <p className="analysis-summary">研究报告、论文问答索引和代码文件已经生成。你可以点下面的内容，在右侧打开查看。</p>
          </>
        ) : (
          <>
            <div className="analysis-head">
              <div className="analysis-pulse" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div>
                <strong>{statusText(project?.status)}</strong>
                <p>{title}</p>
              </div>
              <em>{project?.progress ?? 0}%</em>
            </div>
            <div className="progress-track slim">
              <div className="progress-bar" style={{ width: `${project?.progress ?? 0}%` }} />
            </div>
            <p className="analysis-summary">{summary}</p>
          </>
        )}

        {events.length && !isCompleted(project?.status) ? (
          <div className="analysis-stream" aria-label="分析过程">
            {events.map((event, index) => (
              <div className={index === events.length - 1 ? "analysis-stream-line active" : "analysis-stream-line"} key={`${event.step}-${event.created_at}-${index}`}>
                <span>{eventTitle(event)}</span>
                {eventSummary(event) ? <small>{eventSummary(event)}</small> : null}
              </div>
            ))}
          </div>
        ) : null}

        {isFailed(project?.status) && project?.error_message ? <p className="error-text">{project.error_message}</p> : null}
        {projectError ? <p className="error-text">{projectError}</p> : null}

        {isCompleted(project?.status) || reportReady || files.length ? (
          <div className="artifact-strip">
            {reportReady ? (
              <button className="artifact-chip" type="button" onClick={onOpenReport}>
                <span className="file-type">MD</span>
                <div>
                  <strong>研究报告.md</strong>
                  <small>结构化总结、方法拆解和复现要点</small>
                </div>
              </button>
            ) : reportError ? (
              <p className="muted">{reportError}</p>
            ) : null}

            {files.length ? (
              <button className="artifact-chip" type="button" onClick={() => onOpenFile(firstFilePath)}>
                <span className="file-type">CODE</span>
                <div>
                  <strong>代码文件</strong>
                  <small>{files.length} 个文件，点击在右侧预览</small>
                </div>
              </button>
            ) : codeError ? (
              <p className="muted">{codeError}</p>
            ) : null}

            {files.length ? (
              <a className="artifact-chip artifact-download" href={artifactUrl}>
                <span className="file-type">ZIP</span>
                <div>
                  <strong>下载 zip</strong>
                  <small>完整复现代码包</small>
                </div>
              </a>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ProjectStatusMessage({ project, error }: ProjectStatusMessageProps) {
  const latestThought = useMemo(
    () => project?.events?.filter(isThoughtEvent).at(-1) ?? null,
    [project?.events],
  );
  const title = latestThought?.details?.title ?? project?.current_step ?? statusText(project?.status);
  const summary =
    latestThought?.details?.summary ??
    (isCompleted(project?.status)
      ? "报告和代码已经准备好，可以在右侧查看生成内容。"
      : "我正在阅读论文、整理结构并生成可运行代码。");

  if (isCompleted(project?.status) && !error) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble compact-message">
          <strong>分析完成</strong>
          <p>研究报告、问答索引和代码文件已经准备好。点击下面的文件卡片可在右侧查看内容。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="message-row assistant">
      <div className="message-bubble analysis-message">
        <div className="analysis-head">
          <div className="analysis-pulse" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <strong>{statusText(project?.status)}</strong>
            <p>{title}</p>
          </div>
          <em>{project?.progress ?? 0}%</em>
        </div>
        <div className="progress-track slim">
          <div className="progress-bar" style={{ width: `${project?.progress ?? 0}%` }} />
        </div>
        <p className="analysis-summary">{summary}</p>
        {isFailed(project?.status) && project?.error_message ? <p className="error-text">{project.error_message}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </div>
    </div>
  );
}

export function ReportMessage({ ready, error, onOpen }: ReportMessageProps) {
  if (!ready && !error) {
    return null;
  }

  return (
    <div className="message-row assistant">
      <div className="message-bubble compact-message">
        <p className="message-label">生成内容</p>
        {ready ? (
          <button className="artifact-chip" type="button" onClick={onOpen}>
            <span className="file-type">MD</span>
            <div>
              <strong>研究报告.md</strong>
              <small>结构化总结、方法拆解和复现要点</small>
            </div>
          </button>
        ) : (
          <p className="muted">{error}</p>
        )}
      </div>
    </div>
  );
}

export function QuestionAnswerMessage({ question, result }: QuestionAnswerMessageProps) {
  if (!question && !result) {
    return null;
  }

  return (
    <>
      {question ? (
        <div className="message-row user">
          <div className="message-bubble">
            <p className="answer-text">{question}</p>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="message-row assistant">
          <div className="message-bubble">
            <div className="answer-meta">置信度：{result.confidence}</div>
            <p className="answer-text">{result.answer}</p>
            {result.used_chunks.length ? (
              <div className="chunk-tags">
                {result.used_chunks.map((chunkId) => (
                  <span key={chunkId}>{chunkId}</span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="message-row assistant">
          <div className="message-bubble compact-message">
            <div className="analysis-pulse small" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <p>正在检索论文内容...</p>
          </div>
        </div>
      )}
    </>
  );
}

export function CodeMessage({ files, error, artifactUrl, onOpenFile }: CodeMessageProps) {
  if (!files.length && !error) {
    return null;
  }

  return (
    <div className="message-row assistant">
      <div className="message-bubble compact-message">
        <div className="message-title-row">
          <p className="message-label">生成文件</p>
          {files.length ? (
            <a className="secondary-button" href={artifactUrl}>
              下载 zip
            </a>
          ) : null}
        </div>

        {files.length ? (
          <div className="artifact-grid">
            {files.slice(0, 8).map((file) => (
              <button className="artifact-chip" key={file.path} type="button" onClick={() => onOpenFile(file.path)}>
                <span className="file-type">PY</span>
                <div>
                  <strong>{file.path}</strong>
                  <small>点击打开右侧代码预览</small>
                </div>
              </button>
            ))}
            {files.length > 8 ? <span className="muted">还有 {files.length - 8} 个文件可在右侧查看</span> : null}
          </div>
        ) : (
          <p className="muted">{error}</p>
        )}
      </div>
    </div>
  );
}
