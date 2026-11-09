import { useEffect, useState } from 'react';
import { App, Button, Drawer, Input, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';

import { familyGoalApi } from '@/features/family_goal/api';
import type { FamilyTodayTask } from '@/types';

const { Text } = Typography;
const { TextArea } = Input;

/** 与后端 FAMILY_EVIDENCE_MAX_COUNT 对齐：最多一次交 9 张图。 */
const MAX_EVIDENCE_COUNT = 9;

interface TaskEvidenceDrawerProps {
  open: boolean;
  task: FamilyTodayTask | null;
  onClose: () => void;
  onSubmitted: () => void;
}

/**
 * 完成证据提交：多张图片 + 文字说明，两者至少一项才允许提交。
 * 图片先逐张上传取 content_ref，再一次性提交；不做 AI 判断，只保存与展示。
 */
export default function TaskEvidenceDrawer({
  open,
  task,
  onClose,
  onSubmitted,
}: TaskEvidenceDrawerProps) {
  const { message } = App.useApp();
  const [note, setNote] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setNote('');
      setFiles([]);
    }
  }, [open]);

  useEffect(() => {
    const urls = files.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);

  const canSubmit = (files.length > 0 || note.trim().length > 0) && !submitting;

  const addFiles = (picked: FileList | null) => {
    if (!picked || picked.length === 0) return;
    const next = [...files, ...Array.from(picked)].slice(0, MAX_EVIDENCE_COUNT);
    setFiles(next);
  };

  const handleSubmit = async () => {
    if (!task || !canSubmit) return;
    setSubmitting(true);
    try {
      const refs: string[] = [];
      for (const file of files) {
        const uploaded = await familyGoalApi.uploadEvidence(file);
        refs.push(uploaded.content_ref);
      }
      await familyGoalApi.submitOccurrence(task.occurrence_id, {
        note: note.trim() || null,
        evidence_refs: refs,
      });
      message.success('交上去了，等家长确认');
      onSubmitted();
      onClose();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ?? '提交失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      placement="bottom"
      height="auto"
      title={task ? `交作业 · ${task.title}` : '交作业'}
      onClose={onClose}
      destroyOnClose
      footer={
        <div className="sb-family-task-drawer-footer">
          <Button onClick={onClose} disabled={submitting}>
            再想想
          </Button>
          <Button type="primary" loading={submitting} disabled={!canSubmit} onClick={handleSubmit}>
            提交给家长
          </Button>
        </div>
      }
    >
      <div className="sb-family-task-upload">
        <label className="sb-family-task-upload-button">
          <PlusOutlined /> 加图片
          <input
            type="file"
            accept="image/*"
            multiple
            hidden
            aria-label="选择完成照片"
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = '';
            }}
          />
        </label>
        <Text type="secondary" style={{ fontSize: 12 }}>
          最多 {MAX_EVIDENCE_COUNT} 张（{files.length}/{MAX_EVIDENCE_COUNT}）
        </Text>
      </div>

      {previews.length > 0 && (
        <div className="sb-family-task-previews">
          {previews.map((url, index) => (
            <div className="sb-family-task-preview" key={url}>
              <img src={url} alt={`完成照片 ${index + 1}`} />
              <button
                type="button"
                aria-label={`移除第 ${index + 1} 张照片`}
                onClick={() => setFiles(files.filter((_, i) => i !== index))}
              >
                <DeleteOutlined />
              </button>
            </div>
          ))}
        </div>
      )}

      <TextArea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="写一句做了什么，比如：默写完第 3 单元，错了 2 个"
        autoSize={{ minRows: 3, maxRows: 6 }}
        maxLength={500}
        showCount
      />
      <Text type="secondary" style={{ fontSize: 12 }}>
        图片和文字至少有一项才能提交。
      </Text>
    </Drawer>
  );
}
