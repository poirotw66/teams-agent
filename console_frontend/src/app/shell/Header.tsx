import React, { useMemo, useState } from 'react';
import { Layout, Menu, Space, Typography, Tag, Button } from 'antd';
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
  const { data: identity } = useGetIdentity<{
    id: string;
    name: string;
    role: string;
    ownerUnits: string[];
  }>();
  const [globalFaqOpen, setGlobalFaqOpen] = useState<boolean>(false);
  const faqWrite = CONSOLE_WRITE_ACTIONS.faqWrite;
  const { data: canWriteFaq } = useCan({
    resource: faqWrite.resource,
    action: faqWrite.action,
  });

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
