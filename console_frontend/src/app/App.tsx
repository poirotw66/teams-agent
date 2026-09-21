import React, { Suspense } from 'react';
import { Refine } from '@refinedev/core';
import routerBindings, {
  UnsavedChangesNotifier,
} from '@refinedev/react-router-v6';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { ConfigProvider, App as AntdApp, Result, Button, Spin } from 'antd';
import zhTW from 'antd/locale/zh_TW';

import { Authenticated } from '@refinedev/core';
import { dataProvider } from './providers/dataProvider';
import { authProvider } from './providers/authProvider';
import { accessControlProvider } from './providers/accessControlProvider';
import { AppLayout } from './shell/AppLayout';
import { toRefineResources } from './routing/routeRegistry';

const DashboardPage = React.lazy(() =>
  import('../features/dashboard/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const TriagePage = React.lazy(() =>
  import('../features/triage/pages/TriagePage').then((m) => ({ default: m.TriagePage })),
);
const KnowledgePage = React.lazy(() =>
  import('../features/knowledge/pages/KnowledgePage').then((m) => ({ default: m.KnowledgePage })),
);
const ReleasesPage = React.lazy(() =>
  import('../features/knowledge/pages/ReleasesPage').then((m) => ({ default: m.ReleasesPage })),
);
const ReviewsPage = React.lazy(() =>
  import('../features/knowledge/pages/ReviewsPage').then((m) => ({ default: m.ReviewsPage })),
);
const SyncJobsPage = React.lazy(() =>
  import('../features/knowledge/pages/SyncJobsPage').then((m) => ({ default: m.SyncJobsPage })),
);
const TicketsPage = React.lazy(() =>
  import('../features/tickets/pages/TicketsPage').then((m) => ({ default: m.TicketsPage })),
);
const HealthPage = React.lazy(() =>
  import('../features/operations/pages/HealthPage').then((m) => ({ default: m.HealthPage })),
);
const CaseDetailPage = React.lazy(() =>
  import('../features/improvements/pages/CaseDetailPage').then((m) => ({
    default: m.CaseDetailPage,
  })),
);
const EvaluationsPage = React.lazy(() =>
  import('../features/evaluations/pages/EvaluationsPage').then((m) => ({
    default: m.EvaluationsPage,
  })),
);
const ExamplesPage = React.lazy(() =>
  import('../features/ai/pages/ExamplesPage').then((m) => ({ default: m.ExamplesPage })),
);
const PromptsPage = React.lazy(() =>
  import('../features/ai/pages/PromptsPage').then((m) => ({ default: m.PromptsPage })),
);
const SearchPage = React.lazy(() =>
  import('../features/operations/pages/SearchPage').then((m) => ({ default: m.SearchPage })),
);
const LoginPage = React.lazy(() =>
  import('../features/auth/pages/LoginPage').then((m) => ({ default: m.LoginPage })),
);

const AuditPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.AuditPage };
});
const FlagsPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.FlagsPage };
});
const MaskingPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.MaskingPage };
});
const ModelsPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.ModelsPage };
});
const RetentionPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.RetentionPage };
});
const RolesPage = React.lazy(async () => {
  const m = await import('../features/governance/pages/GovernancePages');
  return { default: m.RolesPage };
});
const BudgetsPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.BudgetsPage };
});
const CostsPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.CostsPage };
});
const IssuesPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.IssuesPage };
});
const KnowledgeAnalyticsPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.KnowledgeAnalyticsPage };
});
const KnowledgeAuditPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.KnowledgeAuditPage };
});
const RoutesPage = React.lazy(async () => {
  const m = await import('../features/operations/pages/OpsPages');
  return { default: m.RoutesPage };
});

const routeFallback = (
  <div style={{ display: 'grid', placeItems: 'center', minHeight: 240 }}>
    <Spin size="large" />
  </div>
);

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
            resources={toRefineResources()}
            options={{
              syncWithLocation: true,
              warnWhenUnsavedChanges: true,
            }}
          >
            <Suspense fallback={routeFallback}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route
                  element={
                    <Authenticated
                      key="console-authenticated"
                      redirectOnFail="/console-v2/login"
                      appendCurrentPathToQuery
                      loading={routeFallback}
                    >
                      <AppLayout>
                        <Outlet />
                      </AppLayout>
                    </Authenticated>
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
                  <Route path="/knowledge/reviews" element={<ReviewsPage />} />
                  <Route path="/knowledge/releases" element={<ReleasesPage />} />
                  <Route path="/knowledge/sync" element={<SyncJobsPage />} />
                  <Route path="/tickets" element={<TicketsPage />} />
                  <Route path="/operations/health" element={<HealthPage />} />
                  <Route path="/ai/evaluations" element={<EvaluationsPage />} />
                  <Route path="/ai/examples" element={<ExamplesPage />} />
                  <Route path="/ai/prompts" element={<PromptsPage />} />
                  <Route path="/ai/models" element={<ModelsPage />} />
                  <Route path="/ai/flags" element={<FlagsPage />} />
                  <Route path="/ai/evals" element={<Navigate to="/ai/evaluations" replace />} />
                  <Route path="/operations/issues" element={<IssuesPage />} />
                  <Route path="/operations/routes" element={<RoutesPage />} />
                  <Route path="/operations/costs" element={<CostsPage />} />
                  <Route path="/operations/budgets" element={<BudgetsPage />} />
                  <Route path="/governance/roles" element={<RolesPage />} />
                  <Route path="/governance/retention" element={<RetentionPage />} />
                  <Route path="/governance/masking" element={<MaskingPage />} />
                  <Route path="/governance/audit" element={<AuditPage />} />
                  <Route path="/knowledge/analytics" element={<KnowledgeAnalyticsPage />} />
                  <Route path="/knowledge/audit" element={<KnowledgeAuditPage />} />
                  <Route path="/operations/search" element={<SearchPage />} />
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
            </Suspense>
            <UnsavedChangesNotifier />
          </Refine>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
};
