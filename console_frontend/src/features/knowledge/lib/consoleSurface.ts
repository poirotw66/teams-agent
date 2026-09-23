/** Cloud vs laptop Console surface. Independent of CLOUD_FORMAL write mode. */

export type ConsoleSurfaceIdentity = {
  knowledgeInProcess?: boolean;
  consoleSurface?: string;
  knowledgeWorkspaceMode?: string;
};

export function isCloudConsoleSurface(
  identity?: ConsoleSurfaceIdentity | null,
): boolean {
  const explicit = String(identity?.consoleSurface || '').trim().toUpperCase();
  if (explicit === 'CLOUD') {
    return true;
  }
  if (explicit === 'LOCAL') {
    return false;
  }
  if (typeof identity?.knowledgeInProcess === 'boolean') {
    return identity.knowledgeInProcess === false;
  }
  return false;
}

export function defaultKnowledgePageTab(
  identity?: ConsoleSurfaceIdentity | null,
): 'docs' | 'cloud-mirror' {
  return isCloudConsoleSurface(identity) ? 'docs' : 'cloud-mirror';
}
