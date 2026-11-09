import client from '@/shared/api/client';

export interface WechatBindSession {
  id: number;
  bind_code: string;
  qr_value: string;
  status: 'pending' | 'bound' | 'expired' | 'cancelled';
  expires_at: string;
  bound_at: string | null;
}

export interface WechatAccount {
  bound: boolean;
  openid_masked?: string | null;
  bound_at?: string | null;
}

export interface WechatParentInvitation {
  parent_name: string;
  student_name: string;
  bind_code: string;
  qr_value: string;
  status: 'pending' | 'bound' | 'expired' | 'cancelled';
  expires_at: string;
}

export interface WechatGuardianContext {
  id: number;
  guardian_name: string;
  openid_masked: string;
  push_time: string;
  paused: boolean;
  status: string;
  latest_summary_title?: string | null;
  latest_summary_content?: string | null;
  latest_summary_created_at?: string | null;
}

export interface WechatGuardianSettings {
  push_time_options: string[];
  default_push_time: string;
}

export const wechatApi = {
  getAccount: () => client.get<WechatAccount>('/api/channels/wechat/account').then((r) => r.data),
  createBindSession: () =>
    client.post<WechatBindSession>('/api/channels/wechat/bind-sessions').then((r) => r.data),
  getBindSession: (id: number) =>
    client.get<WechatBindSession>(`/api/channels/wechat/bind-sessions/${id}`).then((r) => r.data),
  getParentInvitation: (scene: string) =>
    client
      .get<WechatParentInvitation>(
        `/api/channels/wechat/parent-invitations/${encodeURIComponent(scene)}`,
      )
      .then((r) => r.data),
  getGuardianSettings: () =>
    client
      .get<WechatGuardianSettings>('/api/channels/wechat/guardian-settings')
      .then((r) => r.data),
  listGuardianContexts: () =>
    client
      .get<WechatGuardianContext[]>('/api/channels/wechat/guardian-contexts')
      .then((r) => r.data),
  createGuardianInvitation: () =>
    client
      .post<WechatBindSession>('/api/channels/wechat/guardian-invitations')
      .then((r) => r.data),
  updateGuardianContext: (
    id: number,
    payload: { push_time?: string; paused?: boolean },
  ) =>
    client
      .patch<WechatGuardianContext>(`/api/channels/wechat/guardian-contexts/${id}`, payload)
      .then((r) => r.data),
  unbindGuardianContext: (id: number) =>
    client.delete<void>(`/api/channels/wechat/guardian-contexts/${id}`).then((r) => r.data),
  unbind: () => client.delete<void>('/api/channels/wechat/account').then((r) => r.data),
  reportProgress: () =>
    client
      .post<{ sent: number; failed: number }>('/api/channels/wechat/report-progress')
      .then((r) => r.data),
};
