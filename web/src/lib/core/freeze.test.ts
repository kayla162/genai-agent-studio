import { describe, it, expect } from 'vitest';
import { deepFreeze } from './freeze';

describe('deepFreeze', () => {
  it('freezes nested objects and arrays', () => {
    const value = deepFreeze({ a: { b: [{ c: 1 }] }, list: [1, 2] });
    expect(Object.isFrozen(value)).toBe(true);
    expect(Object.isFrozen(value.a)).toBe(true);
    expect(Object.isFrozen(value.a.b)).toBe(true);
    expect(Object.isFrozen(value.a.b[0])).toBe(true);
    expect(Object.isFrozen(value.list)).toBe(true);
  });

  it('rejects in-place mutation of nested values', () => {
    const value = deepFreeze({ nested: { k: 0 } });
    expect(Reflect.set(value.nested, 'k', 1)).toBe(false);
    expect(value.nested.k).toBe(0);
  });

  it('passes primitives and null through unchanged', () => {
    expect(deepFreeze(5)).toBe(5);
    expect(deepFreeze('x')).toBe('x');
    expect(deepFreeze(null)).toBeNull();
    expect(deepFreeze(undefined)).toBeUndefined();
  });

  it('does not recurse forever on a self-referencing object', () => {
    const node: { self?: unknown } = {};
    node.self = node;
    expect(Object.isFrozen(deepFreeze(node))).toBe(true);
  });
});
