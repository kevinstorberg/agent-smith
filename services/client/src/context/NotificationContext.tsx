import { useCallback, useRef, useState, type ReactNode } from 'react';
import { NotificationContext, type Notification, type NotificationType } from './useNotification';

const AUTO_DISMISS_MS = 7000;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const timers = useRef<Map<string, number>>(new Map());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const notify = useCallback((message: string, type: NotificationType) => {
    if (!message) return;

    const id = crypto.randomUUID();
    setNotifications(prev => [...prev, { id, message, type }]);

    const timer = window.setTimeout(() => {
      timers.current.delete(id);
      setNotifications(prev => prev.filter(n => n.id !== id));
    }, AUTO_DISMISS_MS);
    timers.current.set(id, timer);
  }, []);

  return (
    <NotificationContext.Provider value={{ notifications, notify, dismiss }}>
      {children}
    </NotificationContext.Provider>
  );
}
