import { describe, expect, it } from 'vitest';
import {
  evaluateResourceAccess,
  resolvePrimaryNavKey,
  toRefineResources,
} from './routeRegistry';

describe('routeRegistry access mapping', () => {
  it('denies unknown resources by default (fail closed)', () => {
    const result = evaluateResourceAccess({
      resource: 'not-a-real-resource',
      action: 'list',
      capabilities: ['ops.health.read'],
    });
    expect(result.can).toBe(false);
    expect(result.reason).toMatch(/fail closed|未映射/);
  });

  it('allows triage read when conversations capability is present', () => {
    const result = evaluateResourceAccess({
      resource: 'triage',
      action: 'list',
      capabilities: ['ops.conversations.read'],
    });
    expect(result.can).toBe(true);
  });

  it('requires evals.write for golden eval create', () => {
    const denied = evaluateResourceAccess({
      resource: 'evaluations',
      action: 'create',
      capabilities: ['ops.evals.read'],
    });
    expect(denied.can).toBe(false);

    const allowed = evaluateResourceAccess({
      resource: 'evaluations',
      action: 'create',
      capabilities: ['ops.evals.write'],
    });
    expect(allowed.can).toBe(true);
  });

  it('keeps primary nav selection aligned for nested knowledge paths', () => {
    expect(resolvePrimaryNavKey('/knowledge/reviews')).toBe('/knowledge');
    expect(resolvePrimaryNavKey('/improvements/cases/abc')).toBe('/triage');
    expect(resolvePrimaryNavKey('/operations/costs')).toBe('/dashboard');
  });

  it('exports refine resources without parameterized paths', () => {
    const resources = toRefineResources();
    expect(resources.some((item) => item.name === 'dashboard')).toBe(true);
    expect(resources.every((item) => !item.list.includes(':'))).toBe(true);
  });
});
