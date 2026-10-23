# Данные

Каталог монтируется в контейнер бэкенда как `/data` (только чтение).

Датасет профилей заёмщиков от ML кладётся сюда, путь указывается в `.env`:

```
BORROWER_DATASET_PATH=/data/borrowers.jsonl
```

Формат — Borrower Profile из [`docs/credit_mmb_data_model_updated.md`](../docs/credit_mmb_data_model_updated.md), описание — [`docs/external-sources.md`](../docs/external-sources.md).
