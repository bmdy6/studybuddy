import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import ProtectedRoute from '@/features/auth/ProtectedRoute';

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: false, role: null }),
}));

function LoginTarget() {
  const location = useLocation();
  return <div>from:{String((location.state as { from?: string } | null)?.from)}</div>;
}

describe('ProtectedRoute', () => {
  it('未登录时保留微信深链接的路径和查询参数', async () => {
    render(
      <MemoryRouter initialEntries={['/materials?source=wechat']}>
        <Routes>
          <Route
            path="/materials"
            element={
              <ProtectedRoute>
                <div>materials</div>
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<LoginTarget />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('from:/materials?source=wechat')).toBeInTheDocument();
  });
});
