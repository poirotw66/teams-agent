import React, { useEffect, useState } from 'react';
import { Alert, Typography } from 'antd';
import { PublishElapsedLabel } from './PublishElapsedLabel';
import {
  clearFormalPublishInFlight,
  FormalPublishInFlight,
  readFormalPublishInFlight,
} from '../lib/formalPublishSession';
import { ManualDocumentItem } from '../../../shared/api/types';

const { Text } = Typography;

/** Clear stale session markers once the document leaves APPROVED/PUBLISHING. */
function shouldKeepInFlight(
  inFlight: FormalPublishInFlight,
  documents: ManualDocumentItem[],
): boolean {
  const doc = documents.find((item) => item.id === inFlight.documentId);
  if (!doc) {
    // Documents may still be loading; keep the banner briefly.
    return true;
  }
  return doc.status === 'APPROVED' || doc.status === 'PUBLISHING';
}

interface FormalPublishProgressBannerProps {
  documents: ManualDocumentItem[];
}

/**
 * Survives page refresh while a formal publish HTTP request may still be
 * running server-side. Explains elapsed time so operators do not assume
 * an empty/hung list means data was deleted.
 */
export const FormalPublishProgressBanner: React.FC<FormalPublishProgressBannerProps> = ({
  documents,
}) => {
  const [inFlight, setInFlight] = useState<FormalPublishInFlight | null>(() =>
    readFormalPublishInFlight(),
  );

  useEffect(() => {
    const current = readFormalPublishInFlight();
    if (!current) {
      setInFlight(null);
      return;
    }
    if (documents.length > 0 && !shouldKeepInFlight(current, documents)) {
      clearFormalPublishInFlight(current.documentId);
      setInFlight(null);
      return;
    }
    setInFlight(current);
  }, [documents]);

  useEffect(() => {
    if (!inFlight) return;
    const timer = window.setInterval(() => {
      setInFlight(readFormalPublishInFlight());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [inFlight?.documentId, inFlight?.startedAtMs]);

  if (!inFlight) {
    return null;
  }

  const title = inFlight.documentTitle
    ? `《${inFlight.documentTitle}》正式發布進行中`
    : '正式發布進行中';

  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 12 }}
      message={title}
      description={
        <Text type="secondary">
          <PublishElapsedLabel startedAtMs={inFlight.startedAtMs} />
          。請勿關閉分頁；列表應可持續載入，完成後狀態會自動更新。
        </Text>
      }
    />
  );
};
