import {describe, expect, it} from 'vitest';
import {operationStageLabel, strings, type Language} from '../src/i18n';

describe('operation stage labels', () => {
  for (const language of Object.keys(strings) as Language[]) {
    const t = strings[language];
    it(`${language}: removal does not inherit installation headings`, () => {
      expect(operationStageLabel(t, 'prepare', 'uninstall')).toBe(t.uninstallPreparing);
      expect(operationStageLabel(t, 'plan', 'uninstall')).toBe(t.uninstallPlanReady);
      expect(operationStageLabel(t, 'root_ready', 'uninstall')).toBe(t.uninstallRootReady);
      expect(operationStageLabel(t, 'complete', 'uninstall')).toBe(t.successUninstall);
      expect(operationStageLabel(t, 'uninstall_prepare', 'uninstall')).toBe(t.stages.uninstall_prepare);
    });
    it(`${language}: each record uses its own operation`, () => {
      for (const method of ['part', 'tf', 'image', 'reinstall', 'boot', 'update', undefined])
        expect(operationStageLabel(t, 'prepare', method)).toBe(t.stages.prepare);
      expect(operationStageLabel(t, 'unknown', 'uninstall')).toBe('unknown');
    });
  }
});
