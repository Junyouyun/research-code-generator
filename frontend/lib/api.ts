const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api";

export type ProjectStatus = {
  project_id: string;
  status: string;
  current_step: string;
  progress: number;
  error_message?: string | null;
  events?: ProjectEvent[];
};

export type ProjectListItem = {
  project_id: string;
  status: string;
  current_step: string;
  progress: number;
  original_filename: string;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ProjectListResult = {
  projects: ProjectListItem[];
};

export type User = {
  user_id: string;
  email: string;
  display_name?: string | null;
  avatar_initial?: string | null;
  plan: string;
};

export type AuthResult = {
  user: User;
};

export type ProjectEvent = {
  step: string;
  level: string;
  message: string;
  duration_ms?: number | null;
  details?: ThoughtDetails | null;
  created_at?: string | null;
};

export type ThoughtDetails = {
  kind?: string;
  title?: string;
  summary?: string;
  bullets?: string[];
  tags?: string[];
};

export type UploadResult = {
  project_id: string;
  status: string;
};

export type ReportResult = {
  project_id: string;
  content: string;
};

export type CodeFile = {
  path: string;
  content: string;
};

export type CodeFilesResult = {
  project_id: string;
  files: CodeFile[];
};

export type GraphEntity = {
  entity_id: string;
  entity_type: string;
  name: string;
  normalized_name: string;
  description?: string | null;
  importance: number;
  confidence: number;
  source_chunk_ids: string[];
  evidence?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type GraphRelation = {
  relation_id: string;
  source_entity_id: string;
  target_entity_id: string;
  source_name?: string | null;
  target_name?: string | null;
  relation_type: string;
  description?: string | null;
  confidence: number;
  source_chunk_ids: string[];
  evidence?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ProjectGraphResult = {
  project_id: string;
  paper_id?: string | null;
  paper_version_id?: string | null;
  entities: GraphEntity[];
  relations: GraphRelation[];
};

export type QuestionResult = {
  project_id: string;
  conversation_id?: string | null;
  answer: string;
  used_chunks: string[];
  confidence: string;
  expanded?: boolean;
  used_related_chunks?: string[];
  retrieval_trace?: Record<string, unknown> | null;
};

export type Conversation = {
  conversation_id: string;
  user_id: string;
  project_id?: string | null;
  title?: string | null;
  status: string;
  short_summary?: string | null;
  summary_updated_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ConversationMessage = {
  message_id: string;
  conversation_id: string;
  project_id?: string | null;
  role: "user" | "assistant" | string;
  content: string;
  content_type: string;
  metadata?: {
    confidence?: string;
    used_chunks?: string[];
    expanded?: boolean;
    used_related_chunks?: string[];
  } | null;
  created_at?: string | null;
};

export type ConversationMessagesResult = {
  conversation_id: string;
  messages: ConversationMessage[];
};

export type ProjectMemory = {
  memory_id: string;
  project_id: string;
  memory_type: string;
  content: string;
  normalized_key?: string | null;
  importance: number;
  confidence: number;
  status: string;
  source_type: string;
  source_id?: string | null;
  evidence?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ProjectMemoriesResult = {
  project_id: string;
  memories: ProjectMemory[];
};

export type UserMemory = {
  memory_id: string;
  memory_type: string;
  content: string;
  normalized_key?: string | null;
  importance: number;
  confidence: number;
  status: string;
  source_type: string;
  source_id?: string | null;
  evidence?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type UserMemoriesResult = {
  memories: UserMemory[];
};

export type UpdateUserMemoryPayload = {
  content?: string;
  memory_type?: string;
  importance?: number;
  confidence?: number;
};

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(url, {
      ...options,
      credentials: "include",
    });
  } catch {
    throw new Error("无法连接后端服务，请确认 http://127.0.0.1:8000 已启动。");
  }

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error("资源还没有生成，或项目 ID 不存在。");
    }
    if (response.status === 401) {
      throw new Error("请先登录后再继续。");
    }
    if (response.status === 403) {
      throw new Error("你没有权限访问这个项目。");
    }
    if (response.status >= 500) {
      throw new Error("后端处理失败，请查看后端日志。");
    }
    throw new Error(`请求失败：${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function register(email: string, password: string, displayName: string): Promise<AuthResult> {
  return requestJson<AuthResult>(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName || null,
    }),
  });
}

export async function login(email: string, password: string): Promise<AuthResult> {
  return requestJson<AuthResult>(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  await requestJson<{ ok: boolean }>(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
  });
}

export async function getMe(): Promise<AuthResult> {
  return requestJson<AuthResult>(`${API_BASE_URL}/auth/me`);
}

export async function uploadPaper(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  return requestJson<UploadResult>(`${API_BASE_URL}/upload`, {
    method: "POST",
    body: formData,
  });
}

export async function listProjects(): Promise<ProjectListResult> {
  return requestJson<ProjectListResult>(`${API_BASE_URL}/projects`);
}

export async function getProject(projectId: string): Promise<ProjectStatus> {
  return requestJson<ProjectStatus>(`${API_BASE_URL}/projects/${projectId}`);
}

export async function getReport(projectId: string): Promise<ReportResult> {
  return requestJson<ReportResult>(`${API_BASE_URL}/projects/${projectId}/report`);
}

export async function getCodeFiles(projectId: string): Promise<CodeFilesResult> {
  return requestJson<CodeFilesResult>(`${API_BASE_URL}/projects/${projectId}/code`);
}

export async function getProjectGraph(projectId: string): Promise<ProjectGraphResult> {
  return requestJson<ProjectGraphResult>(`${API_BASE_URL}/projects/${projectId}/graph`);
}

export async function getProjectConversation(projectId: string): Promise<Conversation> {
  return requestJson<Conversation>(`${API_BASE_URL}/projects/${projectId}/conversation`);
}

export async function getConversationMessages(conversationId: string): Promise<ConversationMessagesResult> {
  return requestJson<ConversationMessagesResult>(`${API_BASE_URL}/conversations/${conversationId}/messages`);
}

export async function getProjectMemories(projectId: string): Promise<ProjectMemoriesResult> {
  return requestJson<ProjectMemoriesResult>(`${API_BASE_URL}/projects/${projectId}/memories`);
}

export async function getUserMemories(memoryType?: string): Promise<UserMemoriesResult> {
  const params = memoryType ? `?memory_type=${encodeURIComponent(memoryType)}` : "";
  return requestJson<UserMemoriesResult>(`${API_BASE_URL}/memories${params}`);
}

export async function updateUserMemory(
  memoryId: string,
  payload: UpdateUserMemoryPayload,
): Promise<UserMemory> {
  return requestJson<UserMemory>(`${API_BASE_URL}/memories/${memoryId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function deleteUserMemory(memoryId: string): Promise<UserMemory> {
  return requestJson<UserMemory>(`${API_BASE_URL}/memories/${memoryId}`, {
    method: "DELETE",
  });
}

export async function askProjectQuestion(projectId: string, question: string, conversationId?: string): Promise<QuestionResult> {
  return requestJson<QuestionResult>(`${API_BASE_URL}/projects/${projectId}/qa`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, conversation_id: conversationId || null }),
  });
}

export function getArtifactUrl(projectId: string): string {
  return `${API_BASE_URL}/projects/${projectId}/artifact`;
}
