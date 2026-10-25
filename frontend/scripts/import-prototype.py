"""Extract the team's bundled HTML screens without changing their visual markup.

Usage: python scripts/import-prototype.py <downloaded-prototype.html>
"""
import base64
import argparse
import gzip
import json
import re
from pathlib import Path


def island(document, name):
    return json.loads(document.rsplit(f"__bundler/{name}", 1)[1].split(">", 1)[1].split("</script>", 1)[0])


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("--scenario", type=int, choices=range(1, 8))
parser.add_argument("--references", type=Path, help="Optional directory for browser comparison originals")
args = parser.parse_args()
source = args.source.read_text(encoding="utf-8")
manifest = island(source, "manifest")
board = island(source, "template")
entries = re.findall(r'<h2>(.*?)</h2><iframe src="about:blank#([^"]+)"[^>]*width="(\d+)" height="(\d+)"', board)

names = {
    "Вход": "Login",
    "Главная: нет заявки": "HomeEmpty",
    "Чат: подтверждение заявки": "Chat",
    "Чат: изменение параметров": "ChatEdit",
    "Чат: проверка документов": "ChatSubmitted",
    "Главная: заявка отправлена": "HomeSubmitted",
    "Чат: автоотказ ИИ": "ChatAutoDecline",
    "Главная: нужны документы": "HomeMissingDocs",
    "Чат: на рассмотрении": "ChatReview",
    "Главная: автоотказ, заявка закрыта": "HomeAutoDecline",
    "Чат: недостающие документы": "ChatMissingDocs",
    "Главная: на рассмотрении": "HomeReview",
    "Документы": "Docs",
    "Главная: оффер": "HomeOffer",
    "Главная: контр-предложение": "HomeCounter",
    "Кредиты": "Credits",
    "Главная: отказ, заявка закрыта": "HomeDeclined",
    "Главная: оффер отклонён, заявка закрыта": "HomeOfferRejected",
    "Главная: договор на подписание": "Home",
    "Профиль компании": "Profile",
    "Главная: график платежей": "HomeSchedule",
    "Главная: детали заявки": "HomeModal",
    "Главная: кредит выдан": "HomeIssued",
    "Кредиты: график платежей": "CreditsSchedule",
    "Кредиты: нет кредитов": "CreditsEmpty",
}
screens = {}
analyst_names = {
    "Вход": "Login",
    "Рабочая зона: Все": "Analyst",
    "Вкладка: Новые эскалации": "AnalystNew",
    "Вкладка: Запросы от андеррайтера": "AnalystFromUw",
    "Вкладка: В работе": "AnalystInWork",
    "Запрос документов через ИИ": "RequestDocs",
    "Отправка заключения": "Conclusion",
    "Приём запроса на экспертизу": "Accept",
}
underwriter_names = {
    "Вход": "Login",
    "Рабочая зона: Все": "Workspace",
    "Вкладка: Мои": "Mine",
    "Вкладка: Ждут решения": "Pending",
    "Вкладка: Запросы": "Requests",
    "Запрос документов у клиента": "RequestDocs",
    "Запрос экспертизы": "Expertise",
    "Одобрить": "Approve",
    "Одобрить с изменениями": "Counter",
    "Отказать": "Refuse",
}
admin_names = {
    "Вход": "Login",
    "Все заявки": "All",
    "Вкладка: В работе": "InWork",
    "Вкладка: Закрытые": "Closed",
    "Вкладка: Завершённые": "Done",
    "Заявка: кредит выдан": "DetailDone",
    "Заявка: автоотказ": "DetailDeclined",
}
for label, uuid, width, height in entries:
    scenario = args.scenario if args.scenario else int(label[0])
    if scenario > 7:
        continue
    phase = label.split(" · ", 1)[1] if " · " in label else label
    if scenario == 5:
        name = f"A_{analyst_names[phase]}.dc.html"
    elif scenario == 6:
        name = f"U_{underwriter_names[phase]}.dc.html"
    elif scenario == 7:
        name = f"AD_{admin_names[phase]}.dc.html"
    else:
        name = f"S{scenario}_{names[phase]}.dc.html"
    if name in screens:
        name = f"S{scenario}_{names[phase]}Pre.dc.html"
    asset = manifest[uuid]
    raw = base64.b64decode(asset["data"])
    document = (gzip.decompress(raw) if asset.get("compressed") else raw).decode()
    if args.references:
        args.references.mkdir(parents=True, exist_ok=True)
        (args.references / name).write_text(document, encoding="utf-8")
    template = island(document, "template")
    title = re.search(r"<title>(.*?)</title>", template, re.S).group(1)
    body = re.search(r"<body[^>]*>(.*?)</body>", template, re.S).group(1)
    # Remove only the export runtime; preserve source CSS, content and links.
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.S)
    if scenario == 6:
        # Main.dc.html is absent from this export. Exit to this role's own login.
        body = body.replace('href="Main.dc.html"', 'href="U_Login.dc.html"')
    elif scenario == 7:
        body = body.replace('href="Main.dc.html"', 'href="AD_Login.dc.html"')
    # The DC export replaces native table tags with sc-raw-* placeholders.
    # Restore semantic tables, including native colspan and table layout.
    body = re.sub(
        r"(<\/?)(?:sc-raw-)(table|thead|tbody|tfoot|tr|th|td|caption|colgroup|col)(?=[\s>])",
        r"\1\2",
        body,
    )
    refresh = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>\s*Обновить статус\s*</a>', body)
    auto_next = refresh.group(1) if refresh else None
    body = re.sub(r'<a\b[^>]*>\s*Обновить статус\s*</a>', "", body)
    if name == "S1_ChatSubmitted.dc.html":
        auto_next = "S1_ChatAutoDecline.dc.html"
    elif name == "S2_ChatSubmitted.dc.html":
        auto_next = "S2_ChatMissingDocs.dc.html"
    elif name == "S3_ChatSubmitted.dc.html":
        auto_next = "S3_ChatReview.dc.html"
    elif name == "S4_ChatSubmitted.dc.html":
        auto_next = "S4_ChatReview.dc.html"
    screens[name] = {"title": title, "label": label, "html": body.strip(), "width": int(width), "height": int(height), "auto_next": auto_next}

destination = Path(__file__).resolve().parents[1] / "src/prototype/screens.json"
destination.parent.mkdir(parents=True, exist_ok=True)
links = {href for screen in screens.values() for href in re.findall(r'href="([^"]+)"', screen["html"]) if href.endswith(".dc.html")}
links.update(screen["auto_next"] for screen in screens.values() if screen.get("auto_next"))
missing = sorted(links - screens.keys())
if args.scenario == 5 and "A_Login.dc.html" in screens:
    missing = [name for name in missing if name != "Main.dc.html"]
print(f"Extracted {len(screens)} screens. Unresolved links: {missing}")
if missing:
    raise SystemExit(1)
if args.scenario and destination.exists():
    existing = json.loads(destination.read_text(encoding="utf-8"))
    prefix = "A_" if args.scenario == 5 else "U_" if args.scenario == 6 else "AD_" if args.scenario == 7 else f"S{args.scenario}_"
    existing = {name: screen for name, screen in existing.items() if not name.startswith(prefix)}
    existing.update(screens)
    screens = existing
destination.write_text(json.dumps(screens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
