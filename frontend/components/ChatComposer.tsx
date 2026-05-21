"use client";

import { ChangeEvent, KeyboardEvent, useRef, useState } from "react";

type ChatComposerProps = {
  disabled?: boolean;
  placeholder: string;
  sendLabel?: string;
  allowAttachments?: boolean;
  onSend?: (text: string, file: File | null) => Promise<void> | void;
};

function formatFileSize(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }

  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function ChatComposer({
  disabled,
  placeholder,
  sendLabel = "发送",
  allowAttachments = true,
  onSend,
}: ChatComposerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState("");

  const canSubmit = Boolean(text.trim() || selectedFile) && !disabled && !isWorking;

  async function submitMessage() {
    if (!canSubmit || !onSend) {
      return;
    }

    try {
      setIsWorking(true);
      setError("");
      await onSend(text.trim(), selectedFile);
      setText("");
      setSelectedFile(null);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "发送失败，请稍后再试。");
    } finally {
      setIsWorking(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";

    if (!file) {
      return;
    }

    setError("");
    setSelectedFile(file);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  }

  return (
    <div className="composer-wrap">
      <div className={selectedFile ? "chat-composer has-attachment" : "chat-composer"}>
        {selectedFile ? (
          <div className="composer-attachment">
            <div>
              <strong>{selectedFile.name}</strong>
              <span>{formatFileSize(selectedFile.size)}</span>
            </div>
            <button type="button" onClick={() => setSelectedFile(null)} aria-label="移除附件">
              ×
            </button>
          </div>
        ) : null}

        {allowAttachments ? (
          <>
            <button
              className="composer-icon-button"
              type="button"
              disabled={disabled || isWorking}
              onClick={() => inputRef.current?.click()}
              aria-label="选择论文文件"
            >
              +
            </button>
            <input
              ref={inputRef}
              type="file"
              className="hidden-file-input"
              accept=".pdf,.docx,.txt,.md,.markdown,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={handleFileChange}
            />
          </>
        ) : (
          <span className="composer-spacer" />
        )}

        <textarea
          value={text}
          disabled={disabled || isWorking}
          placeholder={placeholder}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
        />

        <button className="composer-send-button" type="button" disabled={!canSubmit} onClick={submitMessage}>
          {isWorking ? "处理中" : sendLabel}
        </button>
      </div>
      {error ? <p className="error-text composer-error">{error}</p> : null}
    </div>
  );
}
