import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConfirmCard } from '@/shared/components/ConfirmCard';

describe('ConfirmCard', () => {
  it('默认「待确认」标签走自定义 token 样式（sb-confirm-tag），不依赖 antd warning 衍生色', () => {
    render(
      <ConfirmCard title="测试计划" confirmLabel="确认并创建" onConfirm={() => {}}>
        <div>内容</div>
      </ConfirmCard>,
    );
    const tag = screen.getByText('待确认').closest('.ant-tag');
    expect(tag).not.toBeNull();
    // P2 修复：默认 warning 态用自定义 class（浅橙底深橙字），且不再传 antd color 触发失效的衍生色
    expect(tag?.className).toContain('sb-confirm-tag');
    expect(tag?.getAttribute('color')).toBeNull();
  });

  it('传非默认 tagColor 时保持 antd 原生行为', () => {
    render(
      <ConfirmCard title="测试" tagText="已完成" tagColor="success" confirmLabel="确定" onConfirm={() => {}}>
        <div>内容</div>
      </ConfirmCard>,
    );
    const tag = screen.getByText('已完成').closest('.ant-tag');
    // 非默认色不套自定义 class（保持 antd 原生渲染）
    expect(tag?.className).not.toContain('sb-confirm-tag');
  });
});
