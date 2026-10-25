import screens from "./screens.json";

export type ScreenName = keyof typeof screens;

const employeeRoutes: Record<string, string> = {
  A_Login: "/staff/login?role=analyst",
  U_Login: "/staff/login?role=underwriter",
  AD_Login: "/staff/login?role=admin",
};

export function isScreen(name: unknown): name is ScreenName {
  return typeof name === "string" && Object.prototype.hasOwnProperty.call(screens, name);
}

export function routeForScreen(name: ScreenName): string {
  const key = name.replace(".dc.html", "");
  if (employeeRoutes[key]) return employeeRoutes[key];
  if (key.startsWith("AD_Detail")) return "/staff/admin/applications/details";
  if (key.startsWith("AD_")) return "/staff/admin";
  if (key.startsWith("A_")) return "/staff/analyst";
  if (key.startsWith("U_")) return "/staff/underwriter";
  const match = /^S([1-4])_(.+)$/.exec(key);
  if (!match) throw new Error(`No route for ${name}`);
  const step = match[2];
  const path = step === "Login" ? "/login"
    : step.startsWith("Chat") ? "/chat"
    : step.startsWith("Docs") ? "/documents"
    : step.startsWith("Credits") ? "/credits"
    : step.startsWith("Profile") ? "/profile"
    : "/applications";
  return path;
}

export function initialScreen(path: string, query: Record<string, string | string[] | undefined>): ScreenName | null {
  const scenario = typeof query.scenario === "string" && /^[1-4]$/.test(query.scenario) ? query.scenario : "1";
  const suffixes: Record<string, string> = {
    "/login": "Login", "/applications": "HomeEmpty", "/chat": "Chat",
    "/documents": scenario === "4" ? "DocsPre" : "Docs",
    "/credits": scenario === "4" ? "CreditsEmpty" : "Credits",
    "/profile": scenario === "4" ? "ProfilePre" : "Profile",
  };
  if (suffixes[path]) return `S${scenario}_${suffixes[path]}.dc.html` as ScreenName;
  if (path === "/staff/login") return query.role === "admin" ? "AD_Login.dc.html"
    : query.role === "underwriter" ? "U_Login.dc.html" : "A_Login.dc.html";
  const staff: Record<string, ScreenName> = {
    "/staff/analyst": "A_Analyst.dc.html",
    "/staff/underwriter": "U_Workspace.dc.html",
    "/staff/admin": "AD_All.dc.html",
    "/staff/admin/applications/details": "AD_DetailDone.dc.html",
  };
  if (/^\/staff\/admin\/applications\/[0-9a-f-]{36}$/.test(path)) return "AD_DetailDone.dc.html";
  return staff[path] ?? null;
}

export function legacyScreen(path: string): ScreenName | null {
  const name = path.replace(/^\//, "");
  return name === "Main.dc.html" ? "A_Login.dc.html" : isScreen(name) ? name : null;
}

export const canonicalPaths = [
  "/applications", "/chat", "/documents", "/credits", "/profile",
  "/staff/login", "/staff/analyst", "/staff/underwriter", "/staff/admin",
  "/staff/admin/applications/details",
];
