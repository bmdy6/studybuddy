import { Form, Input, Modal, Select, Typography } from 'antd';
import type { FormInstance } from 'antd';
import { MATERIAL_TYPE_OPTIONS } from '@/shared/constants';

export interface MaterialFormValues {
  name: string;
  type: string;
  knowledge_tags?: string[];
}

interface MaterialUploadModalProps {
  open: boolean;
  file: File | null;
  uploading: boolean;
  form: FormInstance<MaterialFormValues>;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
}

export function MaterialUploadModal({
  open,
  file,
  uploading,
  form,
  onCancel,
  onConfirm,
}: MaterialUploadModalProps) {
  return (
    <Modal
      title="上传素材"
      open={open}
      destroyOnHidden
      rootClassName="sb-material-upload-modal"
      onCancel={onCancel}
      onOk={onConfirm}
      okText="上传到素材库"
      cancelText="取消"
      confirmLoading={uploading}
      okButtonProps={{ disabled: !file }}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {file ? `已选文件：${file.name}` : '请先选择文件'}
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="素材名称"
          rules={[{ required: true, message: '请填素材名称' }]}
        >
          <Input placeholder="如：英语 U5 单词表" />
        </Form.Item>
        <Form.Item name="type" label="类型" rules={[{ required: true }]}>
          <Select options={MATERIAL_TYPE_OPTIONS} />
        </Form.Item>
        <Form.Item name="knowledge_tags" label="知识点标签">
          <Select
            mode="tags"
            placeholder="如：过去时、单词、U5"
            tokenSeparators={[',', '，', ' ']}
            maxTagCount="responsive"
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
// agg-1 materials
