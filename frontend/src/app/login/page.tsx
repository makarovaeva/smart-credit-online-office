import { PrototypeScreen } from "@/prototype/screen";
import { initialScreen } from "@/prototype/routes";

export const metadata = { title: "Вход — клиент" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <PrototypeScreen name={initialScreen("/login", await searchParams)!} />;
}
