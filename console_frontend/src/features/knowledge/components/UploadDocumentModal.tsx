import React, { useState, useEffect } from 'react';
import {
  Modal,
  Form,
  Input,
  Select,
  Upload,
  Button,
  Space,
  Typography,
  message,
  Steps,
  Alert,
} from 'antd';
import {
  InboxOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { IngestionStage, ManualDocumentItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';

const { Text } = Typography;

interface UploadDocumentModalProps {
  open: boolean;
  initialFile: File | null;
  onClose: () => void;
  onSuccess: (doc: ManualDocumentItem) => void;
}

export const UploadDocumentModal: React.FC<UploadDocumentModalProps> = ({
  open,
  initialFile,
  onClose,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const [uploadedFile, setUploadedFile] = useState<File | null>(initialFile);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [stage, setStage] = useState<IngestionStage | null>(null);

  useEffect(() => {
    if (open) {
      setStage(null);
      if (initialFile) {
        setUploadedFile(initialFile);
        const nameWithoutExt = initialFile.name.replace(/\.[^/.]+$/, '');
        form.setFieldsValue({
          fileName: initialFile.name,
          title: nameWithoutExt,
          version: 'v2.0',
          category: '網路通訊',
          profile: 'AUTO',
        });
      } else {
        setUploadedFile(null);
        form.resetFields();
        form.setFieldsValue({
          version: 'v1.0',
          category: '網路通訊',
          profile: 'AUTO',
        });
      }
    }
  }, [open, initialFile, form]);

  const getFileIcon = (fileName: string) => {
    if (fileName.endsWith('.pdf')) return <FilePdfOutlined style={{ color: '#C4314B', fontSize: 18 }} />;
    if (fileName.endsWith('.docx') || fileName.endsWith('.doc'))
      return <FileWordOutlined style={{ color: '#185ABD', fontSize: 18 }} />;
    return <FileTextOutlined style={{ color: '#107C41', fontSize: 18 }} />;
  };

  const handleConfirmUpload = async () => {
    try {
      const values = await form.validateFields();
      if (!uploadedFile) {
        message.error('請先選擇欲上傳之手冊檔案！');
        return;
      }
      setIsUploading(true);
      try {
        const newDoc = await workbenchStore.uploadDocument({
          file: uploadedFile,
          title: values.title,
          category: values.category,
          version: values.version,
          profile: values.profile,
          onProgress: setStage,
        });

        message.success(
          `手冊《${newDoc.title}》已建立待審草稿，共產生 ${newDoc.chunk_count} 個候選段落。通過品質檢查與審核後才會發布。`
        );
        if (newDoc.ingestion_warnings?.length) {
          message.warning(newDoc.ingestion_warnings.join('；'), 8);
        }
        onSuccess(newDoc);
        onClose();
      } catch (err: any) {
        const detail = err?.message || '檔案解析失敗，請確認檔案格式是否正確。';
        message.error(`手冊上傳處理失敗：${detail}`);
      } finally {
        setIsUploading(false);
      }
    } catch {
      // Form validation error
    }
  };

  return (
    <Modal
      title="上傳操作手冊並建立待審草稿"
      open={open}
      onOk={handleConfirmUpload}
      onCancel={() => {
        if (!isUploading) {
          onClose();
        }
      }}
      okText={isUploading ? '正在建立可審查草稿...' : '上傳並建立草稿'}
      cancelText="取消"
      confirmLoading={isUploading}
      okButtonProps={{
        loading: isUploading,
        style: { backgroundColor: '#5b5fc7', borderColor: '#5b5fc7' },
      }}
      maskClosable={!isUploading}
      closable={!isUploading}
    >
      {isUploading && (
        <div style={{ marginBottom: 20 }}>
          <Steps
            size="small"
            current={stage === 'CHUNK_REVIEW' ? 3 : stage === 'PARSING' ? 2 : stage === 'SCANNING' ? 1 : 0}
            items={[
              { title: '上傳' },
              { title: '掃描' },
              { title: '解析' },
              { title: '切分審查' },
            ]}
          />
        </div>
      )}
      <Alert
        type="info"
        showIcon
        message="上傳不會直接影響正式知識庫"
        description="文件會先進入解析、段落品質檢查與發布審核；只有核准的 immutable release 才會同步到 Hybrid 與 Gemini File Search。"
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical">
        {uploadedFile ? (
          <div
            style={{
              marginBottom: 16,
              padding: '12px 14px',
              backgroundColor: '#F7F7FA',
              border: '1px solid #D2D3EC',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Space>
              {getFileIcon(uploadedFile.name)}
              <div>
                <Text strong style={{ fontSize: '13.5px' }}>
                  {uploadedFile.name}
                </Text>
                <div style={{ fontSize: '12px', color: '#616161' }}>
                  大小：{(uploadedFile.size / 1024 / 1024).toFixed(2)} MB
                </div>
              </div>
            </Space>
            <Upload
              multiple={false}
              showUploadList={false}
              beforeUpload={(file) => {
                setUploadedFile(file);
                const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '');
                form.setFieldsValue({
                  fileName: file.name,
                  title: nameWithoutExt,
                });
                return false;
              }}
            >
              <Button size="small" style={{ borderColor: '#5B5FC7', color: '#5B5FC7' }}>
                更換檔案
              </Button>
            </Upload>
          </div>
        ) : (
          <Form.Item
            label={<Text strong>選擇欲上傳之手冊檔案 (.pdf, .docx, .md)</Text>}
            required
          >
            <Upload.Dragger
              multiple={false}
              showUploadList={false}
              beforeUpload={(file) => {
                setUploadedFile(file);
                const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '');
                form.setFieldsValue({
                  fileName: file.name,
                  title: nameWithoutExt,
                });
                return false;
              }}
              style={{ padding: '16px 0', border: '1px dashed #5B5FC7' }}
            >
              <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
                <InboxOutlined style={{ color: '#5B5FC7', fontSize: 28 }} />
              </p>
              <p className="ant-upload-text" style={{ fontSize: '13px', fontWeight: 600 }}>
                點擊或拖曳檔案至此處選擇檔案
              </p>
              <p className="ant-upload-hint" style={{ fontSize: '12px', color: '#616161' }}>
                支援文字型 PDF、Word (.docx) 或 Markdown (.md)
              </p>
            </Upload.Dragger>
          </Form.Item>
        )}

        <Form.Item
          name="title"
          label={<Text strong>手冊中文名稱</Text>}
          rules={[{ required: true, message: '請輸入手冊名稱' }]}
        >
          <Input placeholder="例：2026 全公司差勤與請假系統操作手冊" />
        </Form.Item>

        <Space style={{ width: '100%' }} size="middle">
          <Form.Item
            name="version"
            label={<Text strong>版本號</Text>}
            rules={[{ required: true }]}
            style={{ width: 140 }}
          >
            <Input placeholder="例: v2.0" />
          </Form.Item>

          <Form.Item
            name="category"
            label={<Text strong>業務分類</Text>}
            rules={[{ required: true }]}
            style={{ width: 260 }}
          >
            <Select
              options={[
                { label: '網路通訊 (VPN / Wi-Fi)', value: '網路通訊' },
                { label: '帳號安全 (AD / MFA / 密碼)', value: '帳號安全' },
                { label: '業務交易系統 (大州 / 報表)', value: '業務交易系統' },
                { label: '通訊協作 (Teams / Webex)', value: '通訊協作' },
                { label: '電子郵件 (Outlook)', value: '電子郵件' },
                { label: 'IT服務指引 (指引 / 報修)', value: 'IT服務指引' },
                { label: '辦公系統 (入口網 / 差勤)', value: '辦公系統' },
              ]}
            />
          </Form.Item>
        </Space>

        <Form.Item
          name="profile"
          label={<Text strong>文件切分類型</Text>}
          tooltip="自動判斷會依頁面密度選擇簡報或手冊規則，您可在段落審查時重新產生。"
        >
          <Select
            options={[
              { label: '自動判斷（建議）', value: 'AUTO' },
              { label: '簡報／投影片', value: 'SLIDE_DECK' },
              { label: '操作手冊', value: 'MANUAL' },
              { label: '政策／規章', value: 'POLICY' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};
