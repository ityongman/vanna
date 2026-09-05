export interface AuthMe {
  id: string;
  email: string | null;
  is_admin: boolean;
  businesses: string[];
}

export interface ConversationMessageMeta {
  role: string;
  content: string;
  rich?: Record<string, any>[];
}

export interface ConversationMeta {
  id: string;
  updated_at: string;
  metadata?: { title?: string; business_id?: string };
  messages: ConversationMessageMeta[];
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("unauthorized");
    if (res.status === 403) throw new Error("forbidden");
    throw new Error(`request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => fetchJson<AuthMe>("/api/auth/me"),
  conversations: (businessId?: string) =>
    fetchJson<ConversationMeta[]>(
      businessId
        ? `/api/conversations?business_id=${encodeURIComponent(businessId)}`
        : '/api/conversations'
    ),
  conversation: (id: string) => fetchJson<ConversationMeta>(`/api/conversations/${id}`),
  deleteConversation: (id: string) =>
    fetchJson<{ deleted: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
  schemaTables: (businessId: string) =>
    fetchJson<{ business_id: string; namespace: string; tables: any[] }>(
      `/api/schema/tables?business_id=${encodeURIComponent(businessId)}`
    ),
  deleteSchemaTable: (table: string, businessId: string) =>
    fetchJson<{ removed_columns: number }>(
      `/api/schema/tables/${encodeURIComponent(table)}?business_id=${encodeURIComponent(businessId)}`,
      { method: "DELETE" }
    ),
};
