"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ConversationSidebar } from "../../../components/ConversationSidebar";
import {
  deleteUserMemory,
  getMe,
  getUserMemories,
  updateUserMemory,
  User,
  UserMemory,
} from "../../../lib/api";

const MEMORY_TYPES = [
  { value: "", label: "全部" },
  { value: "user_preference", label: "偏好" },
  { value: "research_interest", label: "研究方向" },
  { value: "coding_preference", label: "代码习惯" },
  { value: "workflow_preference", label: "工作流" },
  { value: "domain_knowledge", label: "领域知识" },
];

const TYPE_LABELS: Record<string, string> = {
  user_preference: "偏好",
  research_interest: "研究方向",
  coding_preference: "代码习惯",
  workflow_preference: "工作流",
  domain_knowledge: "领域知识",
};

export default function MemorySettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [memories, setMemories] = useState<UserMemory[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [draftType, setDraftType] = useState("user_preference");
  const [draftImportance, setDraftImportance] = useState(0.5);
  const [draftConfidence, setDraftConfidence] = useState(0.7);
  const [busyId, setBusyId] = useState("");

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

    loadMemories(selectedType);
  }, [selectedType, user]);

  async function loadMemories(memoryType = selectedType) {
    setIsLoading(true);
    setError("");
    try {
      const result = await getUserMemories(memoryType || undefined);
      setMemories(result.memories);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取长期记忆失败。");
    } finally {
      setIsLoading(false);
    }
  }

  function startEdit(memory: UserMemory) {
    setEditingId(memory.memory_id);
    setDraftContent(memory.content);
    setDraftType(memory.memory_type);
    setDraftImportance(memory.importance);
    setDraftConfidence(memory.confidence);
  }

  function cancelEdit() {
    setEditingId("");
    setDraftContent("");
  }

  async function saveEdit(memoryId: string) {
    if (!draftContent.trim()) {
      setError("记忆内容不能为空。");
      return;
    }

    setBusyId(memoryId);
    setError("");
    try {
      const updated = await updateUserMemory(memoryId, {
        content: draftContent.trim(),
        memory_type: draftType,
        importance: draftImportance,
        confidence: draftConfidence,
      });
      setMemories((current) => current.map((memory) => (memory.memory_id === memoryId ? updated : memory)));
      cancelEdit();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存长期记忆失败。");
    } finally {
      setBusyId("");
    }
  }

  async function archiveMemory(memoryId: string) {
    setBusyId(memoryId);
    setError("");
    try {
      await deleteUserMemory(memoryId);
      setMemories((current) => current.filter((memory) => memory.memory_id !== memoryId));
    } catch (archiveError) {
      setError(archiveError instanceof Error ? archiveError.message : "删除长期记忆失败。");
    } finally {
      setBusyId("");
    }
  }

  function handleLogout() {
    setUser(null);
    router.push("/");
  }

  const visibleMemories = useMemo(() => {
    const cleanQuery = query.trim().toLowerCase();
    if (!cleanQuery) {
      return memories;
    }
    return memories.filter((memory) => {
      return (
        memory.content.toLowerCase().includes(cleanQuery) ||
        memory.memory_type.toLowerCase().includes(cleanQuery) ||
        (memory.normalized_key || "").toLowerCase().includes(cleanQuery)
      );
    });
  }, [memories, query]);

  const averageConfidence = useMemo(() => {
    if (!memories.length) {
      return 0;
    }
    const total = memories.reduce((sum, memory) => sum + memory.confidence, 0);
    return Math.round((total / memories.length) * 100);
  }, [memories]);

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
    <main className="app-shell memory-shell">
      <ConversationSidebar user={user} onLogout={handleLogout} />

      <section className="memory-main">
        <header className="memory-header">
          <div>
            <strong>长期记忆</strong>
            <span>{user.email}</span>
          </div>
          <button type="button" onClick={() => loadMemories()}>
            刷新
          </button>
        </header>

        <div className="memory-toolbar">
          <div className="memory-stats">
            <span>
              <strong>{memories.length}</strong>
              记忆
            </span>
            <span>
              <strong>{averageConfidence}%</strong>
              平均置信度
            </span>
          </div>

          <div className="memory-controls">
            <input
              value={query}
              placeholder="搜索记忆"
              onChange={(event) => setQuery(event.target.value)}
            />
            <select value={selectedType} onChange={(event) => setSelectedType(event.target.value)}>
              {MEMORY_TYPES.map((type) => (
                <option value={type.value} key={type.value || "all"}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error ? <p className="memory-error">{error}</p> : null}

        <div className="memory-list">
          {isLoading ? (
            <div className="memory-empty">
              <div className="analysis-pulse small" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <span>加载中</span>
            </div>
          ) : visibleMemories.length ? (
            visibleMemories.map((memory) => {
              const editing = editingId === memory.memory_id;
              return (
                <article className="memory-item" key={memory.memory_id}>
                  <div className="memory-item-head">
                    <div>
                      <span className="memory-type">{TYPE_LABELS[memory.memory_type] || memory.memory_type}</span>
                      <strong>{memory.normalized_key || memory.memory_id.slice(0, 10)}</strong>
                    </div>
                    <div className="memory-score">
                      <span>{Math.round(memory.importance * 100)} I</span>
                      <span>{Math.round(memory.confidence * 100)} C</span>
                    </div>
                  </div>

                  {editing ? (
                    <div className="memory-edit">
                      <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} />
                      <div className="memory-edit-grid">
                        <label>
                          类型
                          <select value={draftType} onChange={(event) => setDraftType(event.target.value)}>
                            {MEMORY_TYPES.filter((type) => type.value).map((type) => (
                              <option value={type.value} key={type.value}>
                                {type.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          重要性
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={draftImportance}
                            onChange={(event) => setDraftImportance(Number(event.target.value))}
                          />
                        </label>
                        <label>
                          置信度
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={draftConfidence}
                            onChange={(event) => setDraftConfidence(Number(event.target.value))}
                          />
                        </label>
                      </div>
                      <div className="memory-actions">
                        <button type="button" onClick={() => saveEdit(memory.memory_id)} disabled={busyId === memory.memory_id}>
                          保存
                        </button>
                        <button type="button" onClick={cancelEdit}>
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p>{memory.content}</p>
                      <div className="memory-meta">
                        <span>{memory.source_type}</span>
                        <span>{formatDate(memory.updated_at || memory.created_at)}</span>
                      </div>
                      <div className="memory-actions">
                        <button type="button" onClick={() => startEdit(memory)}>
                          编辑
                        </button>
                        <button type="button" onClick={() => archiveMemory(memory.memory_id)} disabled={busyId === memory.memory_id}>
                          删除
                        </button>
                      </div>
                    </>
                  )}
                </article>
              );
            })
          ) : (
            <div className="memory-empty">
              <strong>暂无长期记忆</strong>
              <span>完成几轮论文问答后，这里会出现可复用的偏好和研究上下文。</span>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function formatDate(value?: string | null) {
  if (!value) {
    return "未记录时间";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
