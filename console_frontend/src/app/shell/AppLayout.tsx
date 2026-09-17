import React from 'react';
import { Layout, Typography } from 'antd';
import { Header } from './Header';

const { Content, Footer: AntFooter } = Layout;
const { Text } = Typography;

interface AppLayoutProps {
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  return (
    <Layout style={{ minHeight: '100vh', backgroundColor: '#F5F5F7' }}>
      <Header />
      <Content style={{ padding: '24px', maxWidth: '1440px', margin: '0 auto', width: '100%' }}>
        {children}
      </Content>
      <AntFooter style={{ textAlign: 'center', backgroundColor: '#F5F5F7', padding: '16px 24px' }}>
        <Text type="secondary" style={{ fontSize: '12px' }}>
          AI Ops 工作流程主控台 · 示範情境資料已嚴格隔離，正式佇列僅呈現經授權之真實案件。
        </Text>
      </AntFooter>
    </Layout>
  );
};
