import type { TaskData } from './types';

declare global {
  // eslint-disable-next-line no-var
  var taskStore: Map<string, TaskData>;
}

if (!global.taskStore) {
  global.taskStore = new Map();
}

export const taskStore = global.taskStore;