# Document Agent

Модуль для проверки пакета документов по кредитной заявке: читает TXT/Markdown и PDF с текстовым слоем, классифицирует документы, извлекает ИНН, даты и финансовые показатели через LLM и проверяет результаты Python-правилами. Возвращает комплектность и **черновик** запроса недостающих документов.

**Кредитные решения, требования к документам и статусы заявки определяет backend, не LLM.** OCR сканов пока нет; проверка цитат не подтверждает подлинность документа.

## Запуск из корня репозитория

```powershell
# Тесты
python -m unittest discover -s ml/document_agent/tests -t . -p 'test_*.py' -v

# Без API, с mock-ответами
python -m ml.document_agent.main `
  --mode backend --parser file --provider mock `
  --file 'doc-bank-1=ml/document_agent/examples/bank_statement.txt' `
  --input ml/document_agent/examples/backend_input.json `
  --out ml/document_agent/data/mock.json
```

## Подключить свою LLM

Поддерживается **любой OpenAI-compatible Chat Completions API**: GLM/Z.ai, Ollama, vLLM и совместимые шлюзы. Для принципиально другого API нужен адаптер в `providers.py`.

Укажите базовый URL **без** `/chat/completions` и ID модели. Ключ вводится скрыто и не сохраняется в файлы:

```powershell
$env:DOCUMENT_LLM_BASE_URL = 'https://api.z.ai/api/paas/v4'  # свой URL
$env:DOCUMENT_LLM_MODEL = 'glm-4.7-flash'                 # своя модель
$secret = Read-Host 'API key' -AsSecureString
try {
  $env:DOCUMENT_LLM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
  Remove-Variable secret

  python -m ml.document_agent.main `
    --mode backend --parser file --provider compatible --extract-fields `
    --file 'doc-bank-1=ml/document_agent/examples/bank_statement.txt' `
    --input ml/document_agent/examples/backend_input.json `
    --out ml/document_agent/data/llm.json
}
finally {
  Remove-Variable secret -ErrorAction SilentlyContinue
  Remove-Item Env:DOCUMENT_LLM_API_KEY -ErrorAction SilentlyContinue
  Remove-Item Env:DOCUMENT_LLM_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:DOCUMENT_LLM_MODEL -ErrorAction SilentlyContinue
}
```

Для локальной Ollama пример URL: `http://127.0.0.1:11434/v1`, а модель — её установленное имя. Для PDF с текстовым слоем нужен `pypdf` (`uv run --no-project --with pypdf python -m ml.document_agent.main ...`).

Дополнительная проверка извлечения полей: `python -m ml.document_agent.field_extractor --provider mock --cases ml/document_agent/examples/realistic/cases.json --out ml/document_agent/data/fields.json` (замените `mock` на `compatible` с настроенным API).

**Безопасность:** не отправляйте реальные банковские документы стороннему API без разрешения. Не коммитьте ключи и результаты: `ml/document_agent/data/` исключена через `.gitignore`.
