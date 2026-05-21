"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthPanel } from "../components/AuthPanel";
import { ChatComposer } from "../components/ChatComposer";
import { EmptyChat, PaperFileMessage } from "../components/ChatMessages";
import { ConversationSidebar } from "../components/ConversationSidebar";
import { saveProjectConversation } from "../components/conversations";
import { getMe, uploadPaper, User } from "../lib/api";

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [sentFileName, setSentFileName] = useState("");

  useEffect(() => {
    let active = true;

    getMe()
      .then((result) => {
        if (active) {
          setUser(result.user);
        }
      })
      .catch(() => {
        if (active) {
          setUser(null);
        }
      })
      .finally(() => {
        if (active) {
          setIsCheckingAuth(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  async function handleSend(text: string, file: File | null) {
    if (!file) {
      throw new Error("请先选择一篇论文文件。");
    }

    setSentFileName(file.name);
    const result = await uploadPaper(file);
    saveProjectConversation(result.project_id, file.name);
    router.push(`/projects/${result.project_id}`);
  }

  function handleLogout() {
    setUser(null);
    setSentFileName("");
  }

  if (isCheckingAuth) {
    return (
      <main className="auth-loading">
        <div className="analysis-pulse" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </main>
    );
  }

  if (!user) {
    return <AuthPanel onAuthenticated={setUser} />;
  }

  return (
    <main className="app-shell">
      <ConversationSidebar user={user} onLogout={handleLogout} />

      <section className="chat-main">
        <header className="chat-header">
          <strong>Research Code</strong>
          <span>上传论文，生成报告、问答索引和可运行代码</span>
        </header>

        <div className="chat-scroll">
          {sentFileName ? <PaperFileMessage fileName={sentFileName} note="正在发送论文" /> : <EmptyChat />}
        </div>

        <ChatComposer
          placeholder="选择论文文件，也可以补充你希望重点复现的内容..."
          sendLabel="发送"
          onSend={handleSend}
        />
      </section>
    </main>
  );
}
