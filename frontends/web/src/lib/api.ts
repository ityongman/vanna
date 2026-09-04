export interface AuthMe {
  id: string;
  email: string | null;
  is_admin: boolean;
  businesses: string[];
}

export interface ConversationMeta {
  id: string;
  updated_at: string;
  messages: { role: string; content: string }[];
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
  conversations: () => fetchJson<ConversationMeta[]>("/api/conversations"),
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
