import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Row, Col, Typography, Tabs } from 'antd';
import {
  CloudOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
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

const { Title, Text } = Typography;

export const KnowledgePage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const categoryParam = searchParams.get('category');

  const [activeTab, setActiveTab] = useState<string>('cloud-mirror');
  const [documents, setDocuments] = useState<ManualDocumentItem[]>(workbenchStore.getDocuments());
  const [faqs, setFaqs] = useState<FaqItem[]>(workbenchStore.getFaqs());
  const [gaps, setGaps] = useState<KnowledgeGapItem[]>(workbenchStore.getKnowledgeGaps());

  const [playgroundQuery, setPlaygroundQuery] = useState<string>('');
  const [quickFaqOpen, setQuickFaqOpen] = useState<boolean>(false);
  const [quickFaqData, setQuickFaqData] = useState<QuickFaqInitialData | null>(null);

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

  const tabItems = [
    {
      key: 'cloud-mirror',
      label: (
        <span>
          <CloudOutlined style={{ marginRight: 6 }} />
          雲端正式鏡像
        </span>
      ),
      children: <CloudFormalMirrorDocs onTestQuery={handleTestQuery} />,
    },
    {
      key: 'docs',
      label: (
        <span>
          <FileTextOutlined style={{ marginRight: 6 }} />
          本機測試工作區 ({documents.length})
        </span>
      ),
      children: (
        <ManualDocsManager
          documents={documents}
          onTestQuery={handleTestQuery}
          selectedCategory={categoryParam}
        />
      ),
    },
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
          「雲端正式鏡像」才是與雲端 active 同一份資料。本機測試工作區仍是獨立
          FILE sandbox，上傳不會回寫雲端。右側試問讀的是本機 sandbox 關鍵字，不是
          Agent GCS。
        </Text>
      </div>

      <Row gutter={[16, 16]} style={{ minHeight: 'min(70vh, 720px)' }}>
        {/* Left: Document & FAQ Managers */}
        <Col xs={24} lg={15} style={{ minHeight: 320, overflowY: 'auto' }}>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            type="card"
            items={tabItems}
            style={{ marginBottom: 0 }}
          />
        </Col>

        {/* Right: Live Playground Simulator */}
        <Col xs={24} lg={9} style={{ minHeight: 320 }}>
          <PlaygroundSimulator initialQuery={playgroundQuery} />
        </Col>
      </Row>

      {/* Quick FAQ Drawer */}
      <QuickFaqDrawer
        open={quickFaqOpen}
        onClose={() => setQuickFaqOpen(false)}
        initialData={quickFaqData}
      />
    </div>
  );
};
