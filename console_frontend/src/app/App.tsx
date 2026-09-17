import React from 'react';
import { Refine } from '@refinedev/core';
import routerBindings, {
  UnsavedChangesNotifier,
} from '@refinedev/react-router-v6';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { ConfigProvider, App as AntdApp, Result, Button } from 'antd';
import zhTW from 'antd/locale/zh_TW';

import { dataProvider } from './providers/dataProvider';
import { authProvider } from './providers/authProvider';
import { accessControlProvider } from './providers/accessControlProvider';
import { AppLayout } from './shell/AppLayout';

import { DashboardPage } from '../features/dashboard/pages/DashboardPage';
import { TriagePage } from '../features/triage/pages/TriagePage';
import { KnowledgePage } from '../features/knowledge/pages/KnowledgePage';
import { TicketsPage } from '../features/tickets/pages/TicketsPage';
import { HealthPage } from '../features/operations/pages/HealthPage';
import { CaseDetailPage } from '../features/improvements/pages/CaseDetailPage';
import { LoginPage } from '../features/auth/pages/LoginPage';

export const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={zhTW}
      theme={{
        token: {
          colorPrimary: '#5B5FC7',
          colorPrimaryHover: '#4F52B2',
          colorPrimaryActive: '#444791',
          colorPrimaryBg: '#F0F1FA',
          colorInfo: '#5B5FC7',
          colorSuccess: '#107C41',
          colorWarning: '#B78800',
          colorError: '#C4314B',
          colorTextBase: '#242424',
          colorTextSecondary: '#616161',
          colorBorder: '#E0E0E6',
          colorBorderSecondary: '#EBEBF2',
          colorBgLayout: '#F5F5F7',
          colorBgContainer: '#FFFFFF',
          borderRadius: 8,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans TC', Roboto, Helvetica, Arial, sans-serif",
        },
        components: {
          Button: {
            borderRadius: 6,
            fontWeight: 600,
            primaryColor: '#FFFFFF',
          },
          Card: {
            borderRadius: 10,
            colorBorderSecondary: '#EBEBF2',
          },
          Tabs: {
            colorPrimary: '#5B5FC7',
            itemSelectedColor: '#5B5FC7',
            itemHoverColor: '#4F52B2',
            inkBarColor: '#5B5FC7',
          },
          Tag: {
            borderRadius: 4,
          },
          Table: {
            headerBg: '#F7F7FA',
            headerColor: '#242424',
            rowHoverBg: '#F9F9FC',
          },
        },
      }}
    >
      <AntdApp>
        <BrowserRouter
          basename="/console-v2"
          future={{
            v7_relativeSplatPath: true,
            v7_startTransition: true,
          }}
        >
          <Refine
            dataProvider={dataProvider}
            authProvider={authProvider}
            accessControlProvider={accessControlProvider}
            routerProvider={routerBindings}
            resources={[
              {
                name: 'dashboard',
                list: '/dashboard',
                meta: {
                  label: '營運儀表板',
                },
              },
              {
                name: 'triage',
                list: '/triage',
                meta: {
                  label: '對話與分診',
                },
              },
              {
                name: 'knowledge',
                list: '/knowledge',
                meta: {
                  label: '知識庫與手冊',
                },
              },
              {
                name: 'tickets',
                list: '/tickets',
                meta: {
                  label: 'IT 工單追蹤',
                },
              },
              {
                name: 'health',
                list: '/operations/health',
                meta: {
                  label: '系統健康',
                },
              },
            ]}
            options={{
              syncWithLocation: true,
              warnWhenUnsavedChanges: true,
            }}
          >
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <AppLayout>
                    <Outlet />
                  </AppLayout>
                }
              >
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/work" element={<Navigate to="/dashboard" replace />} />
                <Route path="/triage" element={<TriagePage />} />
                <Route path="/improvements" element={<Navigate to="/triage" replace />} />
                <Route path="/improvements/cases" element={<Navigate to="/triage" replace />} />
                <Route path="/improvements/cases/:id" element={<CaseDetailPage />} />
                <Route path="/knowledge" element={<KnowledgePage />} />
                <Route path="/tickets" element={<TicketsPage />} />
                <Route path="/operations/health" element={<HealthPage />} />
                <Route
                  path="*"
                  element={
                    <Result
                      status="404"
                      title="404"
                      subTitle="抱歉，您所造訪的頁面不存在或已被移動。"
                      extra={
                        <Button type="primary" href="/console-v2/dashboard">
                          返回營運儀表板
                        </Button>
                      }
                    />
                  }
                />
              </Route>
            </Routes>
            <UnsavedChangesNotifier />
          </Refine>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
};
