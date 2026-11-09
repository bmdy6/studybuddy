import { Alert, DatePicker, Form, Input, Modal, Typography } from 'antd';
import type { FormInstance } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';

export interface BatchUploadFormValues {
  exam_name: string;
  exam_date: Dayjs;
}

interface BatchUploadModalProps {
  open: boolean;
  files: File[];
  uploading: boolean;
  error: string | null;
  form: FormInstance<BatchUploadFormValues>;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
}

export function BatchUploadModal({
  open,
  files,
  uploading,
  error,
  form,
  onCancel,
  onConfirm,
}: BatchUploadModalProps) {
  return (
    <Modal
      title="拍题批改"
      open={open}
      destroyOnHidden
      onCancel={onCancel}
      onOk={onConfirm}
      okText={`上传 ${files.length} 张并识别`}
      cancelText="取消"
      confirmLoading={uploading}
      okButtonProps={{ disabled: files.length === 0 }}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        已选 {files.length} 张题目照片，确认后先识别成 Markdown，核对无误后再逐题批改。
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ exam_name: '', exam_date: dayjs() }}
      >
        <Form.Item
          name="exam_name"
          label="任务名称"
          rules={[{ required: true, message: '请填任务名称' }]}
        >
          <Input placeholder="如：英语 U5 作业批改" />
        </Form.Item>
        <Form.Item
          name="exam_date"
          label="拍题日期"
          rules={[{ required: true, message: '请选日期' }]}
        >
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
