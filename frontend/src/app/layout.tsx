import type { Metadata } from "next";
import { BankProvider } from "@/prototype/bank-provider";

export const metadata: Metadata = { title: "Кредитный кабинет ММБ — прототип" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ru"><body><BankProvider>{children}</BankProvider></body></html>;
}
