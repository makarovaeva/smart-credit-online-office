import { redirect } from "next/navigation";

export const metadata = { title: "Главная — нет заявки" };

export default function Home() {
  redirect("/applications");
}
