import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  mockList,
  mockPreviewUrl,
  mockDelete,
  mockRecognize,
  mockGetExtraction,
  mockConfirmExtraction,
  mockUpload,
  mockMessageError,
  mockMessageWarning,
} = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockPreviewUrl: vi.fn(),
  mockDelete: vi.fn(),
  mockRecognize: vi.fn(),
  mockGetExtraction: vi.fn(),
  mockConfirmExtraction: vi.fn(),
  mockUpload: vi.fn(),
  mockMessageError: vi.fn(),
  mockMessageWarning: vi.fn(),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: {
      success: vi.fn(),
      error: mockMessageError,
      warning: mockMessageWarning,
    },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

vi.mock('@/features/materials/api', () => ({
  materialApi: {
    list: mockList,
    previewUrl: mockPreviewUrl,
    delete: mockDelete,
    upload: mockUpload,
    recognize: mockRecognize,
    getExtraction: mockGetExtraction,
    confirmExtraction: mockConfirmExtraction,
  },
}));


import MaterialsPage from '@/features/materials/pages/MaterialsPage';
import { useAuthStore } from '@/features/auth/store';
import type { MaterialItem } from '../types';

function material(overrides: Partial<MaterialItem>): MaterialItem {
  return {
    id: 705,
    name: 'IMG_20260705_145431',
    type: 'image',
    source: 'student',
    knowledge_tags: [],
    recognition_status: 'pending',
    uploaded_by: '弟弟正式账号',
    cos_url: '/uploads/materials/2026/07/demo.jpg',
    created_at: '2026-07-05 14:54:48',
    ...overrides,
  };
}

describe('MaterialsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      token: 'token-a',
      role: 'student',
      displayName: '账号A',
      avatar: null,
      userId: 1,
      children: [],
      activeChildId: null,
      authVersion: 0,
    });
  });

  it('链接按钮先获取鉴权预览地址再打开', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    mockList.mockResolvedValue([material({})]);
    mockPreviewUrl.mockResolvedValue({
      url: '/sb/uploads/materials/2026/07/demo.jpg',
      ext: 'jpg',
      name: 'IMG_20260705_145431',
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);

    await screen.findByText('IMG_20260705_145431');
    await userEvent.click(screen.getByLabelText('打开素材链接'));

    expect(mockPreviewUrl).toHaveBeenCalledWith(705);
    expect(openSpy).toHaveBeenCalledWith('/sb/uploads/materials/2026/07/demo.jpg', '_blank');
  });

  it('pending 素材渲染为「已上传·可用」而非「识别中」', async () => {
    mockList.mockResolvedValue([material({ recognition_status: 'pending' })]);

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);

    await screen.findByText('IMG_20260705_145431');
    expect(screen.getByText(/已上传·可用/)).toBeInTheDocument();
    expect(screen.queryByText(/识别中/)).not.toBeInTheDocument();
  });

  it('当前账号变化后重新加载素材列表', async () => {
    mockList
      .mockResolvedValueOnce([material({ id: 1, name: '账号A素材', uploaded_by: 'A' })])
      .mockResolvedValueOnce([material({ id: 2, name: '账号B素材', uploaded_by: 'B' })]);

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);

    await screen.findByText('账号A素材');

    useAuthStore.setState({
      token: 'token-b',
      role: 'student',
      displayName: '账号B',
      avatar: null,
      userId: 2,
      children: [],
      activeChildId: null,
      authVersion: 1,
    });

    await screen.findByText('账号B素材');

    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('失败素材提供重新识别，并在成功后刷新列表状态', async () => {
    mockList
      .mockResolvedValueOnce([material({ recognition_status: 'failed' })])
      .mockResolvedValueOnce([material({ recognition_status: 'recognized', auto_ready: true })]);
    mockRecognize.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'recognized',
      recognized_markdown: '### 英语单词表\n\nshopkeeper 店主',
      confirmed_markdown: null,
      uncertain_points: [],
      auto_ready: true,
    });
    mockGetExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'failed',
      recognized_markdown: null,
      confirmed_markdown: null,
      uncertain_points: [],
      auto_ready: false,
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);

    await screen.findByText('IMG_20260705_145431');
    await userEvent.click(screen.getByRole('button', { name: /查看识别失败详情/ }));
    await screen.findByText('没有识别到可用内容');
    await userEvent.click(screen.getByRole('button', { name: /重新识别/ }));

    await waitFor(() => expect(mockRecognize).toHaveBeenCalledWith(705));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('低置信识别稿提示机器结果可能有误并允许保存修正', async () => {
    mockList.mockResolvedValue([material({ recognition_status: 'needs_review' })]);
    mockGetExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'needs_review',
      raw_text: 'raw',
      recognized_markdown: '### 英语单词表\n\nshopkeeper 店主',
      confirmed_markdown: null,
      summary: null,
      content_type: '英语单词表',
      recognition_provider: 'mimo',
      recognition_confidence: 'medium',
      uncertain_points: ['第二行单词需要确认'],
      recognized_at: null,
      confirmed_at: null,
    });
    mockConfirmExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'confirmed',
      confirmed_markdown: '### 英语单词表\n\nshopkeeper 店主',
      uncertain_points: [],
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);

    await screen.findByText('IMG_20260705_145431');
    await userEvent.click(screen.getByRole('button', { name: /查看识别稿/ }));

    await screen.findByText('shopkeeper 店主');
    expect(screen.getByText('第二行单词需要确认')).toBeInTheDocument();

    expect(screen.getAllByText('可供助手使用·建议核对')).toHaveLength(2);
    await userEvent.click(screen.getByRole('button', { name: /保存修正/ }));

    await waitFor(() =>
      expect(mockConfirmExtraction).toHaveBeenCalledWith(705, '### 英语单词表\n\nshopkeeper 店主'),
    );
  });

  it('高置信识别结果自动可供助手使用，不再要求人工确认', async () => {
    mockList.mockResolvedValue([material({ recognition_status: 'recognized', auto_ready: true })]);
    mockGetExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'recognized',
      recognized_markdown: '### 英语单词表',
      confirmed_markdown: null,
      recognition_confidence: 'high',
      uncertain_points: [],
      auto_ready: true,
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);
    await screen.findByText('IMG_20260705_145431');

    expect(screen.getByText('可供助手使用')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /查看识别稿/ }));

    expect(await screen.findByText('这份机器识别结果已可供助手使用。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /确认给 Agent 使用/ })).not.toBeInTheDocument();
  });

  it('空白识别结果不进入编辑器，失败状态只提供重新识别', async () => {
    mockList.mockResolvedValue([material({ recognition_status: 'failed' })]);
    mockGetExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'failed',
      recognized_markdown: '   ',
      confirmed_markdown: null,
      uncertain_points: [],
      auto_ready: false,
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);
    await screen.findByText('IMG_20260705_145431');
    await userEvent.click(screen.getByRole('button', { name: /查看识别失败详情/ }));

    expect(await screen.findByText('没有识别到可用内容')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/AI 识别出的 Markdown/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重新识别/ })).toBeInTheDocument();
  });

  it('修正内容被清空时保存按钮禁用', async () => {
    mockList.mockResolvedValue([material({ recognition_status: 'needs_review' })]);
    mockGetExtraction.mockResolvedValue({
      material_id: 705,
      name: 'IMG_20260705_145431',
      recognition_status: 'needs_review',
      recognized_markdown: '原识别稿',
      confirmed_markdown: null,
      recognition_confidence: 'low',
      uncertain_points: [],
      auto_ready: false,
    });

    render(<MemoryRouter><MaterialsPage /></MemoryRouter>);
    await screen.findByText('IMG_20260705_145431');
    await userEvent.click(screen.getByRole('button', { name: /查看识别稿/ }));
    const editor = await screen.findByPlaceholderText(/AI 识别出的 Markdown/);
    await userEvent.clear(editor);

    expect(screen.getByRole('button', { name: /保存修正/ })).toBeDisabled();
  });

  it('上传命中重复素材时提示已存在并定位已有记录', async () => {
    mockList.mockResolvedValue([material({ name: '已有单词表', recognition_status: 'recognized' })]);
    mockUpload.mockResolvedValue({
      material_id: 705,
      name: '已有单词表',
      type: 'image',
      source: 'student',
      cos_key: 'existing.jpg',
      uploaded_by: '弟弟正式账号',
      created_at: '2026-07-05 14:54:48',
      is_duplicate: true,
      duplicate_of_material_id: 705,
    });

    const { container } = render(<MemoryRouter><MaterialsPage /></MemoryRouter>);
    await screen.findByText('已有单词表');
    await userEvent.click(screen.getByRole('button', { name: /上传素材/ }));
    const fileInput = container.ownerDocument.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, new File(['same'], '已有单词表.jpg', { type: 'image/jpeg' }));
    await userEvent.click(screen.getByRole('button', { name: /全部上传/ }));

    await waitFor(() => expect(mockMessageWarning).toHaveBeenCalledWith('素材已存在：已有单词表'));
    expect(screen.getByPlaceholderText('搜索素材名或知识点')).toHaveValue('已有单词表');
  });
});
// agg-1 P2
