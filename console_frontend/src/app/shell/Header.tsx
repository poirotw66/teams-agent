import React, { useState } from 'react';
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
  CheckCircleFilled,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useGetIdentity } from '@refinedev/core';
import { QuickFaqDrawer } from '../../features/dashboard/components/QuickFaqDrawer';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

export const Header: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: identity } = useGetIdentity<{ id: string; name: string; role: string; ownerUnits: string[] }>();
  const [globalFaqOpen, setGlobalFaqOpen] = useState<boolean>(false);

  const menuItems = [
    {
      key: '/dashboard',
      icon: <DashboardOutlined />,
      label: '營運儀表板',
    },
    {
      key: '/triage',
      icon: <CommentOutlined />,
      label: '對話與分診',
    },
    {
      key: '/knowledge',
      icon: <BookOutlined />,
      label: '知識庫與手冊',
    },
    {
      key: '/tickets',
      icon: <FileDoneOutlined />,
      label: 'IT 工單追蹤',
    },
    {
      key: '/operations/health',
      icon: <HeartOutlined />,
      label: '系統健康',
    },
  ];

  // Match active menu key or fallbacks
  let selectedKey = '/dashboard';
  if (location.pathname.startsWith('/triage') || location.pathname.startsWith('/improvements')) {
    selectedKey = '/triage';
  } else if (location.pathname.startsWith('/knowledge')) {
    selectedKey = '/knowledge';
  } else if (location.pathname.startsWith('/tickets')) {
    selectedKey = '/tickets';
  } else if (location.pathname.startsWith('/operations/health')) {
    selectedKey = '/operations/health';
  }

  return (
    <>
      <AntHeader
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          backgroundColor: '#242438',
          borderBottom: '1px solid #3d3c4f',
          color: '#fff',
          height: 60,
          lineHeight: '60px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
          zIndex: 10,
        }}
      >
        <Space size="large" align="center">
          <Space size="middle" style={{ cursor: 'pointer' }} onClick={() => navigate('/dashboard')}>
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
            <div>
              <div style={{ color: '#ffffff', fontSize: '16px', fontWeight: 700, lineHeight: 1.2 }}>
                資訊客服營運中心
              </div>
              <div style={{ color: '#a6a6b8', fontSize: '11px', lineHeight: 1 }}>
                Teams AI Ops Console
              </div>
            </div>
          </Space>

          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{
              minWidth: 500,
              backgroundColor: 'transparent',
              borderBottom: 'none',
              fontSize: '14px',
              fontWeight: 500,
            }}
          />
        </Space>

        <Space size="middle" align="center">
          {/* Status Badges with Teams Fluent tokens */}
          <Space size="small" style={{ marginRight: 8 }}>
            <Tag
              style={{
                backgroundColor: 'rgba(16, 124, 65, 0.2)',
                color: '#60d98f',
                border: '1px solid rgba(16, 124, 65, 0.4)',
                borderRadius: 12,
                padding: '1px 10px',
              }}
              icon={<CheckCircleFilled style={{ color: '#52c41a' }} />}
            >
              Teams 機器人：正常運行
            </Tag>
            <Tag
              style={{
                backgroundColor: 'rgba(91, 95, 199, 0.25)',
                color: '#c5c7ff',
                border: '1px solid rgba(91, 95, 199, 0.5)',
                borderRadius: 12,
                padding: '1px 10px',
              }}
              icon={<CheckCircleFilled style={{ color: '#8c90ff' }} />}
            >
              工單系統：已連線
            </Tag>
          </Space>

          {/* Quick FAQ Button with Teams Primary */}
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

          {identity && (
            <Space size="small">
              <UserOutlined style={{ color: '#8c8c8c' }} />
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
            舊版後台
          </Button>
        </Space>
      </AntHeader>

      <QuickFaqDrawer
        open={globalFaqOpen}
        onClose={() => setGlobalFaqOpen(false)}
      />
    </>
  );
};
