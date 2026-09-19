import React, { useEffect, useState } from "react";
import { Alert, Button } from "antd";
import { workbenchStore } from "../api/workbenchStore";

/**
 * Surfaces workbench fetch failures so empty KPI/list state is not mistaken
 * for a healthy zero-activity dashboard.
 */
export const WorkbenchLoadErrorBanner: React.FC = () => {
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

  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 16 }}
      message="無法載入工作台資料"
      description={loadError}
      action={
        <Button size="small" onClick={() => void workbenchStore.loadAll()}>
          重試
        </Button>
      }
    />
  );
};
