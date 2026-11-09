import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    role: 'student',
    displayName: '弟弟',
  }),
}));

import HelpPage from '@/app/pages/HelpPage';
import { latestReleaseNote, releaseNotes } from '@/shared/data/releaseNotes';

describe('HelpPage', () => {
  it('展示使用指南和更新记录', () => {
    render(<HelpPage />);

    expect(screen.getByText('帮助与更新')).toBeInTheDocument();
    expect(screen.getByText('使用指南')).toBeInTheDocument();
    expect(screen.getByText('更新记录')).toBeInTheDocument();
    expect(screen.getByText('学生日常使用')).toBeInTheDocument();
    expect(screen.getAllByText(latestReleaseNote.version).length).toBeGreaterThan(0);
    expect(screen.getAllByText(latestReleaseNote.title).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('tab', { name: '更新记录' }));
    for (const note of releaseNotes.slice(0, 5)) {
      expect(screen.getAllByText(note.version).length).toBeGreaterThan(0);
      expect(screen.getAllByText(note.title).length).toBeGreaterThan(0);
    }
  });
});
