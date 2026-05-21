"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ArtifactSidePanel } from "../../../components/ArtifactSidePanel";
import { ChatComposer } from "../../../components/ChatComposer";
import {
  PaperFileMessage,
  ProjectAnalysisMessage,
  QuestionAnswerMessage,
} from "../../../components/ChatMessages";
import { ConversationSidebar } from "../../../components/ConversationSidebar";
import { ensureProjectConversation, readConversations } from "../../../components/conversations";
import {
  askProjectQuestion,
  CodeFile,
  getArtifactUrl,
  getCodeFiles,
  getMe,
  getProject,
  getReport,
  ProjectStatus as ProjectStatusData,
  QuestionResult,
  User,
} from "../../../lib/api";

type QaMessage = {
  id: string;
  question: string;
  result: QuestionResult | null;
};

type ArtifactKind = "report" | "code";

function isFinalStatus(status?: string) {
  return status === "completed" || status === "failed";
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = params.id;
  const [user, setUser] = useState<User | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [project, setProject] = useState<ProjectStatusData | null>(null);
  const [projectError, setProjectError] = useState("");
  const [reportContent, setReportContent] = useState("");
  const [reportError, setReportError] = useState("");
  const [files, setFiles] = useState<CodeFile[]>([]);
  const [activePath, setActivePath] = useState("");
  const [codeError, setCodeError] = useState("");
  const [qaMessages, setQaMessages] = useState<QaMessage[]>([]);
  const [paperTitle, setPaperTitle] = useState("已上传的论文");
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [artifactCollapsed, setArtifactCollapsed] = useState(false);
  const [artifactKind, setArtifactKind] = useState<ArtifactKind>("report");

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
          router.replace("/");
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
  }, [router]);

  useEffect(() => {
    if (!user) {
      return;
    }

    ensureProjectConversation(projectId, `项目 ${projectId.slice(0, 8)}`);
    const conversation = readConversations().find((item) => item.projectId === projectId);
    if (conversation?.title) {
      setPaperTitle(conversation.title);
    }
  }, [projectId, user]);

  useEffect(() => {
    if (!user) {
      return;
    }

    let active = true;
    let timer: number | undefined;

    async function loadProject() {
      try {
        const data = await getProject(projectId);
        if (!active) {
          return;
        }

        setProject(data);
        setProjectError("");

        if (!isFinalStatus(data.status)) {
          timer = window.setTimeout(loadProject, 2000);
        }
      } catch (error) {
        if (!active) {
          return;
        }

        setProjectError(error instanceof Error ? error.message : "读取项目状态失败。");
        timer = window.setTimeout(loadProject, 3000);
      }
    }

    loadProject();

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [projectId, user]);

  useEffect(() => {
    if (!user) {
      return;
    }

    let active = true;
    let timer: number | undefined;

    async function loadReport() {
      try {
        const data = await getReport(projectId);
        if (!active) {
          return;
        }

        setReportContent(data.content);
        setReportError("");
      } catch (error) {
        if (!active) {
          return;
        }

        if (project?.status === "failed") {
          setReportError("分析失败，报告未生成。");
          return;
        }

        setReportError(error instanceof Error ? error.message : "报告还未生成。");
        if (project?.status !== "completed") {
          timer = window.setTimeout(loadReport, 3000);
        }
      }
    }

    if (!reportContent) {
      loadReport();
    }

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [project?.status, projectId, reportContent, user]);

  useEffect(() => {
    if (!user) {
      return;
    }

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
        setCodeError("");
      } catch (error) {
        if (!active) {
          return;
        }

        if (project?.status === "failed") {
          setCodeError("分析失败，代码文件未生成。");
          return;
        }

        setCodeError(error instanceof Error ? error.message : "代码还未生成。");
        if (project?.status !== "completed") {
          timer = window.setTimeout(loadCodeFiles, 3000);
        }
      }
    }

    if (!files.length) {
      loadCodeFiles();
    }

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [files.length, project?.status, projectId, user]);

  function openReport() {
    setArtifactKind("report");
    setArtifactOpen(true);
    setArtifactCollapsed(false);
  }

  function openCodeFile(path: string) {
    setActivePath(path);
    setArtifactKind("code");
    setArtifactOpen(true);
    setArtifactCollapsed(false);
  }

  async function handleAsk(question: string) {
    if (project?.status !== "completed") {
      throw new Error("论文分析完成后才能提问。");
    }

    const id = `${Date.now()}`;
    setQaMessages((current) => [...current, { id, question, result: null }]);
    const result = await askProjectQuestion(projectId, question);
    setQaMessages((current) => current.map((item) => (item.id === id ? { ...item, result } : item)));
  }

  const shellClassName = [
    "app-shell",
    "with-artifact",
    !artifactOpen ? "artifact-hidden" : "",
    artifactCollapsed ? "artifact-collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");

  function handleLogout() {
    setUser(null);
    router.push("/");
  }

  if (isCheckingAuth || !user) {
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

  return (
    <main className={shellClassName}>
      <ConversationSidebar currentProjectId={projectId} user={user} onLogout={handleLogout} />

      <section className="chat-main">
        <header className="chat-header">
          <div className="chat-header-title">
            <strong>{project?.status === "completed" ? "论文分析完成" : "论文分析中"}</strong>
            <span>{projectId}</span>
          </div>
          {!artifactOpen ? (
            <button className="artifact-header-button" type="button" onClick={openReport} aria-label="打开内容">
              <span className="artifact-header-icon" aria-hidden="true" />
              <span>打开内容</span>
            </button>
          ) : null}
        </header>

        <div className="chat-scroll">
          <PaperFileMessage fileName={paperTitle} />
          <ProjectAnalysisMessage
            project={project}
            projectError={projectError}
            reportReady={Boolean(reportContent)}
            reportError={reportError}
            files={files}
            codeError={codeError}
            artifactUrl={getArtifactUrl(projectId)}
            onOpenReport={openReport}
            onOpenFile={openCodeFile}
          />

          {qaMessages.map((message) => (
            <QuestionAnswerMessage question={message.question} result={message.result} key={message.id} />
          ))}
        </div>

        <ChatComposer
          disabled={project?.status !== "completed"}
          allowAttachments={false}
          placeholder={project?.status === "completed" ? "继续追问论文、实验或代码实现..." : "论文分析完成后可以继续提问"}
          onSend={(text) => handleAsk(text)}
        />
      </section>

      <ArtifactSidePanel
        open={artifactOpen}
        collapsed={artifactCollapsed}
        kind={artifactKind}
        reportContent={reportContent}
        reportError={reportError}
        files={files}
        activePath={activePath}
        codeError={codeError}
        artifactUrl={getArtifactUrl(projectId)}
        onOpen={() => setArtifactOpen(true)}
        onClose={() => setArtifactOpen(false)}
        onToggleCollapse={() => setArtifactCollapsed((current) => !current)}
        onSelectKind={setArtifactKind}
        onSelectFile={setActivePath}
      />
    </main>
  );
}
