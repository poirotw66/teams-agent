import React from 'react';
import { Refine } from '@refinedev/core';
import routerBindings, {
  UnsavedChangesNotifier,
} from '@refinedev/react-router-v6';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntdApp, Result, Button } from 'antd';
import zhTW from 'antd/locale/zh_TW';

import { dataProvider } from './providers/dataProvider';
import { authProvider } from './providers/authProvider';
import { accessControlProvider } from './providers/accessControlProvider';
import { AppLayout } from './shell/AppLayout';

import { WorkPage } from '../features/work/pages/WorkPage';
import { HealthPage } from '../features/operations/pages/HealthPage';
import { CaseDetailPage } from '../features/improvements/pages/CaseDetailPage';

export const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={zhTW}
      theme={{
        token: {
          colorPrimary: '#1890ff',
          borderRadius: 6,
        },
      }}
    >
      <AntdApp>
        <BrowserRouter basename="/console-v2">
          <Refine
            dataProvider={dataProvider}
            authProvider={authProvider}
            accessControlProvider={accessControlProvider}
            routerProvider={routerBindings}
            resources={[
              {
                name: 'work-items',
                list: '/work',
                meta: {
                  label: '我的工作',
                },
              },
              {
                name: 'improvements',
                list: '/work',
                show: '/improvements/cases/:id',
                meta: {
                  label: '問題改善',
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
            <AppLayout>
              <Routes>
                <Route path="/" element={<Navigate to="/work" replace />} />
                <Route path="/work" element={<WorkPage />} />
                <Route path="/operations/health" element={<HealthPage />} />
                <Route path="/improvements" element={<Navigate to="/work" replace />} />
                <Route path="/improvements/cases/:id" element={<CaseDetailPage />} />
                <Route
                  path="*"
                  element={
                    <Result
                      status="404"
                      title="404"
                      subTitle="抱歉，您所造訪的頁面不存在或已被移動。"
                      extra={
                        <Button type="primary" href="/console-v2/work">
                          返回我的工作
                        </Button>
                      }
                    />
                  }
                />
              </Routes>
            </AppLayout>
            <UnsavedChangesNotifier />
          </Refine>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
};
