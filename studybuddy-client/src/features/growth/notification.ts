import client from '@/shared/api/client';
import type { NotificationItem, NotificationListResponse } from '@/types';

export const notificationApi = {
  list: (params?: { unreadOnly?: boolean; limit?: number }) =>
    client
      .get<NotificationListResponse>('/api/notifications', {
        params: {
          unread_only: params?.unreadOnly,
          limit: params?.limit,
        },
      })
      .then((r) => r.data),

  markRead: (notificationId: number) =>
    client.patch<NotificationItem>(`/api/notifications/${notificationId}/read`).then((r) => r.data),
};
