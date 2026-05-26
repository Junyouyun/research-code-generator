"use client";

import { useRouter } from "next/navigation";
import { KeyboardEvent, useEffect, useState } from "react";

import {
  Conversation,
  deleteConversation,
  mergeProjectConversations,
  readConversations,
  renameConversation,
  subscribeConversations,
} from "./conversations";
import { listProjects, logout, User } from "../lib/api";

type ConversationSidebarProps = {
  currentProjectId?: string;
  user?: User;
  onLogout?: () => void;
};

export function ConversationSidebar({ currentProjectId, user, onLogout }: ConversationSidebarProps) {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [menuId, setMenuId] = useState("");
  const [editingId, setEditingId] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [logoutError, setLogoutError] = useState("");

  function reload() {
    setConversations(readConversations());
  }

  useEffect(() => {
    reload();
    return subscribeConversations(reload);
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    listProjects()
      .then((result) => {
        mergeProjectConversations(result.projects);
        reload();
      })
      .catch(() => undefined);
  }, [user]);

  function openConversation(conversation: Conversation) {
    if (editingId) {
      return;
    }

    if (conversation.projectId) {
      router.push(`/projects/${conversation.projectId}`);
    }
  }

  function startRename(conversation: Conversation) {
    setEditingId(conversation.id);
    setDraftTitle(conversation.title);
    setMenuId("");
  }

  function finishRename() {
    if (editingId) {
      renameConversation(editingId, draftTitle);
    }
    setEditingId("");
    setDraftTitle("");
  }

  function handleRenameKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      finishRename();
    }
    if (event.key === "Escape") {
      setEditingId("");
      setDraftTitle("");
    }
  }

  async function handleLogout() {
    setLogoutError("");
    try {
      await logout();
      onLogout?.();
      router.push("/");
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : "退出失败，请稍后再试。");
    }
  }

  const displayName = user?.display_name || user?.email || "Research Code";
  const avatar = user?.avatar_initial || displayName.slice(0, 1).toUpperCase() || "R";

  return (
    <aside className="conversation-sidebar">
      <div className="sidebar-user">
        <span className="user-avatar">{avatar}</span>
        <div className="sidebar-user-text">
          <strong>{displayName}</strong>
          <span>{user ? user.plan : "Research Code"}</span>
        </div>
      </div>

      {user ? (
        <button className="logout-button" type="button" onClick={handleLogout}>
          退出登录
        </button>
      ) : null}

      {logoutError ? <p className="sidebar-error">{logoutError}</p> : null}

      <button className="new-chat-button" type="button" onClick={() => router.push("/")}>
        <span>+</span>
        新建分析
      </button>

      {user ? (
        <button className="memory-nav-button" type="button" onClick={() => router.push("/settings/memory")}>
          Memory
        </button>
      ) : null}

      <div className="sidebar-section-title">最近项目</div>

      <div className="conversation-list">
        {conversations.length ? (
          conversations.map((conversation) => {
            const active = conversation.projectId && conversation.projectId === currentProjectId;

            return (
              <div className={active ? "conversation-item active" : "conversation-item"} key={conversation.id}>
                {editingId === conversation.id ? (
                  <input
                    className="conversation-rename-input"
                    value={draftTitle}
                    autoFocus
                    onBlur={finishRename}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onKeyDown={handleRenameKey}
                  />
                ) : (
                  <button className="conversation-title" type="button" onClick={() => openConversation(conversation)}>
                    {conversation.title}
                  </button>
                )}

                <button
                  className="conversation-more"
                  type="button"
                  aria-label="打开项目菜单"
                  onClick={() => setMenuId((current) => (current === conversation.id ? "" : conversation.id))}
                >
                  ...
                </button>

                {menuId === conversation.id ? (
                  <div className="conversation-menu">
                    <button type="button" onClick={() => startRename(conversation)}>
                      重命名
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        deleteConversation(conversation.id);
                        setMenuId("");
                      }}
                    >
                      删除
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })
        ) : (
          <p className="sidebar-empty">上传一篇论文后，这里会显示最近的分析项目。</p>
        )}
      </div>
    </aside>
  );
}
