import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import ExamTakingPage from '@/features/exams/pages/ExamTakingPage';
import { answerApi } from '@/features/exams/answer';
import { examApi } from '@/features/exams/exam';
import { useExamStore } from '@/features/exams/store';
import type { ExamDetail } from '@/types';

vi.mock('@/features/exams/exam', () => ({
  examApi: {
    detail: vi.fn(),
    start: vi.fn(),
  },
}));
vi.mock('@/features/exams/answer', () => ({
  answerApi: { submit: vi.fn() },
}));

function createDefaultExam(): ExamDetail {
  return {
    id: 1,
    title: '数学小测',
    feedback_mode: 'after_submit',
    questions: [
      {
        id: 10,
        type: 'single_choice',
        stem: '1 + 1 = ?',
        options: ['1', '2', '3'],
        score: 2,
        group_id: null,
      },
      {
        id: 11,
        type: 'single_choice',
        stem: '2 + 2 = ?',
        options: ['2', '4', '6'],
        score: 2,
        group_id: null,
      },
    ],
  };
}

function ResultStateProbe() {
  const location = useLocation();
  return <div data-testid="result-state">{`${location.search}|${JSON.stringify(location.state)}`}</div>;
}

function renderPage(
  initialEntry: string = '/exams/1/take',
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/exams/:examId/take" element={<ExamTakingPage />} />
        <Route path="/exams/:examId/result" element={<ResultStateProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ExamTakingPage 手机端答题', () => {
  beforeEach(() => {
    useExamStore.setState({ drafts: {}, marked: {}, activeRecord: null });
    vi.clearAllMocks();
    vi.mocked(examApi.detail).mockReset().mockResolvedValue(createDefaultExam());
    vi.mocked(examApi.start)
      .mockReset()
      .mockResolvedValue({ exam_record_id: 100, exam_id: 1, status: 'in_progress' });
    vi.mocked(answerApi.submit).mockReset().mockResolvedValue({
      exam_record_id: 100,
      status: 'submitted',
      objective_score: 4,
      pending_manual_count: 0,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('计划内试卷交卷后把 planItemId 传到结果页', async () => {
    renderPage('/exams/1/take?plan_item_id=100');
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('radio')[1]);
    fireEvent.click(screen.getByRole('button', { name: /交\s*卷/ }));
    fireEvent.click(await screen.findByRole('button', { name: '确认交卷' }));

    await waitFor(() => expect(screen.getByTestId('result-state')).toBeInTheDocument());
    expect(screen.getByTestId('result-state')).toHaveTextContent('plan_item_id=100');
  });

  it('渲染第一题题干与题型标签', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    expect(screen.getAllByText('单选题').length).toBeGreaterThan(0);
  });

  it('短题时底部操作栏仍贴近视口底部', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());

    expect(screen.getByTestId('exam-taking-page')).toHaveStyle({
      minHeight: '100dvh',
      display: 'flex',
      flexDirection: 'column',
    });
    expect(screen.getByTestId('exam-question-section')).toHaveStyle({ flex: '1' });
  });

  it('单选题选完后自动跳到下一题', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole('radio')[1]); // 选 B（"2"）
    await vi.advanceTimersByTimeAsync(500);
    await waitFor(() => expect(screen.getByText('2 + 2 = ?')).toBeInTheDocument());
  });

  it('单选后手动下一题会取消待执行的自动跳题', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('radio')[1]);
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    await vi.advanceTimersByTimeAsync(500);

    expect(screen.getByText('2 + 2 = ?')).toBeInTheDocument();
  });

  it('单选后从答题卡切题会取消待执行的自动跳题', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('radio')[1]);
    fireEvent.click(screen.getByRole('button', { name: /答题卡/ }));
    const grid = await waitFor(() => screen.getByTestId('answer-card-grid'));
    fireEvent.click(within(grid).getByRole('button', { name: /第 1 题/ }));
    await vi.advanceTimersByTimeAsync(500);

    expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument();
  });

  it('标记按钮切换当前题的标记状态', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '标记本题' }));
    expect(useExamStore.getState().isMarked(100, 10)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '标记本题' }));
    expect(useExamStore.getState().isMarked(100, 10)).toBe(false);
  });

  it('单选后立即标记会取消自动跳题', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('radio')[1]);
    fireEvent.click(screen.getByRole('button', { name: '标记本题' }));
    await vi.advanceTimersByTimeAsync(500);

    expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument();
    expect(useExamStore.getState().isMarked(100, 10)).toBe(true);
    expect(useExamStore.getState().isMarked(100, 11)).toBe(false);
  });

  it('答题卡默认收起，点按钮后展开题号', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    // 默认不显示"答题卡"网格容器
    expect(screen.queryByTestId('answer-card-grid')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /答题卡/ }));
    await waitFor(() => expect(screen.getByTestId('answer-card-grid')).toBeInTheDocument());
  });

  it('答题卡抽屉按内容高度展开，并限制最大高度', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /答题卡/ }));

    const drawerWrapper = await waitFor(() => {
      const element = document.querySelector<HTMLElement>('.ant-drawer-content-wrapper');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    expect(drawerWrapper).toHaveStyle({ height: 'auto', maxHeight: '70vh' });
  });

  it('答题卡交卷按钮固定在抽屉 footer', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('1 + 1 = ?')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /答题卡/ }));

    const footer = await waitFor(() => {
      const element = document.querySelector<HTMLElement>('.ant-drawer-footer');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    expect(within(footer).getByRole('button', { name: /交\s*卷/ })).toBeInTheDocument();
  });

  it('卸载后的旧试卷请求不会覆盖当前考试记录', async () => {
    let resolveFirstExam!: (value: Awaited<ReturnType<typeof examApi.detail>>) => void;
    const firstExam = new Promise<Awaited<ReturnType<typeof examApi.detail>>>((resolve) => {
      resolveFirstExam = resolve;
    });

    vi.mocked(examApi.detail).mockImplementation((id) => {
      if (id === 1) return firstExam;
      return Promise.resolve({
        id: 2,
        title: '第二份试卷',
        feedback_mode: 'after_submit',
        questions: [
          {
            id: 20,
            type: 'single_choice',
            stem: '3 + 3 = ?',
            options: ['5', '6'],
            score: 2,
            group_id: null,
          },
        ],
      });
    });
    vi.mocked(examApi.start).mockImplementation((id) =>
      Promise.resolve({ exam_record_id: id * 100, exam_id: id, status: 'in_progress' }),
    );

    const firstRender = renderPage('/exams/1/take');
    await waitFor(() => expect(examApi.detail).toHaveBeenCalledWith(1));
    firstRender.unmount();

    renderPage('/exams/2/take');
    await waitFor(() => expect(screen.getByText('3 + 3 = ?')).toBeInTheDocument());
    expect(useExamStore.getState().activeRecord?.exam_id).toBe(2);

    await act(async () => {
      resolveFirstExam({
        id: 1,
        title: '第一份试卷',
        feedback_mode: 'after_submit',
        questions: [
          {
            id: 10,
            type: 'single_choice',
            stem: '1 + 1 = ?',
            options: ['1', '2'],
            score: 2,
            group_id: null,
          },
        ],
      });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(examApi.start).not.toHaveBeenCalledWith(1);
    expect(useExamStore.getState().activeRecord?.exam_id).toBe(2);
  });

  it('卸载后才返回的旧 start 请求不会覆盖当前考试记录', async () => {
    let resolveFirstStart!: (value: Awaited<ReturnType<typeof examApi.start>>) => void;
    const firstStart = new Promise<Awaited<ReturnType<typeof examApi.start>>>((resolve) => {
      resolveFirstStart = resolve;
    });

    vi.mocked(examApi.detail).mockImplementation((id) =>
      Promise.resolve({
        id,
        title: `试卷 ${id}`,
        feedback_mode: 'after_submit',
        questions: [
          {
            id: id * 10,
            type: 'single_choice',
            stem: id === 1 ? '1 + 1 = ?' : '3 + 3 = ?',
            options: ['1', '2'],
            score: 2,
            group_id: null,
          },
        ],
      }),
    );
    vi.mocked(examApi.start).mockImplementation((id) => {
      if (id === 1) return firstStart;
      return Promise.resolve({ exam_record_id: 200, exam_id: 2, status: 'in_progress' });
    });

    const firstRender = renderPage('/exams/1/take');
    await waitFor(() => expect(examApi.start).toHaveBeenCalledWith(1));
    firstRender.unmount();

    renderPage('/exams/2/take');
    await waitFor(() => expect(screen.getByText('3 + 3 = ?')).toBeInTheDocument());
    expect(useExamStore.getState().activeRecord?.exam_id).toBe(2);

    await act(async () => {
      resolveFirstStart({ exam_record_id: 100, exam_id: 1, status: 'in_progress' });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useExamStore.getState().activeRecord?.exam_id).toBe(2);
  });
});
