export type Workspace = {
  id: string;
  name: string;
  slug: string;
  role: "OWNER" | "ADMIN" | "MEMBER";
};

export type User = {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
};

export type CurrentUser = {
  user: User;
  workspaces: Workspace[];
  selected_workspace: Workspace | null;
};

export type SessionInfo = {
  id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  device_label: string;
  is_current: boolean;
};

export type WorkspaceMember = {
  user_id: string;
  full_name: string;
  email: string;
  role: Workspace["role"];
  joined_at: string;
};
