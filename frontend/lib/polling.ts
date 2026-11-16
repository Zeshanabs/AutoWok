/**
 * Repeats `callback` every `intervalMs` while the tab is visible. Hidden tabs
 * make no requests; when the tab becomes visible again the callback runs once
 * immediately. A callback that returns a promise is not started again until
 * that promise settles. Returns a function that stops the polling.
 */
export function pollWhileVisible(callback: () => unknown, intervalMs: number): () => void {
  let running = false;
  const tick = () => {
    if (document.hidden || running) return;
    const result = callback();
    if (result instanceof Promise) {
      running = true;
      void result.catch(() => undefined).finally(() => {
        running = false;
      });
    }
  };
  const onVisibility = () => {
    if (!document.hidden) tick();
  };
  const timer = window.setInterval(tick, intervalMs);
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
