"use client";

import { useState } from "react";

import { askProjectQuestion, QuestionResult } from "../lib/api";

type QuestionPanelProps = {
  projectId: string;
  projectStatus?: string;
};

export function QuestionPanel({ projectId, projectStatus }: QuestionPanelProps) {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [result, setResult] = useState<QuestionResult | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState("");
  const canAsk = projectStatus === "completed";

  async function handleAsk() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setError("请输入问题。");
      return;
    }
    if (!canAsk) {
      setError("文档处理完成后可以提问。");
      return;
    }

    try {
      setIsAsking(true);
      setError("");
      setSubmittedQuestion(trimmedQuestion);
      const data = await askProjectQuestion(projectId, trimmedQuestion);
      setResult(data);
      setQuestion("");
    } catch (askError) {
      setError(askError instanceof Error ? askError.message : "提问失败。");
    } finally {
      setIsAsking(false);
    }
  }

  return (
    <section className="chat-composer-panel">
      {submittedQuestion ? (
        <div className="message-row user">
          <div className="message-bubble">
            <p className="answer-text">{submittedQuestion}</p>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="message-row assistant">
          <div className="avatar">AI</div>
          <div className="message-bubble">
            <div className="answer-meta">confidence: {result.confidence}</div>
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
      ) : null}

      <div className="question-composer">
        <textarea
          className="question-input"
          value={question}
          placeholder={canAsk ? "继续追问这份文档..." : "文档处理完成后可以提问"}
          disabled={!canAsk || isAsking}
          onChange={(event) => setQuestion(event.target.value)}
        />

        <button className="primary-button send-button" type="button" disabled={!canAsk || isAsking} onClick={handleAsk}>
          {isAsking ? "发送中..." : "发送"}
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </section>
  );
}
