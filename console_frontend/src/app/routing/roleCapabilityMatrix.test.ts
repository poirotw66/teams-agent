import { describe, expect, it } from 'vitest';
import { evaluateResourceAccess } from './routeRegistry';
import { ROLE_CAPABILITY_FIXTURES } from './roleCapabilityFixtures';

describe('role capability matrix against route registry', () => {
  it('allows SYSTEM_ADMIN core pages and FAQ write', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.SYSTEM_ADMIN;
    expect(evaluateResourceAccess({ resource: 'dashboard', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'evaluations', action: 'create', capabilities: caps }).can).toBe(true);
  });

  it('denies VIEWER dashboard and write actions while allowing triage read', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.VIEWER;
    expect(evaluateResourceAccess({ resource: 'dashboard', action: 'list', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'resolve', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'evaluations', action: 'create', capabilities: caps }).can).toBe(false);
  });

  it('allows ANALYST dashboard/triage/health read but denies knowledge and FAQ write', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.ANALYST;
    expect(evaluateResourceAccess({ resource: 'dashboard', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'list', capabilities: caps }).can).toBe(false);
    // health readCapabilities include ops.summary.read, which ANALYST has.
    expect(evaluateResourceAccess({ resource: 'health', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(false);
  });

  it('allows KNOWLEDGE_ADMIN FAQ write and Golden Eval create, denies resolve', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.KNOWLEDGE_ADMIN;
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'evaluations', action: 'create', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'resolve', capabilities: caps }).can).toBe(false);
  });

  it('allows SERVICE_OWNER resolve and broadcast manage, denies FAQ write without faq.write', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.SERVICE_OWNER;
    expect(evaluateResourceAccess({ resource: 'triage', action: 'resolve', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'dashboard', action: 'edit', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(false);
  });

  it('allows AUDITOR audit and knowledge read, denies health and FAQ write', () => {
    const caps = ROLE_CAPABILITY_FIXTURES.AUDITOR;
    expect(evaluateResourceAccess({ resource: 'audit', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'list', capabilities: caps }).can).toBe(true);
    expect(evaluateResourceAccess({ resource: 'health', action: 'list', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'knowledge', action: 'create', capabilities: caps }).can).toBe(false);
  });

  it('denies unauthenticated empty capability set across mapped resources', () => {
    const caps: string[] = [];
    expect(evaluateResourceAccess({ resource: 'dashboard', action: 'list', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'triage', action: 'list', capabilities: caps }).can).toBe(false);
    expect(evaluateResourceAccess({ resource: 'unknown-thing', action: 'list', capabilities: caps }).can).toBe(false);
  });
});
