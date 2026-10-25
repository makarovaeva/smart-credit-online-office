import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PrototypeScreen, getScreen } from "@/prototype/screen";
import { initialScreen, legacyScreen } from "@/prototype/routes";

type Props = {
  params: Promise<{ path: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

async function resolveScreen({ params, searchParams }: Props) {
  const path = `/${(await params).path.join("/")}`;
  return legacyScreen(path) ?? initialScreen(path, await searchParams);
}

export async function generateMetadata(props: Props): Promise<Metadata> {
  const name = await resolveScreen(props);
  return { title: name ? getScreen(name)?.title : "Страница не найдена" };
}

export default async function Page(props: Props) {
  const name = await resolveScreen(props);
  if (!name) notFound();
  return <PrototypeScreen name={name} />;
}
