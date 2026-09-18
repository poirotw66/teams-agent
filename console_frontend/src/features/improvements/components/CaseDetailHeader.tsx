import React from 'react';
import { Breadcrumb, Button, Space, Typography } from 'antd';
import {
  ArrowLeftOutlined,
  FileAddOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  AuditOutlined,
  SyncOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { StatusTag } from '../../../shared/ui/StatusTag';

const { Title, Text } = Typography;

export type CaseDetailHeaderProps = {
  caseId: string;
  title: string;
  status: string;
  etag: number;
  ownerUnitId?: string;
  submitting: boolean;
  onBack: () => void;
  onTransition: (status: string, reason: string) => void;
  onOpenDraftModal: () => void;
  onOpenResolveModal: () => void;
  onOpenCloseModal: () => void;
  onRefreshObservation: () => void;
};

export const CaseDetailHeader: React.FC<CaseDetailHeaderProps> = ({
  caseId,
  title,
  status,
  etag,
  ownerUnitId,
  submitting,
  onBack,
  onTransition,
  onOpenDraftModal,
  onOpenResolveModal,
  onOpenCloseModal,
  onRefreshObservation,
}) => {
  return (
    <>
      <Breadcrumb
        items={[
          {
            title: <Link to="/console-v2/work">我的工作</Link>,
          },
          {
            title: '品質案件改善流程',
          },
          {
            title: caseId,
          },
        ]}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space size="middle" align="center">
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
            返回案件列表
          </Button>
          <div>
            <Space align="center" size="middle">
              <Title level={3} style={{ margin: 0 }}>
                {title}
              </Title>
              <StatusTag status={status} />
            </Space>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              案件編號: {caseId} · 版本 ETag: {etag} · 權責單位: {ownerUnitId}
            </Text>
          </div>
        </Space>

        <Space size="small">
          {status === 'NEW' && (
            <Button
              type="primary"
              loading={submitting}
              onClick={() => onTransition('TRIAGED', '完成初步分流與方向確認')}
            >
              確認分流與方向 (Triage)
            </Button>
          )}

          {status === 'TRIAGED' && (
            <Button
              type="primary"
              loading={submitting}
              onClick={() => onTransition('IN_PROGRESS', '展開內容修正作業')}
            >
              進入修正階段
            </Button>
          )}

          {(status === 'TRIAGED' || status === 'IN_PROGRESS') && (
            <Button type="primary" icon={<FileAddOutlined />} onClick={onOpenDraftModal}>
              建立文件草稿
            </Button>
          )}

          {status === 'IN_PROGRESS' && (
            <Button
              type="default"
              icon={<AuditOutlined />}
              loading={submitting}
              onClick={() => onTransition('WAITING_REVIEW', '草稿完成，送交審核與驗證')}
            >
              提交審核驗證
            </Button>
          )}

          {status === 'WAITING_REVIEW' && (
            <Button
              type="primary"
              icon={<EyeOutlined />}
              loading={submitting}
              onClick={() => onTransition('OBSERVING', '審核通過，進入線上觀察期')}
            >
              開始上線觀察
            </Button>
          )}

          {status === 'OBSERVING' && (
            <>
              <Button icon={<SyncOutlined />} loading={submitting} onClick={onRefreshObservation}>
                重新整理指標
              </Button>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={onOpenResolveModal}
              >
                驗收結案
              </Button>
            </>
          )}

          {status !== 'RESOLVED' && status !== 'WONT_FIX' && status !== 'DUPLICATE' && (
            <Button danger icon={<CloseCircleOutlined />} onClick={onOpenCloseModal}>
              終止／不予修復
            </Button>
          )}
        </Space>
      </div>
    </>
  );
};
