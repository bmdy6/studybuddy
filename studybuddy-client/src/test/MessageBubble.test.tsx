import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { MessageBubble } from '@/features/chat/components/MessageBubble';
import { MarkdownContent } from '@/shared/components/MarkdownContent';

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('选择工具停用：渲染为文字编号列表', () => {
  it('present_choice_question 渲染成编号文字列表，不显示可点按钮', () => {
    render(
      <MessageBubble
        msg={{
          id: 'a1',
          role: 'assistant',
          content: '你选哪个方向？',
          tools: [
            {
              id: 't1',
              name: 'present_choice_question',
              status: 'done',
              input: {
                question: '你选哪个方向？',
                options: [
                  { label: '数学', value: 'math' },
                  { label: '英语', value: 'english' },
                ],
              },
            },
          ],
        }}
      />,
    );
    // AI 正文正常显示
    expect(screen.getByText('你选哪个方向？')).toBeInTheDocument();
    // 选项渲染成编号文字列表
    expect(screen.getByText(/1\. 数学/)).toBeInTheDocument();
    expect(screen.getByText(/2\. 英语/)).toBeInTheDocument();
    // 不再有可点按钮
    expect(screen.queryByRole('button', { name: '数学' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '英语' })).not.toBeInTheDocument();
  });

  it('有 choice tool 时 AI 正文仍正常显示，不被隐藏', () => {
    render(
      <MessageBubble
        msg={{
          id: 'a2',
          role: 'assistant',
          content: '根据你的情况，我建议先补英语。',
          tools: [
            {
              id: 't2',
              name: 'present_choice_question',
              status: 'done',
              input: {
                question: '先学哪科？',
                options: [{ label: '英语', value: 'english' }],
              },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('根据你的情况，我建议先补英语。')).toBeInTheDocument();
  });
});

describe('MessageBubble tool result rendering', () => {
  it('工具结果 summary 为对象时也能渲染，不把对象作为 React 子节点', () => {
    render(
      <MessageBubble
        msg={{
          id: 'assistant-1',
          role: 'assistant',
          content: '我先看学习地图。',
          tools: [
            {
              id: 'tool-1',
              name: 'query_learning_map',
              status: 'done',
              output: JSON.stringify({
                student_id: 2,
                summary: { weak: 17, reviewing: 0, stable: 0, unknown: 8 },
              }),
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('查询学习地图')).toBeInTheDocument();
    expect(screen.getByText(/优先补 17 个/)).toBeInTheDocument();
    expect(screen.getByText('我先看学习地图。')).toBeInTheDocument();
  });

  it('折叠态长 summary 文本被截断到 30 字加省略号', () => {
    // summary 是对象 -> toDisplayText 走 JSON.stringify 成长串，超过 30 字应被 truncate
    const longSummary = { note: '这是一段非常长的学习总结内容'.repeat(10) };
    render(
      <MessageBubble
        msg={{
          id: 'assistant-2',
          role: 'assistant',
          content: '已查询。',
          tools: [
            {
              id: 'tool-2',
              name: 'query_diagnosis',
              status: 'done',
              output: JSON.stringify({ summary: longSummary }),
            },
          ],
        }}
      />,
    );
    // 摘要以省略号结尾
    const summaryText = screen.getByText(/-/);
    const summaryContent = summaryText.textContent || '';
    expect(summaryContent.endsWith('…')).toBe(true);
    // 去掉 "- " 前缀和省略号后，主体不超过 30 字
    const body = summaryContent.replace(/^-\s*/, '').replace(/…$/, '');
    expect(body.length).toBeLessThanOrEqual(30);
    // 完整长串不应出现在折叠态
    expect(screen.queryByText(JSON.stringify(longSummary))).toBeNull();
  });

  it('折叠态 error 文本节点带省略号样式，可被 CSS 截断', () => {
    render(
      <MessageBubble
        msg={{
          id: 'assistant-3',
          role: 'assistant',
          content: '出错了。',
          tools: [
            {
              id: 'tool-3',
              name: 'grade_homework_photo',
              status: 'error',
              output: '图片识别服务超时，请稍后重试或改用口述题目方式录入。错误码 IMG_TIMEOUT_5000 来自上游服务。',
            },
          ],
        }}
      />,
    );
    // error 文本节点存在
    const errorNode = screen.getByText(/图片识别服务超时/);
    // inline style 含省略号截断样式
    const style = (errorNode as HTMLElement).style;
    expect(style.textOverflow).toBe('ellipsis');
    expect(style.overflow).toBe('hidden');
    expect(style.whiteSpace).toBe('nowrap');
  });

  it('折叠态所有工具卡片标题行固定高度 40px，长短摘要一致', () => {
    const { container } = render(
      <MessageBubble
        msg={{
          id: 'assistant-4',
          role: 'assistant',
          content: '两步操作。',
          tools: [
            {
              id: 'tool-short',
              name: 'query_learning_map',
              status: 'done',
              output: JSON.stringify({
                summary: { weak: 1, reviewing: 0, stable: 0 },
              }),
            },
            {
              id: 'tool-long',
              name: 'query_diagnosis',
              status: 'done',
              output: JSON.stringify({
                summary: { note: '长内容'.repeat(50) },
              }),
            },
          ],
        }}
      />,
    );
    // 工具卡片标题行是可点击的 div（cursor:pointer + height:40）
    const headerRows = container.querySelectorAll('div[style*="cursor: pointer"]');
    expect(headerRows.length).toBeGreaterThanOrEqual(2);
    headerRows.forEach((row) => {
      const style = (row as HTMLElement).style;
      expect(style.height).toBe('40px');
      expect(style.overflow).toBe('hidden');
      expect(style.whiteSpace).toBe('nowrap');
    });
  });
});

describe('MessageBubble markdown 链接点击行为', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderAssistant(content: string) {
    render(
      <MemoryRouter>
        <MessageBubble
          msg={{
            id: 'assistant-link',
            role: 'assistant',
            content,
          }}
        />
      </MemoryRouter>,
    );
  }

  it('应用内 hash 链接（#/notes/123）点击走应用内 navigate，不新开标签页', () => {
    renderAssistant('笔记已保存，可点此查看：[查看笔记](#/notes/123)');

    const link = screen.getByText('查看笔记')?.closest('a');
    expect(link).not.toBeNull();
    expect(link).not.toHaveAttribute('target', '_blank');

    fireEvent.click(link!);

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('/notes/123');
  });

  it('外部 URL 链接仍新开标签页，不触发 navigate', () => {
    renderAssistant('推荐视频：[英语语法精讲](https://www.bilibili.com/video/BV1xxx)');

    const link = screen.getByText('英语语法精讲')?.closest('a');
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');

    fireEvent.click(link!);

    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

describe('MarkdownContent 换行排版', () => {
  it('单个换行渲染为真正的 <br>，不依赖 CSS white-space 兜底', () => {
    const { container } = render(
      <MarkdownContent
        content={`第一行
第二行

第二段`}
      />,
    );
    const ps = container.querySelectorAll('.sb-markdown p');
    // 单个 \n 变成 <br>，\n\n 仍然分段 -> 共 2 个 <p>
    expect(ps.length).toBe(2);
    expect(ps[0].textContent).toContain('第一行');
    expect(ps[0].textContent).toContain('第二行');
    expect(ps[0].querySelector('br')).not.toBeNull();
  });

  it('连续编号追问渲染为紧凑有序列表', () => {
    const { container } = render(
      <MarkdownContent content={'为了帮你制定计划，需要确认：\n1. 今天学习哪些科目？\n2. 有多少时间？\n3. 想先学什么？'} />,
    );

    const list = container.querySelector('.sb-markdown ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(3);
    expect((list as HTMLElement).style.marginTop).toBe('4px');
  });

  it('段落 margin 收紧到 4px，避免多段回复留白过大', () => {
    const { container } = render(
      <MarkdownContent
        content={`第一段

第二段`}
      />,
    );
    const p = container.querySelector('.sb-markdown p') as HTMLElement;
    expect(p.style.marginTop).toBe('4px');
  });
});

describe('assistant 紧凑编号列表显示层规范化', () => {
  function renderAssistant(content: string) {
    return render(
      <MemoryRouter>
        <MessageBubble msg={{ id: 'test', role: 'assistant', content }} />
      </MemoryRouter>,
    );
  }

  it('模型偶发把编号列表挤成一行时，显示层仍渲染为有序列表', () => {
    const { container } = renderAssistant('我可以帮你： 1. 出题 2. 讲解 3. 推荐资源');
    const list = container.querySelector('.sb-markdown ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(3);
  });

  it('版本号和小数不被误判为编号列表', () => {
    const { container } = renderAssistant('当前是版本 1.2.3，已经修复了几个问题');
    expect(container.querySelector('.sb-markdown ol')).toBeNull();
  });

  it('只有一个编号的普通句子不生成列表', () => {
    const { container } = renderAssistant('我有 1. 个问题想问你');
    expect(container.querySelector('.sb-markdown ol')).toBeNull();
  });

  it('引导语换行后再把列表挤成一行时，仍渲染为有序列表（偶发场景）', () => {
    const { container } = renderAssistant('好的，计划如下：\n1. 语文 2. 物理 3. 英语');
    const lists = container.querySelectorAll('.sb-markdown ol');
    expect(lists).toHaveLength(1);
    expect(lists[0]?.querySelectorAll('li')).toHaveLength(3);
  });

  it('多行回复里夹两段紧凑列表时，分别渲染为两个有序列表', () => {
    const { container } = renderAssistant('计划：\n1. 语文 2. 物理\n确认：\n1. 时间 2. 内容');
    const lists = container.querySelectorAll('.sb-markdown ol');
    expect(lists).toHaveLength(2);
    expect(lists[0]?.querySelectorAll('li')).toHaveLength(2);
    expect(lists[1]?.querySelectorAll('li')).toHaveLength(2);
  });

  it('已正确分行的列表不被改动，仍渲染为有序列表', () => {
    const { container } = renderAssistant('1. 语文\n2. 物理\n3. 英语');
    const list = container.querySelector('.sb-markdown ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(3);
  });
});

describe('PracticeExamCard 行动卡', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('create_practice_exam done 时渲染行动卡，点开始作答跳 take 页', () => {
    render(
      <MessageBubble
        msg={{
          id: 'a1',
          role: 'assistant',
          content: '',
          tools: [
            {
              id: 't1',
              name: 'create_practice_exam',
              status: 'done',
              output: JSON.stringify({
                exam_id: 42,
                assignment_id: 7,
                plan_item_id: null,
                title: '一般过去时自练',
                question_count: 3,
              }),
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('自练卷已生成')).toBeInTheDocument();
    expect(screen.getByText(/一般过去时自练 · 3 题/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('开始作答'));
    expect(mockNavigate).toHaveBeenCalledWith('/exams/42/take');
  });

  it('create_practice_exam succeeded 时也渲染行动卡，并保留任务来源', () => {
    render(
      <MessageBubble
        msg={{
          id: 'a-succeeded',
          role: 'assistant',
          content: '',
          tools: [
            {
              id: 't-succeeded',
              name: 'create_practice_exam',
              status: 'succeeded',
              output: JSON.stringify({
                exam_id: 43,
                assignment_id: 8,
                plan_item_id: 100,
                title: '一般过去时自练',
                question_count: 10,
              }),
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('自练卷已生成')).toBeInTheDocument();
    fireEvent.click(screen.getByText('开始作答'));
    expect(mockNavigate).toHaveBeenCalledWith('/exams/43/take?plan_item_id=100');
  });

  it('create_practice_exam running 时回退普通工具卡', () => {
    render(
      <MessageBubble
        msg={{
          id: 'a2',
          role: 'assistant',
          content: '',
          tools: [{ id: 't2', name: 'create_practice_exam', status: 'running' }],
        }}
      />,
    );
    expect(screen.getByText('自练卷')).toBeInTheDocument();
  });
});

// ===== 批次 2：历史单行 markdown 修复（msg 2637 fixture + 防误伤矩阵）=====

const MSG2637_LEGACY =
  '对！**第 3 个** y = x³ + 2x² + 1 不是一元二次函数，因为它有 x³，最高次数是 3 了。 ' +
  '✅ 你能准确判断，说明"一元"和"最高次是 2"这两个条件已经抓住了。 ' +
  '接下来搞清楚 **一元二次函数的图像（抛物线）** 和几个重要要素。 ' +
  '--- ### 第二块：抛物线与顶点 ' +
  '**y = ax² + bx + c** 的图像是一条抛物线，记住几个核心点： ' +
  '**1. 对称轴** x = -b / 2a 这是抛物线的"左右对称线"。 ' +
  '**2. 顶点**（抛物线的最高或最低点） 顶点的横坐标就是对称轴的值，纵坐标把 x 代回去就算出来。 ' +
  '换个好记的说法： > 顶点 = **(-b/2a, f(-b/2a))** ' +
  '**3. a 的正负决定谁是顶点：** - a > 0：开口朝上，顶点是**最低点** - a < 0：开口朝下，顶点是**最高点** ' +
  '--- ### 练一个： y = 2x² - 4x + 1 你能算出它的**对称轴**和**顶点坐标**吗？ ' +
  '不确定也没关系，试着算算看。';

describe('批次2：历史单行 markdown 修复（msg 2637）', () => {
  it('渲染出标题、引用、无序列表，数学符号保留', () => {
    render(
      <MemoryRouter>
        <MarkdownContent content={MSG2637_LEGACY} />
      </MemoryRouter>,
    );
    // 标题渲染（h4 对应 ###）
    expect(screen.getByText(/第二块：抛物线与顶点/)).toBeInTheDocument();
    expect(screen.getByText(/练一个/)).toBeInTheDocument();
    // 引用渲染
    expect(screen.getByText(/顶点 =/)).toBeInTheDocument();
    // 无序列表两项
    expect(screen.getByText(/开口朝上/)).toBeInTheDocument();
    expect(screen.getByText(/开口朝下/)).toBeInTheDocument();
    // 数学符号保留（含比较符与减号原文）
    expect(document.body.textContent).toContain('x = -b / 2a');
    expect(document.body.textContent).toContain('(-b/2a, f(-b/2a))');
    expect(document.body.textContent).toContain('2x² - 4x + 1');
  });

  it('防误伤矩阵不产生额外 ul/blockquote，文本保持不变', () => {
    const matrix = [
      'a > 0；a < 0；Δ >= 0；x <= 1',
      'x - b；x - 1；b² - 4ac；-b/2a；-4ac',
      '版本 1.2.3',
      'https://example.com/a-b?q=x>0',
      'y = ax² + bx + c，a ≠ 0',
    ];
    for (const text of matrix) {
      const { container } = render(
        <MemoryRouter>
          <MarkdownContent content={text} />
        </MemoryRouter>,
      );
      // 不产生无序列表/引用容器（数学比较不是列表/引用）
      expect(container.querySelectorAll('ul')).toHaveLength(0);
      expect(container.querySelectorAll('blockquote')).toHaveLength(0);
      // 文本逐字保留（无空格化/拆行破坏）
      expect(container.textContent).toBe(text);
      container.remove();
    }
  });

  it('已规范 markdown 幂等（DOM 不变化）', () => {
    const normal = '好，我们开始。\n\n### 第一块\n\n- 项一\n- 项二';
    const { container } = render(
      <MemoryRouter>
        <MarkdownContent content={normal} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll('h4')).toHaveLength(1);
    expect(container.querySelectorAll('ul li')).toHaveLength(2);
  });

  it('fenced code 内紧凑编号不被误拆（保护占位符层）', () => {
    const text =
      '示例代码：\n```\n1. 步骤一 2. 步骤二 3. 步骤三\n```\n以上是完整代码。';
    const { container } = render(
      <MemoryRouter>
        <MarkdownContent content={text} />
      </MemoryRouter>,
    );
    // 代码块存在且内部编号仍在一行（未被拆成列表）
    const code = container.querySelector('code');
    expect(code).toBeTruthy();
    expect(code?.textContent?.includes('1. 步骤一 2. 步骤二')).toBe(true);
    // 代码块外不产生额外列表
    expect(container.querySelectorAll('ul')).toHaveLength(0);
    container.remove();
  });
});
