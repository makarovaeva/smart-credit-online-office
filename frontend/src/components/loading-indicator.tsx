import styles from "./loading-indicator.module.css";

export function LoadingIndicator() {
  return (
    <div className={styles.container} role="status" aria-label="Загрузка кабинета" aria-busy="true">
      <span className={styles.spinner} aria-hidden="true" />
    </div>
  );
}
