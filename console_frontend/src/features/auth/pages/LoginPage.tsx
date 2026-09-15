import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiClient } from '../../../shared/api/client';
import {
  acquireEntraAccessToken,
  handleRedirectPromise,
  loginWithRedirect,
  type EntraPublicConfig,
} from '../../../shared/auth/msal';
import {
  clearAuthSession,
  loadAuthSession,
  saveAuthSession,
} from '../../../shared/auth/session';

const { Title, Paragraph, Text } = Typography;

interface AuthConfig {
  authMode?: string;
  headerAuthAllowed?: boolean;
  entraTenantId?: string | null;
  entraClientId?: string | null;
  entraScopes?: string[] | null;
  loginRedirectUri?: string | null;
}

function toEntraConfig(config: AuthConfig): EntraPublicConfig | null {
  const tenantId = String(config.entraTenantId || '').trim();
  const clientId = String(config.entraClientId || '').trim();
  if (!tenantId || !clientId) {
    return null;
  }
  return {
    tenantId,
    clientId,
    scopes: Array.isArray(config.entraScopes)
      ? config.entraScopes.filter((item): item is string => typeof item === 'string' && !!item)
      : undefined,
    redirectUri: config.loginRedirectUri || undefined,
  };
}

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [authMode, setAuthMode] = useState<string>('HEADER');
  const [headerAuthAllowed, setHeaderAuthAllowed] = useState<boolean>(true);
  const [entraConfig, setEntraConfig] = useState<EntraPublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [bootstrapping, setBootstrapping] = useState<boolean>(true);

  const redirectTo = searchParams.get('redirect') || '/console-v2/work';

  const continueWithSession = async () => {
    setLoading(true);
    setError(null);
    try {
      await apiClient('/api/capabilities');
      const redirectTarget = redirectTo.startsWith('/console-v2')
        ? redirectTo.slice('/console-v2'.length) || '/work'
        : redirectTo || '/work';
      navigate(redirectTarget.startsWith('/') ? redirectTarget : `/${redirectTarget}`, {
        replace: true,
      });
    } catch {
      clearAuthSession();
      setError('尚未通過身分驗證，請先完成登入。');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await apiClient<AuthConfig>('/api/auth/config');
        if (cancelled) return;
        setAuthMode(String(config.authMode || 'HEADER').toUpperCase());
        setHeaderAuthAllowed(Boolean(config.headerAuthAllowed));
        const nextEntra = toEntraConfig(config);
        setEntraConfig(nextEntra);
        if (String(config.authMode || '').toUpperCase() === 'ENTRA' && nextEntra) {
          const redirected = await handleRedirectPromise(nextEntra);
          if (cancelled) return;
          if (redirected?.accessToken) {
            await continueWithSession();
            return;
          }
          const silent = await acquireEntraAccessToken(nextEntra);
          if (cancelled) return;
          if (silent) {
            await continueWithSession();
            return;
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : '無法讀取登入設定，請稍後再試。',
          );
        }
      } finally {
        if (!cancelled) {
          setBootstrapping(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bootstrap once on mount
  }, []);

  const onEntraMicrosoftLogin = async () => {
    if (!entraConfig) {
      setError('後端尚未提供 Entra tenant/client 設定，無法啟動 Microsoft 登入。');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await loginWithRedirect(entraConfig);
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : '無法啟動 Microsoft 登入。');
    }
  };

  const onEntraSubmit = async (values: { accessToken: string }) => {
    const token = values.accessToken.trim();
    if (!token) {
      setError('請貼上有效的 Entra 存取權杖。');
      return;
    }
    saveAuthSession({ ...loadAuthSession(), bearerToken: token });
    await continueWithSession();
  };

  const onHeaderContinue = async () => {
    if (!headerAuthAllowed) {
      setError('此環境不允許 HEADER 測試登入，請改用 Entra。');
      return;
    }
    saveAuthSession({
      userId: 'ops.admin',
      userName: 'System Administrator',
      role: 'SYSTEM_ADMIN',
      ownerUnits: 'IT Service Desk',
      tenantId: 'default',
      groups: 'grp_public',
    });
    await continueWithSession();
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f5f5',
        padding: 24,
      }}
    >
      <Card style={{ width: 480, maxWidth: '100%' }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Title level={3} style={{ marginBottom: 8 }}>
              登入 AI Ops 工作主控台
            </Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              目前驗證模式：{authMode}
            </Paragraph>
          </div>
          {error && <Alert type="error" showIcon message={error} />}
          {bootstrapping ? (
            <Text type="secondary">正在檢查登入狀態…</Text>
          ) : authMode === 'ENTRA' ? (
            <>
              <Text>
                使用 Microsoft Entra 登入。登入後權杖會保存在此瀏覽器工作階段，並於 API
                請求帶入 Authorization 標頭；過期時會嘗試靜默續期。
              </Text>
              <Button
                type="primary"
                onClick={onEntraMicrosoftLogin}
                loading={loading}
                disabled={!entraConfig}
                block
              >
                使用 Microsoft 帳號登入
              </Button>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                若 Entra 應用程式尚未註冊 SPA 重新導向 URI，可暫時貼上存取權杖進行驗證。
              </Paragraph>
              <Form layout="vertical" onFinish={onEntraSubmit}>
                <Form.Item
                  label="Entra 存取權杖（後援）"
                  name="accessToken"
                  rules={[{ required: true, message: '請輸入存取權杖' }]}
                >
                  <Input.TextArea rows={3} placeholder="eyJ..." autoComplete="off" />
                </Form.Item>
                <Button htmlType="submit" loading={loading} block>
                  以權杖登入
                </Button>
              </Form>
            </>
          ) : (
            <>
              <Text>
                開發／PoC 可用 HEADER 測試身分。正式 Entra 模式上線後，此入口會改為 Microsoft 登入。
              </Text>
              <Button type="primary" onClick={onHeaderContinue} loading={loading} block>
                以測試管理員身分繼續
              </Button>
            </>
          )}
        </Space>
      </Card>
    </div>
  );
};
