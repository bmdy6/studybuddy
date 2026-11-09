import { useState } from 'react';
import {
  Alert,
  Button,
  DatePicker,
  Drawer,
  Form,
  Grid,
  Input,
  InputNumber,
  Space,
  Typography,
} from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';

import { p2Api } from '@/features/p2/api';
import type { StudyPlan } from '@/types';

const { Text } = Typography;

interface ManualStudyPlanDrawerProps {
  open: boolean;
  studentId: number;
  onClose: () => void;
  onCreated: (plan: StudyPlan) => void;
}

interface ManualPlanFormValues {
  title: string;
  description?: string;
  plannedDate: Dayjs;
  items: Array<{ title: string; minutes: number }>;
}

const initialValues: ManualPlanFormValues = {
  title: '',
  plannedDate: dayjs(),
  items: [{ title: '', minutes: 20 }],
};

export default function ManualStudyPlanDrawer({
  open,
  studentId,
  onClose,
  onCreated,
}: ManualStudyPlanDrawerProps) {
  const [form] = Form.useForm<ManualPlanFormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;

  const closeDrawer = () => {
    setError('');
    form.resetFields();
    onClose();
  };

  const submit = async (values: ManualPlanFormValues) => {
    setSubmitting(true);
    setError('');
    try {
      const plan = await p2Api.createStudyPlan(studentId, {
        title: values.title.trim(),
        focus: null,
        description: values.description?.trim() || null,
        planned_date: values.plannedDate.format('YYYY-MM-DD'),
        items: values.items.map((item) => ({
          title: item.title.trim(),
          target: null,
          minutes: item.minutes,
          related_tags: [],
        })),
      });
      onCreated(plan);
      form.resetFields();
      onClose();
    } catch {
      setError('创建计划失败，请再试一次');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      placement={mobile ? 'bottom' : 'right'}
      width={mobile ? undefined : 420}
      height={mobile ? 'min(92dvh, 720px)' : undefined}
      title={
        <Space direction="vertical" size={0}>
          <span>添加今天计划</span>
          <Text type="secondary" className="sb-manual-plan-subtitle">
            安排最重要的 1-3 项
          </Text>
        </Space>
      }
      rootClassName="sb-manual-plan-drawer"
      onClose={closeDrawer}
      footer={
        <div className="sb-manual-plan-footer">
          <Button onClick={closeDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={() => form.submit()}>
            保存计划
          </Button>
        </div>
      }
    >
      {error && <Alert type="error" showIcon message={error} className="sb-manual-plan-error" />}
      <Form<ManualPlanFormValues>
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={submit}
        requiredMark={false}
      >
        <Form.Item
          name="title"
          label="计划名称"
          rules={[{ required: true, whitespace: true, message: '请输入计划名称' }]}
        >
          <Input placeholder="例如：英语错题复习" maxLength={128} />
        </Form.Item>
        <Form.Item name="description" label="计划说明（可选）">
          <Input.TextArea
            placeholder="例如：参考了最近英语错题，重点补时态；弟弟要求先做薄弱项"
            maxLength={500}
            autoSize={{ minRows: 2, maxRows: 4 }}
          />
        </Form.Item>
        <Form.Item
          name="plannedDate"
          label="计划日期"
          rules={[{ required: true, message: '请选择计划日期' }]}
        >
          <DatePicker allowClear={false} style={{ width: '100%' }} />
        </Form.Item>
        <Form.List name="items">
          {(fields, { add, remove }) => (
            <div className="sb-manual-plan-items">
              {fields.map((field, index) => {
                const { key, ...fieldProps } = field;
                return (
                  <div className="sb-manual-plan-item" key={key}>
                    <Form.Item
                      {...fieldProps}
                      name={[field.name, 'title']}
                      label={`任务 ${index + 1}`}
                      rules={[{ required: true, whitespace: true, message: '请输入任务名称' }]}
                    >
                      <Input placeholder="要完成什么" maxLength={160} />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, 'minutes']}
                      label={`预计分钟 ${index + 1}`}
                      rules={[{ required: true, message: '请输入预计时间' }]}
                    >
                      <InputNumber min={5} max={60} step={5} />
                    </Form.Item>
                    {fields.length > 1 && (
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={`删除任务 ${index + 1}`}
                        onClick={() => remove(field.name)}
                      />
                    )}
                  </div>
                );
              })}
              {fields.length < 3 && (
                <Button
                  type="text"
                  icon={<PlusOutlined />}
                  aria-label="再加一项"
                  onClick={() => add({ title: '', minutes: 20 })}
                >
                  再加一项
                </Button>
              )}
            </div>
          )}
        </Form.List>
      </Form>
    </Drawer>
  );
}
