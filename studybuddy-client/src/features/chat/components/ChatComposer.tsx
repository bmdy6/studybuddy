import { useState, type RefObject } from 'react';
import { Button, Input, Popover, Upload } from 'antd';
import type { InputRef } from 'antd';
import { CameraOutlined, FileAddOutlined, SendOutlined } from '@ant-design/icons';
import type {
  NoteDraftState,
  PhotoAnswerReviewItem,
  PhotoAnswerReviewState,
} from '@/types';
import type { ErrorReportInfo } from '@/features/chat/store';
import { ErrorReportCard } from '@/features/chat/components/ErrorReportCard';
import { useAuthStore } from '@/features/auth/store';
import { NoteDraftPanel } from '@/features/chat/components/NoteDraftPanel';
import { PlanDraftPanel } from '@/features/chat/components/PlanDraftPanel';
import { PlanCarryOverPanel } from '@/features/chat/components/PlanCarryOverPanel';
import { HistoricalPlanDraftNotice } from '@/features/chat/components/HistoricalPlanDraftNotice';
import { useChatStore } from '@/features/chat/store';
import { PhotoAnswerReviewPanel } from '@/features/chat/components/PhotoAnswerReviewPanel';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

interface ChatComposerProps {
  input: string;
  inputRef: RefObject<InputRef>;
  batchFileInputRef: RefObject<HTMLInputElement>;
  sessionId: number | null;
  loading: boolean;
  batchUploading: boolean;
  materialUploading: boolean;
  pendingAnswerReview: PhotoAnswerReviewState | null;
  answerReviewConfirming: boolean;
  pendingNoteDraft: NoteDraftState | null;
  noteDraftConfirming: boolean;
  latestErrorReport: ErrorReportInfo | null;
  onInputChange: (value: string) => void;
  onSend: (content?: string) => Promise<void>;
  onOpenBatchUpload: (files: File[]) => void;
  onOpenMaterialUpload: (file: File) => void;
  onAnswerReviewConfirm: (items: PhotoAnswerReviewItem[]) => Promise<void>;
  onNoteDraftConfirm: (edits: Partial<NoteDraftState>) => Promise<void>;
  onCopyError: (report: ErrorReportInfo) => Promise<void>;
  onCloseError: () => void;
}

export function ChatComposer({
  input,
  inputRef,
  batchFileInputRef,
  sessionId,
  loading,
  batchUploading,
  materialUploading,
  pendingAnswerReview,
  answerReviewConfirming,
  pendingNoteDraft,
  noteDraftConfirming,
  latestErrorReport,
  onInputChange,
  onSend,
  onOpenBatchUpload,
  onOpenMaterialUpload,
  onAnswerReviewConfirm,
  onNoteDraftConfirm,
  onCopyError,
  onCloseError,
}: ChatComposerProps) {
  const [uploadMenuOpen, setUploadMenuOpen] = useState(false);
  const mode = useAuthStore((s) => s.mode);
  const pendingPlanDraft = useChatStore((s) => s.pendingPlanDraft);
  const planDraftConfirming = useChatStore((s) => s.planDraftConfirming);
  const confirmPlanDraftAction = useChatStore((s) => s.confirmPlanDraft);
  const pendingPlanCarryOver = useChatStore((s) => s.pendingPlanCarryOver);
  const planCarryOverConfirming = useChatStore((s) => s.planCarryOverConfirming);
  const planCarryOverError = useChatStore((s) => s.planCarryOverError);
  const carryOverStudyPlan = useChatStore((s) => s.carryOverStudyPlan);

  const cameraBtnProps = {
    icon: <CameraOutlined />,
    disabled: !sessionId || loading,
    size: 'large' as const,
    title: '上传：错题或素材',
    style: { borderRadius: 12, minWidth: 48 },
  };

  const uploadMenu = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
      <input
        ref={batchFileInputRef}
        accept="image/*"
        multiple
        type="file"
        style={{ display: 'none' }}
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          setUploadMenuOpen(false);
          onOpenBatchUpload(files);
          event.currentTarget.value = '';
        }}
      />
      <Button
        type="text"
        icon={<CameraOutlined />}
        disabled={!sessionId || loading || batchUploading}
        style={{ textAlign: 'left', width: '100%' }}
        onClick={() => {
          setUploadMenuOpen(false);
          batchFileInputRef.current?.click();
        }}
      >
        拍题批改
      </Button>
      <Upload
        showUploadList={false}
        beforeUpload={(file) => {
          setUploadMenuOpen(false);
          onOpenMaterialUpload(file);
          return false;
        }}
        disabled={!sessionId || loading || materialUploading}
      >
        <Button
          type="text"
          icon={<FileAddOutlined />}
          disabled={!sessionId || loading || materialUploading}
          style={{ textAlign: 'left', width: '100%' }}
        >
          上传素材（单词表等）
        </Button>
      </Upload>
    </div>
  );

  return (
    <div
      className="sb-chat-composer"
      style={{
        borderTop: '1px solid var(--sb-color-border-warm)',
        padding: '16px',
        background: 'var(--sb-color-white)',
      }}
    >
      {pendingAnswerReview ? (
        <PhotoAnswerReviewPanel
          state={pendingAnswerReview}
          confirming={answerReviewConfirming}
          onConfirm={onAnswerReviewConfirm}
        />
      ) : null}
      {pendingNoteDraft ? (
        <NoteDraftPanel
          state={pendingNoteDraft}
          confirming={noteDraftConfirming}
          onConfirm={onNoteDraftConfirm}
        />
      ) : null}
      {pendingPlanCarryOver ? (
        <PlanCarryOverPanel
          state={pendingPlanCarryOver}
          confirmingPlanId={planCarryOverConfirming}
          error={planCarryOverError}
          onCarryOver={(planId) => {
            void carryOverStudyPlan(planId);
          }}
          onReplan={() => {
            void onSend('我想重新制定今天计划');
          }}
        />
      ) : null}
      {pendingPlanDraft ? (
        <PlanDraftPanel
          state={pendingPlanDraft}
          confirming={planDraftConfirming}
          onConfirm={confirmPlanDraftAction}
        />
      ) : null}
      <HistoricalPlanDraftNotice />
      {latestErrorReport ? (
        <ErrorReportCard
          report={latestErrorReport}
          onCopy={() => {
            void onCopyError(latestErrorReport);
          }}
          onClose={onCloseError}
        />
      ) : null}
      <form
        className="sb-chat-composer-form"
        style={{ maxWidth: READING_COLUMN_MAX, margin: '0 auto', display: 'flex', gap: 12 }}
        onSubmit={(event) => {
          event.preventDefault();
          void onSend();
        }}
      >
        {uploadMenuOpen ? (
          <Popover open onOpenChange={setUploadMenuOpen} placement="topLeft" content={uploadMenu}>
            <Button {...cameraBtnProps} />
          </Popover>
        ) : (
          <Button {...cameraBtnProps} onClick={() => setUploadMenuOpen(true)} />
        )}
        <Input
          ref={inputRef}
          data-testid="chat-message-input"
          aria-label="输入消息"
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          onInput={(event) => onInputChange((event.target as HTMLInputElement).value)}
          onPaste={(event) => {
            const items = Array.from(event.clipboardData?.items ?? []);
            const filesFromItems = items
              .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
              .map((item) => item.getAsFile())
              .filter((file): file is File => Boolean(file));
            const filesFromList = Array.from(event.clipboardData?.files ?? []).filter((file) =>
              file.type.startsWith('image/'),
            );
            const files = filesFromItems.length > 0 ? filesFromItems : filesFromList;
            if (files.length === 0) return;
            event.preventDefault();
            onOpenBatchUpload(files);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void onSend();
            }
          }}
          placeholder={sessionId ? (mode === 'hobby' ? '说说想学什么…' : '输入消息…') : '正在连接…'}
          disabled={!sessionId || loading}
          size="large"
          style={{ borderRadius: 12 }}
        />
        <Button
          type="primary"
          htmlType="submit"
          data-testid="chat-send-button"
          aria-label="发送"
          icon={<SendOutlined />}
          onMouseDown={(event) => {
            event.preventDefault();
            void onSend();
          }}
          disabled={!input.trim() || !sessionId || loading}
          size="large"
          style={{ borderRadius: 12, minWidth: 48 }}
        />
      </form>
    </div>
  );
}
