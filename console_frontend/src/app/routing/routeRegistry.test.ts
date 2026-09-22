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

  it('maps knowledge-catalog list and write actions to Portal capabilities', () => {
    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'list',
        capabilities: ['ops.knowledge.read'],
      }).can,
    ).toBe(true);

    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'edit',
        capabilities: ['knowledge.edit'],
      }).can,
    ).toBe(true);

    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'submit',
        capabilities: ['knowledge.submit'],
      }).can,
    ).toBe(true);

    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'publish',
        capabilities: ['knowledge.publish'],
      }).can,
    ).toBe(false);

    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'publish',
        capabilities: ['knowledge.catalog.approve'],
      }).can,
    ).toBe(true);

    expect(
      evaluateResourceAccess({
        resource: 'knowledge-catalog',
        action: 'review',
        capabilities: ['knowledge.review'],
      }).can,
    ).toBe(true);
  });

  it('exports knowledge-catalog refine resource', () => {
    const resources = toRefineResources();
    expect(resources.some((item) => item.name === 'knowledge-catalog')).toBe(true);
    expect(
      resources.find((item) => item.name === 'knowledge-catalog')?.list,
    ).toBe('/knowledge/catalog');
  });
});
