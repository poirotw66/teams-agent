import React, { useEffect, useState } from "react";
import { Alert, Button } from "antd";
import {
  workbenchStore,
  type WorkbenchDomain,
} from "../api/workbench/store";

type WorkbenchLoadErrorBannerProps = {
  /** Domains this page owns; retry refreshes only these. */
  domains?: readonly WorkbenchDomain[];
};

/**
 * Surfaces workbench fetch failures so empty KPI/list state is not mistaken
 * for a healthy zero-activity dashboard.
 */
export const WorkbenchLoadErrorBanner: React.FC<WorkbenchLoadErrorBannerProps> = ({
  domains,
}) => {
  const [loadError, setLoadError] = useState<string | null>(
    workbenchStore.getLoadError(),
  );
  const [isLoading, setIsLoading] = useState<boolean>(
    workbenchStore.getIsLoading(),
  );

  useEffect(() => {
    return workbenchStore.subscribe(() => {
      setLoadError(workbenchStore.getLoadError());
      setIsLoading(workbenchStore.getIsLoading());
    });
  }, []);

  if (!loadError || isLoading) {
    return null;
  }

  const handleRetry = () => {
    if (domains && domains.length > 0) {
      void workbenchStore.ensureDomains(domains, { force: true });
      return;
    }
    void workbenchStore.loadAll();
  };

  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 16 }}
      message="無法載入工作台資料"
      description={loadError}
      action={
        <Button size="small" onClick={handleRetry}>
          重試
        </Button>
      }
    />
  );
};
