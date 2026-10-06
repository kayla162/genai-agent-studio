/** 遞迴凍結物件，讓共用的事件與示範資料無法被就地修改（與 WebSocket 每則訊息都是獨立物件的語意一致） */
export function deepFreeze<T>(value: T, seen: WeakSet<object> = new WeakSet()): T {
  if (value === null || typeof value !== 'object' || seen.has(value)) return value;
  seen.add(value);
  for (const key of Reflect.ownKeys(value)) deepFreeze((value as Record<PropertyKey, unknown>)[key], seen);
  Object.freeze(value);
  return value;
}
