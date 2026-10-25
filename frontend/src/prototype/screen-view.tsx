"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type MouseEvent } from "react";
import { useRouter } from "next/navigation";
import screens from "./screens.json";
import { isScreen, routeForScreen, type ScreenName } from "./routes";
import { homeScene, isLogin, useBank } from "./use-bank";
import { bindBank } from "./bind-bank";
import { LoadingIndicator } from "@/components/loading-indicator";
import { useBankContext } from "./bank-provider";
import styles from "./screen-view.module.css";
import { updateMarkup } from "./update-markup";

const storageKey = "credit-ui-screens-v1";
const subscribeMounted = () => () => {};
const clientMounted = () => true;
const serverMounted = () => false;
function cabinet(url: string) {
  const path = url.split("?")[0];
  if (["/applications", "/chat", "/documents", "/credits", "/profile"].includes(path)) return "client";
  return /^\/staff\/(analyst|underwriter|admin)(?:\/|$)/.exec(path)?.[1];
}

function remembered(): Record<string, ScreenName> {
  try { return JSON.parse(sessionStorage.getItem(storageKey) ?? "{}"); }
  catch { return {}; }
}

export function ScreenView({ initialName }: { initialName: ScreenName }) {
  const router = useRouter();
  const { state: cached } = useBankContext();
  const resolveCached = useCallback((next: ScreenName) => {
    if (!cached.user) return next;
    if (next.startsWith("S") && next.includes("_Home") && !next.includes("Modal") && !next.includes("Schedule")) return homeScene(cached.application);
    if (next.startsWith("S") && next.includes("Credits") && !next.includes("Schedule")) return cached.loans.length ? "S4_Credits.dc.html" : "S4_CreditsEmpty.dc.html";
    return next;
  }, [cached.user, cached.application, cached.loans]);
  const [name, setName] = useState(() => resolveCached(initialName));
  const content = useRef<HTMLDivElement>(null);
  const mounted = useSyncExternalStore(subscribeMounted, clientMounted, serverMounted);
  const remember = useCallback((next: ScreenName) => {
    try { sessionStorage.setItem(storageKey, JSON.stringify({ ...remembered(), [routeForScreen(next)]: next })); }
    catch { /* The UI also works when browser storage is disabled. */ }
  }, []);

  const transition = useCallback((next: ScreenName, replace = false) => {
    let url = routeForScreen(next);
    if (next.startsWith("AD_Detail")) {
      try { const id = sessionStorage.getItem("credit-selected-application"); if (id && /^[0-9a-f-]{36}$/.test(id)) url = `/staff/admin/applications/${id}`; } catch {}
    }
    remember(next);
    const current = window.location.pathname + window.location.search;
    // All sections of a cabinet use the same renderer. Keep it mounted while
    // updating Next's integrated history, avoiding a second render of the route.
    if (current === url || (cabinet(url) && cabinet(current) === cabinet(url))) {
      if (replace || current !== url || window.history.state?.creditUiScreen !== next) {
        window.history[replace ? "replaceState" : "pushState"]({ creditUiScreen: next }, "", url);
      }
    } else router[replace ? "replace" : "push"](url, { scroll: false });
    setName(next);
  }, [remember, router]);
  const bank = useBank(name, transition);

  useEffect(() => {
    const urlId = /^\/staff\/admin\/applications\/([0-9a-f-]{36})$/.exec(window.location.pathname)?.[1];
    if (urlId) { try { sessionStorage.setItem("credit-selected-application", urlId); } catch {} }
    const canonical = routeForScreen(initialName);
    const current = window.location.pathname + window.location.search;
    const saved = remembered()[canonical];
    // Explicit legacy links must open their exact frame; clean links may restore a local UI state.
    const restored = current === canonical && isScreen(saved) && routeForScreen(saved) === canonical ? saved : initialName;
    // sessionStorage and legacy URL normalization are only available after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    transition(resolveCached(restored), true);
    const pop = (event: PopStateEvent) => {
      const next = event.state?.creditUiScreen;
      if (isScreen(next)) {
        setName(next); remember(next);
        const id = /^\/staff\/admin\/applications\/([0-9a-f-]{36})$/.exec(window.location.pathname)?.[1];
        void bank.refresh(id);
      }
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
    // Restore on navigation; background data updates must not reset a dialog or tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialName, remember, transition, bank.refresh]);

  useEffect(() => { document.title = screens[name].title; }, [name]);

  const html = useMemo(() => {
    const linked = screens[name].html.replace(/href="([^"]+)"/g, (attribute, target: string) => {
    const next = target === "Main.dc.html" ? "A_Login.dc.html" : target;
    return isScreen(next) ? `href="${routeForScreen(next).replaceAll("&", "&amp;")}" data-screen="${next}"` : attribute;
    });
    return mounted || bank.user ? bindBank(linked, name, bank) : linked;
  }, [name, mounted, bank]);

  const authenticated = !!bank.user;
  const [initialHtml] = useState(html);
  useLayoutEffect(() => {
    if (!content.current) return;
    const template = document.createElement("template");
    template.innerHTML = html;
    updateMarkup(content.current, template.content);
  }, [html, authenticated]);

  useLayoutEffect(() => {
    if (!authenticated || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const panel = content.current?.querySelector("main, section.b");
    const animation = panel?.animate([{ opacity: 0.88 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
    return () => animation?.cancel();
  }, [name, authenticated]);

  async function navigate(event: MouseEvent<HTMLDivElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const root = event.currentTarget;
    const element = (event.target as Element).closest<HTMLElement>("a, button, tr[data-application-id]");
    if (!element) return;
    if (element.getAttribute("aria-disabled") === "true") { event.preventDefault(); return; }
    const row = element.closest<HTMLElement>("tr[data-application-id]");
    if (row?.dataset.applicationId) {
      event.preventDefault();
      await bank.select(row.dataset.applicationId);
      if (name.startsWith("AD_")) {
        const item = bank.applications.find(a => a.id === row.dataset.applicationId);
        transition(item?.status === "closed" ? "AD_DetailDeclined.dc.html" : "AD_DetailDone.dc.html");
        window.history.replaceState(window.history.state, "", `/staff/admin/applications/${row.dataset.applicationId}`);
      }
      return;
    }
    const anchor = element.closest<HTMLAnchorElement>("a[data-screen]");
    const next = anchor?.dataset.screen;
    if (element.tagName === "A" && !isScreen(next) && element.getAttribute("href") !== "#") return;
    event.preventDefault();
    if (isScreen(next) && !isLogin(next) && element.closest("aside")) {
      transition(resolveCached(next));
      window.scrollTo(0, 0);
      return;
    }
    if (bank.busy) return;
    const handled = await bank.action(element.textContent?.trim() ?? "", root, isScreen(next) ? next : undefined);
    if (handled || !isScreen(next)) return;
    const resolved = next.startsWith("S") && next.includes("_Home") && !next.includes("Modal") && !next.includes("Schedule") ? homeScene(bank.application) : next;
    transition(resolved);
    // Only route changes reset scroll; opening a dialog retains its position.
    if (routeForScreen(next) !== routeForScreen(name)) window.scrollTo(0, 0);
  }

  const protectedPage = !isLogin(name);
  return <>
    <div className={styles.notices}>
      {bank.error && <div role="alert" className={`${styles.notice} ${styles.error}`}>{bank.error}<button onClick={() => void bank.refresh()} style={{ marginLeft: 16 }}>Повторить загрузку</button></div>}
      {bank.warnings.length > 0 && protectedPage && <div role="status" className={`${styles.notice} ${styles.warning}`}>{bank.warnings.join(" · ")}</div>}
    </div>
    {protectedPage && !bank.user ? <LoadingIndicator /> : <div className={styles.screen} ref={content} data-screen-name={name} data-api-ready={mounted} aria-busy={bank.busy} onClick={navigate} onChange={event => { const input = event.target as HTMLInputElement; if (input.dataset.upload && input.files?.[0]) void bank.upload(input.files[0]); }} dangerouslySetInnerHTML={{ __html: initialHtml }} />}
  </>;
}
