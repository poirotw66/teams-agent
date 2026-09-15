import React from 'react';
import { Layout, Menu, Space, Typography, Tag, Button } from 'antd';
import {
  CheckSquareOutlined,
  AlertOutlined,
  HeartOutlined,
  ExportOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useGetIdentity } from '@refinedev/core';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

export const Header: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: identity } = useGetIdentity<{ id: string; name: string; role: string; ownerUnits: string[] }>();

  const menuItems = [
    {
      key: '/console-v2/work',
      icon: <CheckSquareOutlined />,
      label: '我的工作',
    },
    {
      key: '/console-v2/improvements',
      icon: <AlertOutlined />,
      label: '問題改善',
    },
    {
      key: '/console-v2/operations/health',
      icon: <HeartOutlined />,
      label: '系統健康',
    },
  ];

  const selectedKey = menuItems.find((item) => location.pathname.startsWith(item.key))?.key || '/console-v2/work';

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        backgroundColor: '#001529',
        color: '#fff',
      }}
    >
      <Space size="large" align="center">
        <Text strong style={{ color: '#fff', fontSize: '18px', cursor: 'pointer' }} onClick={() => navigate('/console-v2/work')}>
          AI Ops 工作主控台
        </Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ minWidth: 320, backgroundColor: 'transparent' }}
        />
      </Space>

      <Space size="middle" align="center">
        {identity && (
          <Space size="small">
            <UserOutlined style={{ color: '#8c8c8c' }} />
            <Text style={{ color: '#ffffff' }}>{identity.name}</Text>
            <Tag color="blue">{identity.role}</Tag>
            {identity.ownerUnits?.length > 0 && (
              <Tag color="geekblue">{identity.ownerUnits[0]}</Tag>
            )}
          </Space>
        )}
        <Button
          type="link"
          size="small"
          icon={<ExportOutlined />}
          href="/"
          style={{ color: '#1890ff' }}
        >
          返回舊版後台
        </Button>
      </Space>
    </AntHeader>
  );
};
