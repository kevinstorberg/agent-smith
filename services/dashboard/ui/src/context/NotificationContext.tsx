import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

type NotificationType = 'success' | 'error' | 'warning' | 'info';

interface Notification {
  id: string;
  message: string;
  type: NotificationType;
}

interface NotificationContextValue {
  notifications: Notification[];
  notify: (message: string, type: NotificationType) => void;
  dismiss: (id: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

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

export function useNotification(): NotificationContextValue {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotification must be used within a NotificationProvider');
  }
  return context;
}
