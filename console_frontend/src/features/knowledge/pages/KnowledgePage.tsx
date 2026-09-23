import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Row, Col, Typography, Tabs } from 'antd';
import {
  CloudOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { useGetIdentity } from '@refinedev/core';
import { ManualDocsManager } from '../components/ManualDocsManager';
import { FaqManager } from '../components/FaqManager';
import { KnowledgeGapsManager } from '../components/KnowledgeGapsManager';
import { PlaygroundSimulator } from '../components/PlaygroundSimulator';
import { CloudFormalMirrorDocs } from '../components/CloudFormalMirrorDocs';
import { KnowledgeWorkspaceBanner } from '../components/KnowledgeWorkspaceBanner';
import { KnowledgeSyncLagBanner } from '../components/KnowledgeSyncLagBanner';
import { FormalPublishProgressBanner } from '../components/FormalPublishProgressBanner';
import { QuickFaqDrawer, QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { WorkbenchLoadErrorBanner } from '../../../shared/ui/WorkbenchLoadErrorBanner';
import {
  ManualDocumentItem,
  FaqItem,
  KnowledgeGapItem,
} from '../../../shared/api/types';
import {
  defaultKnowledgePageTab,
  isCloudConsoleSurface,
} from '../lib/consoleSurface';

const { Title, Text } = Typography;

type KnowledgeIdentity = {
  knowledgeWorkspaceMode?: string;
  knowledgeInProcess?: boolean;
  consoleSurface?: string;
};

export const KnowledgePage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const categoryParam = searchParams.get('category');
  const { data: identity } = useGetIdentity<KnowledgeIdentity>();
  const isCloudConsole = isCloudConsoleSurface(identity);

  const [activeTab, setActiveTab] = useState<string>(() =>
    defaultKnowledgePageTab(identity),
  );
  const [documents, setDocuments] = useState<ManualDocumentItem[]>(workbenchStore.getDocuments());
  const [faqs, setFaqs] = useState<FaqItem[]>(workbenchStore.getFaqs());
  const [gaps, setGaps] = useState<KnowledgeGapItem[]>(workbenchStore.getKnowledgeGaps());

  const [playgroundQuery, setPlaygroundQuery] = useState<string>('');
  const [quickFaqOpen, setQuickFaqOpen] = useState<boolean>(false);
  const [quickFaqData, setQuickFaqData] = useState<QuickFaqInitialData | null>(null);
  const [hasUserChosenTab, setHasUserChosenTab] = useState(false);

  useEffect(() => {
    if (!hasUserChosenTab) {
      setActiveTab(defaultKnowledgePageTab(identity));
    }
  }, [hasUserChosenTab, identity]);

  useEffect(() => {
    void workbenchStore.ensureDomains(['documents', 'faqs', 'overview']);
    const unsubscribe = workbenchStore.subscribe(() => {
      setDocuments(workbenchStore.getDocuments());
      setFaqs(workbenchStore.getFaqs());
      setGaps(workbenchStore.getKnowledgeGaps());
    });
    return unsubscribe;
  }, []);

  const handleTestQuery = (query: string) => {
    setPlaygroundQuery(query);
  };

  const handleOpenQuickFaq = (data?: QuickFaqInitialData) => {
    setQuickFaqData(data || null);
    setQuickFaqOpen(true);
  };

  const mirrorTabLabel = isCloudConsole ? '正式 Agent 目前載入' : '雲端正式鏡像';
  const docsTabLabel = isCloudConsole
    ? `知識文件 (${documents.length})`
    : `本機測試工作區 (${documents.length})`;

  const mirrorTab = {
    key: 'cloud-mirror',
    label: (
      <span>
        <CloudOutlined style={{ marginRight: 6 }} />
        {mirrorTabLabel}
      </span>
    ),
    children: (
      <CloudFormalMirrorDocs
        isCloudConsole={isCloudConsole}
        onTestQuery={handleTestQuery}
      />
    ),
  };
  const docsTab = {
    key: 'docs',
    label: (
      <span>
        <FileTextOutlined style={{ marginRight: 6 }} />
        {docsTabLabel}
      </span>
    ),
    children: (
      <ManualDocsManager
        documents={documents}
        onTestQuery={handleTestQuery}
        selectedCategory={categoryParam}
      />
    ),
  };

  const tabItems = [
    ...(isCloudConsole ? [docsTab, mirrorTab] : [mirrorTab, docsTab]),
    {
      key: 'faqs',
      label: (
        <span>
          <ThunderboltOutlined style={{ marginRight: 6, color: '#5B5FC7' }} />
          FAQ 標準問答 ({faqs.length})
        </span>
      ),
      children: (
        <FaqManager
          faqs={faqs}
          onOpenQuickFaq={handleOpenQuickFaq}
          onTestQuery={handleTestQuery}
        />
      ),
    },
    {
      key: 'gaps',
      label: (
        <span>
          <QuestionCircleOutlined style={{ marginRight: 6, color: '#B78800' }} />
          待補知識缺口 ({gaps.length})
        </span>
      ),
      children: (
        <KnowledgeGapsManager
          gaps={gaps}
          onOpenQuickFaq={handleOpenQuickFaq}
          onTestQuery={handleTestQuery}
        />
      ),
    },
  ];

  const headerHint = isCloudConsole
    ? '此 Console 管理的是雲端正式知識。新增或刪除後要發布新 release，正式對話才會換版。「正式 Agent 目前載入」是唯讀狀態；請在「知識文件」上傳、刪除、送審與發布。'
    : '「雲端正式鏡像」才是與雲端 active 同一份資料。本機測試工作區仍是獨立 FILE sandbox，上傳不會回寫雲端。右側試問讀的是本機 sandbox 關鍵字，不是 Agent GCS。';

  return (
    <div>
      <WorkbenchLoadErrorBanner domains={['documents', 'faqs', 'overview']} />
      <KnowledgeWorkspaceBanner />
      <KnowledgeSyncLagBanner />
      <FormalPublishProgressBanner documents={documents} />
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          知識庫與手冊中心
        </Title>
        <Text type="secondary" style={{ fontSize: '13px' }}>
          {headerHint}
        </Text>
      </div>

      <Row gutter={[16, 16]} style={{ minHeight: 'min(70vh, 720px)' }}>
        <Col xs={24} lg={15} style={{ minHeight: 320, overflowY: 'auto' }}>
          <Tabs
            activeKey={activeTab}
            onChange={(key) => {
              setHasUserChosenTab(true);
              setActiveTab(key);
            }}
            type="card"
            items={tabItems}
            style={{ marginBottom: 0 }}
          />
        </Col>

        <Col xs={24} lg={9} style={{ minHeight: 320 }}>
          <PlaygroundSimulator initialQuery={playgroundQuery} />
        </Col>
      </Row>

      <QuickFaqDrawer
        open={quickFaqOpen}
        onClose={() => setQuickFaqOpen(false)}
        initialData={quickFaqData}
      />
    </div>
  );
};
