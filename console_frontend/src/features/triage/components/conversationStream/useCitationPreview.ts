import { useState } from 'react';
import { message } from 'antd';
import { CitationItem } from '../../../../shared/api/types';
import { apiClient } from '../../../../shared/api/client';
import { resolveCitation } from './citationLookup';

/** Citation drawer state plus optional remote source preview fetch. */
export function useCitationPreview() {
  const [selectedCitation, setSelectedCitation] = useState<CitationItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [loadingPreview, setLoadingPreview] = useState<boolean>(false);

  const openCitation = (cite: CitationItem) => {
    setSelectedCitation(cite);
    setDrawerOpen(true);
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setSelectedCitation(null);
  };

  const selectCitationByIdentifier = async (
    identifier: string,
    citations?: CitationItem[]
  ) => {
    const target = resolveCitation(identifier, citations);
    setSelectedCitation(target);
    setDrawerOpen(true);

    // If source_ref_id is present and content is not cached, fetch from backend
    if (target.source_ref_id && !target.content) {
      setLoadingPreview(true);
      try {
        const preview = await apiClient<{
          content?: string;
          downloadUrl?: string;
          sourcePath?: string;
        }>(`/api/sources/${target.source_ref_id}`);
        if (preview) {
          setSelectedCitation((prev) =>
            prev
              ? {
                  ...prev,
                  content: preview.content || prev.content,
                  download_url: preview.downloadUrl || prev.download_url,
                  source_path: preview.sourcePath || prev.source_path,
                }
              : null
          );
        }
      } catch (err) {
        console.debug('Failed to fetch source preview:', err);
      } finally {
        setLoadingPreview(false);
      }
    }
  };

  const handleCopyPath = (path: string) => {
    navigator.clipboard.writeText(path);
    message.success('路徑已複製至剪貼簿');
  };

  return {
    selectedCitation,
    drawerOpen,
    loadingPreview,
    openCitation,
    closeDrawer,
    selectCitationByIdentifier,
    handleCopyPath,
    setDrawerOpen,
  };
}
