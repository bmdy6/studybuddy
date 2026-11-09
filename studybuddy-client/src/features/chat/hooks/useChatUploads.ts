import { useCallback, useRef, useState } from 'react';
import { Form } from 'antd';
import dayjs from 'dayjs';
import { examBatchApi } from '@/features/exams/examBatch';
import { materialApi } from '@/features/materials/api';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import type { ErrorReportInfo } from '@/features/chat/store';
import { getRequestErrorMessage } from '@/shared/api/client';
import {
  detectMaterialType,
  defaultMaterialName,
  normalizeMaterialTags,
} from '@/shared/utils/material';
import type { BatchUploadFormValues } from '@/features/chat/components/BatchUploadModal';
import type { MaterialFormValues } from '@/features/chat/components/MaterialUploadModal';

interface MessageApi {
  success: (content: string) => void;
  error: (content: string) => void;
}

interface UseChatUploadsOptions {
  sessionId: number | null;
  resolveStudentId: () => number | null;
  onSend: (content: string) => Promise<void>;
  onError: (report: Omit<ErrorReportInfo, 'id'>) => void;
  message: MessageApi;
}

export function useChatUploads({
  sessionId,
  resolveStudentId,
  onSend,
  onError,
  message,
}: UseChatUploadsOptions) {
  const batchFileInputRef = useRef<HTMLInputElement>(null);
  const [pendingPhotos, setPendingPhotos] = useState<File[]>([]);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchUploading, setBatchUploading] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchForm] = Form.useForm<BatchUploadFormValues>();
  const [pendingMaterial, setPendingMaterial] = useState<{
    file: File;
    name: string;
    type: string;
  } | null>(null);
  const [materialModalOpen, setMaterialModalOpen] = useState(false);
  const [materialUploading, setMaterialUploading] = useState(false);
  const [materialForm] = Form.useForm<MaterialFormValues>();

  const openBatchModal = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      setPendingPhotos(files);
      setBatchError(null);
      setMaterialModalOpen(false);
      batchForm.setFieldsValue({
        exam_name: defaultMaterialName(files[0].name),
        exam_date: dayjs(),
      });
      setBatchModalOpen(true);
    },
    [batchForm],
  );

  const openMaterialModal = useCallback(
    (file: File) => {
      const name = defaultMaterialName(file.name);
      const type = detectMaterialType(file.name);
      setBatchModalOpen(false);
      setPendingPhotos([]);
      setPendingMaterial({ file, name, type });
      materialForm.setFieldsValue({ name, type, knowledge_tags: [] });
      setMaterialModalOpen(true);
    },
    [materialForm],
  );

  const cancelBatchModal = useCallback(() => {
    setBatchModalOpen(false);
    setPendingPhotos([]);
    setBatchError(null);
  }, []);

  const cancelMaterialModal = useCallback(() => {
    setMaterialModalOpen(false);
    setPendingMaterial(null);
    materialForm.resetFields();
  }, [materialForm]);

  const confirmBatchUpload = useCallback(async () => {
    const studentId = resolveStudentId() ?? getActiveStudentId(useAuthStore.getState());
    setBatchError(null);
    if (!studentId) {
      message.error('未选定学生，无法拍题批改');
      return;
    }
    const files = pendingPhotos;
    if (files.length === 0) {
      message.error('请先选择题目照片');
      return;
    }
    const values = await batchForm.validateFields().catch(() => null);
    if (!values) return;

    setBatchUploading(true);
    let createdBatchId: number | null = null;
    let cleanedEmptyBatch = false;
    try {
      const batch = await examBatchApi.createBatch({
        student_id: studentId,
        subject: 'auto',
        exam_name: values.exam_name,
        exam_date: values.exam_date.format('YYYY-MM-DD'),
      });
      createdBatchId = batch.id;
      await examBatchApi.uploadPhotos(batch.id, files);
      createdBatchId = null;
      setBatchModalOpen(false);
      setPendingPhotos([]);
      batchForm.resetFields();
      await onSend(
        `[拍题批改] 已上传 ${files.length} 张照片到批次 #${batch.id}（${values.exam_name}），请先把照片识别成 Markdown，保留题干、选项和我的作答；让我确认识别稿后，再逐题批改并给正确答案、错因和知识点。如果识别错了，可以直接告诉我第几题哪里错了，我会按你修正后的作答再批改。`,
      );
    } catch (error) {
      if (createdBatchId) {
        cleanedEmptyBatch = await examBatchApi
          .deleteEmptyBatch(createdBatchId)
          .then(() => true)
          .catch(() => false);
      }
      const cleanupText = cleanedEmptyBatch
        ? '空批次已自动清理，可重新选择照片上传'
        : '如已上传部分照片，批次会保留以便重试';
      const errorMessage = `上传失败：${getRequestErrorMessage(error)}，${cleanupText}`;
      setBatchError(errorMessage);
      onError({
        context: 'chat:homework-upload',
        message: errorMessage,
        details: `files=${files
          .map((file) => `${file.name}(${file.type || 'unknown'},${file.size})`)
          .join(', ')}`,
        sessionId,
        studentId,
      });
      message.error(errorMessage);
    } finally {
      setBatchUploading(false);
    }
  }, [batchForm, message, onError, onSend, pendingPhotos, resolveStudentId, sessionId]);

  const confirmMaterialUpload = useCallback(async () => {
    if (!pendingMaterial) return;
    const values = await materialForm.validateFields().catch(() => null);
    if (!values) return;
    const knowledgeTags = normalizeMaterialTags(values.knowledge_tags);
    setMaterialUploading(true);
    try {
      const result = await materialApi.upload(
        pendingMaterial.file,
        values.name,
        values.type,
        knowledgeTags,
      );
      setMaterialModalOpen(false);
      setPendingMaterial(null);
      materialForm.resetFields();
      message.success(`素材「${values.name}」已存到素材库`);
      const tagText = knowledgeTags.length > 0 ? `，标签：${knowledgeTags.join('、')}` : '';
      await onSend(
        `我上传了一份素材「${values.name}」（类型：${values.type}${tagText}，material_id=${result.material_id}），已经存到素材库了。你可以用 read_material 工具看它的内容，然后帮我整理笔记、推荐学习视频，或讲解相关知识点。`,
      );
    } catch (error) {
      const errorMessage = `素材上传失败：${getRequestErrorMessage(error)}`;
      onError({
        context: 'chat:material-upload',
        message: errorMessage,
        details: `file=${pendingMaterial.file.name}(${pendingMaterial.file.type || 'unknown'},${pendingMaterial.file.size})`,
        sessionId,
        studentId: resolveStudentId(),
      });
      message.error(errorMessage);
    } finally {
      setMaterialUploading(false);
    }
  }, [materialForm, message, onError, onSend, pendingMaterial, resolveStudentId, sessionId]);

  return {
    batchFileInputRef,
    pendingPhotos,
    batchModalOpen,
    batchUploading,
    batchError,
    batchForm,
    pendingMaterial,
    materialModalOpen,
    materialUploading,
    materialForm,
    openBatchModal,
    openMaterialModal,
    cancelBatchModal,
    cancelMaterialModal,
    confirmBatchUpload,
    confirmMaterialUpload,
  };
}
