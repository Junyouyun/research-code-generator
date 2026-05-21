"use client";

import { FormEvent, useState } from "react";

import { login, register, User } from "../lib/api";

type AuthPanelProps = {
  onAuthenticated: (user: User) => void;
};

export function AuthPanel({ onAuthenticated }: AuthPanelProps) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const result =
        mode === "register" ? await register(email, password, displayName) : await login(email, password);
      onAuthenticated(result.user);
    } catch (submitError) {
      setError(formatAuthError(submitError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-copy">
        <div className="auth-brand">
          <span className="auth-brand-mark">R</span>
          <div>
            <strong>Research Code</strong>
            <small>Paper intelligence workspace</small>
          </div>
        </div>

        <div className="auth-headline">
          <h1>Upload a paper. Get report, QA index, runnable code.</h1>
          <p>
            把论文变成结构化研究简报、可追问的论文库索引，以及可运行的复现实验代码入口。
          </p>
        </div>

        <div className="auth-value-grid">
          <div>
            <span className="auth-value-index">01</span>
            <strong>Paper to structured research brief</strong>
            <span>自动提取研究问题、方法、实验和可复现要点。</span>
          </div>
          <div>
            <span className="auth-value-index">02</span>
            <strong>Ask across your paper library</strong>
            <span>登录后项目和向量索引按账号隔离，后续可扩展跨论文追问。</span>
          </div>
          <div>
            <span className="auth-value-index">03</span>
            <strong>Generate runnable reproduction code</strong>
            <span>从论文分析结果出发，生成可下载、可运行的代码包。</span>
          </div>
        </div>
      </section>

      <section className="auth-panel" aria-label="账号入口">
        <div className="auth-panel-head">
          <strong>{mode === "register" ? "创建工作空间" : "回到工作空间"}</strong>
          <span>{mode === "register" ? "注册后立即开始上传论文" : "继续查看你的论文项目和生成内容"}</span>
        </div>

        <div className="auth-tabs">
          <button className={mode === "register" ? "active" : ""} type="button" onClick={() => setMode("register")}>
            注册
          </button>
          <button className={mode === "login" ? "active" : ""} type="button" onClick={() => setMode("login")}>
            登录
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="auth-email">邮箱</label>
            <input
              id="auth-email"
              type="email"
              placeholder="name@company.com"
              value={email}
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>

          {mode === "register" ? (
            <div>
              <label htmlFor="auth-name">显示名称</label>
              <input
                id="auth-name"
                placeholder="你的名字或团队名"
                value={displayName}
                autoComplete="name"
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </div>
          ) : null}

          <div>
            <label htmlFor="auth-password">密码</label>
            <input
              id="auth-password"
              type="password"
              placeholder="至少 8 位"
              value={password}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>

          {error ? <p className="error-text">{error}</p> : null}

          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "处理中" : mode === "register" ? "创建账号并进入" : "登录工作台"}
          </button>

          <p className="auth-footnote">账号用于隔离项目、报告、代码文件和向量索引。</p>
        </form>
      </section>
    </main>
  );
}

function formatAuthError(error: unknown) {
  const message = error instanceof Error ? error.message : "认证失败，请稍后再试。";
  if (message.includes("email_already_registered")) {
    return "这个邮箱已经注册，请直接登录。";
  }
  if (message.includes("invalid_email_or_password")) {
    return "邮箱或密码不正确。";
  }
  if (message.includes("password_too_short")) {
    return "密码至少需要 8 位。";
  }
  if (message.includes("invalid_email")) {
    return "请输入有效邮箱。";
  }
  return message;
}
