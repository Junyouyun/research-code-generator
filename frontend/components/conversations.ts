"use client";

export type Conversation = {
  id: string;
  title: string;
  projectId?: string;
  createdAt: string;
  updatedAt: string;
};

const STORAGE_KEY = "research_code_conversations";
const CHANGE_EVENT = "research_code_conversations_changed";

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function readConversations(): Conversation[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const items = JSON.parse(raw) as Conversation[];
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

function writeConversations(conversations: Conversation[]) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function subscribeConversations(callback: () => void) {
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", callback);

  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

export function saveProjectConversation(projectId: string, title: string) {
  const now = new Date().toISOString();
  const conversations = readConversations();
  const existing = conversations.find((item) => item.projectId === projectId);

  if (existing) {
    writeConversations(
      conversations.map((item) =>
        item.projectId === projectId ? { ...item, title: title || item.title, updatedAt: now } : item,
      ),
    );
    return;
  }

  writeConversations([
    {
      id: createId(),
      title: title || "未命名论文",
      projectId,
      createdAt: now,
      updatedAt: now,
    },
    ...conversations,
  ]);
}

export function mergeProjectConversations(projects: { project_id: string; original_filename: string }[]) {
  const now = new Date().toISOString();
  const conversations = readConversations();
  const existingProjectIds = new Set(conversations.map((item) => item.projectId).filter(Boolean));
  const additions = projects
    .filter((project) => !existingProjectIds.has(project.project_id))
    .map((project) => ({
      id: createId(),
      title: project.original_filename || "未命名论文",
      projectId: project.project_id,
      createdAt: now,
      updatedAt: now,
    }));

  if (additions.length) {
    writeConversations([...additions, ...conversations]);
  }
}

export function ensureProjectConversation(projectId: string, title: string) {
  const conversations = readConversations();
  if (conversations.some((item) => item.projectId === projectId)) {
    return;
  }

  const now = new Date().toISOString();
  writeConversations([
    {
      id: createId(),
      title: title || "未命名论文",
      projectId,
      createdAt: now,
      updatedAt: now,
    },
    ...conversations,
  ]);
}

export function renameConversation(id: string, title: string) {
  const trimmedTitle = title.trim();
  if (!trimmedTitle) {
    return;
  }

  const now = new Date().toISOString();
  writeConversations(
    readConversations().map((item) => (item.id === id ? { ...item, title: trimmedTitle, updatedAt: now } : item)),
  );
}

export function deleteConversation(id: string) {
  writeConversations(readConversations().filter((item) => item.id !== id));
}
