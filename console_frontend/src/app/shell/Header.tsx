import React, { useMemo, useState } from 'react';
import { Layout, Menu, Space, Typography, Tag, Button, message } from 'antd';
import {
  DashboardOutlined,
  CommentOutlined,
  BookOutlined,
  FileDoneOutlined,
  ThunderboltOutlined,
  HeartOutlined,
  ExportOutlined,
  UserOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useCan, useGetIdentity } from '@refinedev/core';
import { QuickFaqDrawer } from '../../features/dashboard/components/QuickFaqDrawer';
import {
  CONSOLE_WRITE_ACTIONS,
  buildGroupedOverflowNavItems,
  listPrimaryNavRoutes,
  resolveSelectedMenuKeys,
} from '../routing/routeRegistry';
import { refreshCachedSession } from '../providers/authProvider';
import { ApiError } from '../../shared/api/client';
import { resetKnowledgeWorkspaceMode } from '../../shared/api/workbench/knowledgeWorkspaceApi';
import { ServiceHealthBadge } from './ServiceHealthBadge';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

const PRIMARY_NAV_ICONS: Record<string, React.ReactNode> = {
  '/dashboard': <DashboardOutlined />,
  '/triage': <CommentOutlined />,
  '/knowledge': <BookOutlined />,
  '/tickets': <FileDoneOutlined />,
  '/operations/health': <HeartOutlined />,
};

export const Header: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: identity, refetch } = useGetIdentity<{
    id: string;
    name: string;
    role: string;
    ownerUnits: string[];
    authMode?: string;
    relaxedWorkflow?: boolean;
    knowledgeWorkspaceMode?: string;
    cloudFormalWritesAllowed?: boolean;
    cloudFormalWriteBlockReasons?: string[];
    cloudFormalWriteBlockReasonLabels?: string[];
    knowledgeWorkspaceSwitchAllowed?: boolean;
    knowledgeWorkspaceOverrideActive?: boolean;
    knowledgeWorkspaceModeSource?: string;
  }>();
  const [globalFaqOpen, setGlobalFaqOpen] = useState<boolean>(false);
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const faqWrite = CONSOLE_WRITE_ACTIONS.faqWrite;
  const { data: canWriteFaq } = useCan({
    resource: faqWrite.resource,
    action: faqWrite.action,
  });

  // UX: hide CLOUD formal-path switching; label the normal workspace as 知識庫
  // (server mode remains LOCAL_SANDBOX). Stale CLOUD overrides can still reset.
  const workspaceMode = String(identity?.knowledgeWorkspaceMode || 'LOCAL_SANDBOX').toUpperCase();
  const isCloudWorkspace = workspaceMode === 'CLOUD_FORMAL';
  const workspaceLabel = isCloudWorkspace ? '正式路徑（鎖定）' : '知識庫';
  const workspaceTagColor = isCloudWorkspace ? 'orange' : 'blue';
  const overrideActive = Boolean(identity?.knowledgeWorkspaceOverrideActive);
  const blockLabels =
    identity?.cloudFormalWriteBlockReasonLabels
    || identity?.cloudFormalWriteBlockReasons
    || [];
  const workspaceHint = isCloudWorkspace
    ? `正式雲端寫入路徑尚未開放${
        blockLabels.length ? `：${blockLabels.join('；')}` : ''
      }。請回到一般知識庫工作區。`
    : '一般知識管理：草稿、審核與發布（lab／營運預設）';
  const canResetWorkspace =
    Boolean(identity?.knowledgeWorkspaceSwitchAllowed)
    && (isCloudWorkspace || overrideActive);

  const onWorkspaceReset = async () => {
    setWorkspaceSaving(true);
    try {
      await resetKnowledgeWorkspaceMode();
      await refreshCachedSession();
      await refetch?.();
      message.success('已回到環境預設的知識庫工作區。');
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : '重設工作區失敗';
      message.error(detail);
    } finally {
      setWorkspaceSaving(false);
    }
  };

  const menuItems = useMemo(() => {
    const primary = listPrimaryNavRoutes().map((route) => ({
      key: route.path,
      icon: PRIMARY_NAV_ICONS[route.path],
      label: route.label,
    }));
    const overflowChildren = buildGroupedOverflowNavItems().map((group) => ({
      key: `group:${group.groupId}`,
      label: group.groupLabel,
      children: group.routes.map((route) => ({
        key: route.path,
        label: route.label,
      })),
    }));
    return [
      ...primary,
      {
        key: 'more-routes',
        icon: <AppstoreOutlined />,
        label: '更多功能',
        children: overflowChildren,
      },
    ];
  }, []);

  const selectedKeys = resolveSelectedMenuKeys(location.pathname);

  return (
    <>
      <AntHeader
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
          justifyContent: 'center',
          padding: '8px 16px',
          backgroundColor: '#242438',
          borderBottom: '1px solid #3d3c4f',
          color: '#fff',
          height: 'auto',
          minHeight: 60,
          lineHeight: 1.2,
          boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
          zIndex: 10,
          gap: 4,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 12,
              cursor: 'pointer',
              background: 'transparent',
              border: 'none',
              padding: 0,
              color: 'inherit',
              flexShrink: 0,
            }}
            aria-label="返回營運儀表板"
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 7,
                backgroundColor: '#5b5fc7',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#ffffff',
                fontWeight: 800,
                fontSize: 16,
                letterSpacing: '-0.5px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
              }}
            >
              T
            </div>
            <div style={{ textAlign: 'left' }}>
              <div style={{ color: '#ffffff', fontSize: '16px', fontWeight: 700, lineHeight: 1.2 }}>
                資訊客服營運中心
              </div>
              <div style={{ color: '#a6a6b8', fontSize: '11px', lineHeight: 1 }}>
                Teams AI Ops Console
              </div>
            </div>
          </button>

          <Space size="small" align="center" wrap style={{ justifyContent: 'flex-end' }}>
            <Tag
              color={workspaceTagColor}
              title={workspaceHint}
              style={{ marginInlineEnd: 0, fontWeight: 700, letterSpacing: 0.4 }}
            >
              {workspaceLabel}
            </Tag>
            {canResetWorkspace ? (
              <Button
                size="small"
                type="text"
                disabled={workspaceSaving}
                onClick={() => {
                  void onWorkspaceReset();
                }}
                style={{ color: '#a6a6b8' }}
              >
                回到知識庫
              </Button>
            ) : null}
            {identity?.relaxedWorkflow ? (
              <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                RELAXED
              </Tag>
            ) : null}
            <ServiceHealthBadge />

            {canWriteFaq?.can ? (
              <Button
                type="primary"
                size="middle"
                icon={<ThunderboltOutlined />}
                onClick={() => setGlobalFaqOpen(true)}
                style={{
                  backgroundColor: '#5b5fc7',
                  borderColor: '#5b5fc7',
                  borderRadius: 6,
                  boxShadow: '0 2px 4px rgba(91, 95, 199, 0.3)',
                }}
              >
                快速新增 FAQ
              </Button>
            ) : null}

            {identity && (
              <Space size="small">
                <UserOutlined style={{ color: '#8c8c8c' }} aria-hidden />
                <Text style={{ color: '#ffffff', fontSize: '13px' }}>{identity.name}</Text>
                <Tag color="blue">{identity.role}</Tag>
              </Space>
            )}

            <Button
              type="link"
              size="small"
              icon={<ExportOutlined />}
              href="/"
              style={{ color: '#8c8c8c', padding: 0 }}
            >
              舊版後台（相容入口）
            </Button>
          </Space>
        </div>

        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={selectedKeys}
          items={menuItems}
          onClick={({ key }) => {
            if (String(key).startsWith('group:') || key === 'more-routes') {
              return;
            }
            navigate(String(key));
          }}
          style={{
            width: '100%',
            minWidth: 0,
            backgroundColor: 'transparent',
            borderBottom: 'none',
            fontSize: '14px',
            fontWeight: 500,
            lineHeight: '40px',
          }}
        />
      </AntHeader>

      <QuickFaqDrawer
        open={globalFaqOpen}
        onClose={() => setGlobalFaqOpen(false)}
      />
    </>
  );
};
