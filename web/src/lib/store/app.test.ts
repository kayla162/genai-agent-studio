import { afterEach, describe, expect, it } from 'vitest';
import { MOCK_OPTIONS } from '@/lib/api/mock/options';
import { useAppStore } from './app';

afterEach(() => useAppStore.setState({ options: null }));

describe('app store', () => {
  it('loads the models and engines the current API offers', async () => {
    expect(useAppStore.getState().options).toBeNull();
    await useAppStore.getState().loadOptions();
    expect(useAppStore.getState().options).toEqual(MOCK_OPTIONS);
  });
});
