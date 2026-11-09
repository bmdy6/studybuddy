import client from '@/shared/api/client';
import type { BlindSpotItem, CreateNoteRequest, NoteItem } from '@/types';

export const noteApi = {
  list: (studentId?: number, subject?: string, type?: string) =>
    client
      .get<NoteItem[]>('/api/notes', { params: { student_id: studentId, subject, type } })
      .then((r) => r.data),

  get: (id: number) => client.get<NoteItem>(`/api/notes/${id}`).then((r) => r.data),

  create: (data: CreateNoteRequest) =>
    client.post<NoteItem>('/api/notes', data).then((r) => r.data),

  update: (
    id: number,
    data: Partial<{ title: string; content: string; knowledge_tags: string[]; category: string; status: string }>,
  ) => client.patch<NoteItem>(`/api/notes/${id}`, data).then((r) => r.data),

  delete: (id: number) => client.delete(`/api/notes/${id}`).then((r) => r.data),

  blindSpots: (studentId?: number) =>
    client
      .get<BlindSpotItem[]>('/api/notes/blind-spots', { params: { student_id: studentId } })
      .then((r) => r.data),

  relatedErrors: (noteId: number) =>
    client
      .get<
        {
          error_id: number;
          question_id: number;
          stem: string;
          error_count: number;
          last_wrong_at: string;
        }[]
      >(`/api/notes/${noteId}/related-errors`)
      .then((r) => r.data),
};
