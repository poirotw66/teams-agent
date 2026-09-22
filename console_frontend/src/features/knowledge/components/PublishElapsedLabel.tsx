import React, { useEffect, useState } from 'react';

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) {
    return `${seconds} 秒`;
  }
  return `${minutes} 分 ${seconds.toString().padStart(2, '0')} 秒`;
}

interface PublishElapsedLabelProps {
  /** Epoch ms when the publish attempt started. Null pauses the timer. */
  startedAtMs: number | null;
  prefix?: string;
}

/**
 * Live elapsed-time label for formal publish. Cloud formal publish rebuilds
 * embeddings, syncs Gemini File Search, and uploads GCS artifacts — often
 * 1–5+ minutes on a full corpus.
 */
export const PublishElapsedLabel: React.FC<PublishElapsedLabelProps> = ({
  startedAtMs,
  prefix = '已過',
}) => {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (startedAtMs == null) {
      setElapsedSeconds(0);
      return;
    }
    const tick = () => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000)));
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [startedAtMs]);

  if (startedAtMs == null) {
    return null;
  }

  const hint =
    elapsedSeconds >= 120
      ? '（整庫重嵌＋File Search 同步，大型庫可能需 3–8 分鐘）'
      : elapsedSeconds >= 30
        ? '（索引與雙後端同步進行中）'
        : '';

  return (
    <span>
      {prefix} {formatElapsed(elapsedSeconds)}
      {hint}
    </span>
  );
};

export { formatElapsed };
