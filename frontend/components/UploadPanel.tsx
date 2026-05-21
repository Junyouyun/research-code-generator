"use client";

import { useRouter } from "next/navigation";
import { ChangeEvent, useState } from "react";

import { uploadPaper } from "../lib/api";

export function UploadPanel() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setError("");
    setFile(event.target.files?.[0] ?? null);
  }

  async function handleUpload() {
    if (!file) {
      setError("请先选择一个文档。");
      return;
    }

    try {
      setIsUploading(true);
      setError("");
      const result = await uploadPaper(file);
      router.push(`/projects/${result.project_id}`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "上传失败。");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <section className="home-chat">
      <div className="home-hero">
        <div className="brand-block centered">
          <span className="brand-mark">R</span>
          <div>
            <p className="brand-title">Research Code</p>
            <p className="brand-subtitle">上传文档，生成报告、问答和代码</p>
          </div>
        </div>
        <h1>今天想分析哪份研究文档？</h1>
        <p className="muted">支持 PDF、Word、Markdown 和纯文本。处理完成后可以继续围绕文档提问。</p>
      </div>

      <div className="upload-composer">
        <label className="file-picker">
          <span>{file ? file.name : "选择文档"}</span>
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleFileChange}
          />
        </label>

        <button className="primary-button send-button" type="button" disabled={isUploading} onClick={handleUpload}>
          {isUploading ? "上传中..." : "开始"}
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </section>
  );
}
