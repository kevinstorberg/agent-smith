import { useNotification } from '../context/useNotification';

export function NotificationBar() {
  const { notifications, dismiss } = useNotification();
  if (notifications.length === 0) return null;

  return (
    <div className="notification-bar">
      {notifications.map(n => (
        <div key={n.id} className={`notification notification-${n.type}`}>
          <span className="notification-message">{n.message}</span>
          <button
            className="notification-dismiss"
            onClick={() => dismiss(n.id)}
            aria-label="Dismiss notification"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}
