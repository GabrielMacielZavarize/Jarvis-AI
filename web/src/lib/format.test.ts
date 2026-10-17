import { describe, expect, it } from 'vitest';
import { groupCode } from './format';

describe('groupCode', () => {
  it('splits a confirmation code in groups of three digits', () => {
    expect(groupCode('482913')).toBe('482 913');
    expect(groupCode('048213')).toBe('048 213');
  });

  it('ignores anything that is not a digit', () => {
    expect(groupCode('48-29 13')).toBe('482 913');
  });
});
