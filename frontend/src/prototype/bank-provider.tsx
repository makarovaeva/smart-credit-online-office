"use client";

import { createContext, useContext, useRef, useState, type ReactNode } from "react";
import type { ObjectData } from "@/lib/api";

export type BankState = {
  user: ObjectData | null; applications: ObjectData[]; application: ObjectData | null;
  detail: ObjectData | null; products: ObjectData[]; loans: ObjectData[];
  offer: ObjectData | null; contract: ObjectData | null; company: ObjectData | null;
  documents: ObjectData[]; requests: ObjectData[]; warnings: string[];
  loading: boolean; busy: boolean; error: string;
};
export const empty: BankState = { user: null, applications: [], application: null, detail: null, products: [], loans: [], offer: null, contract: null, company: null, documents: [], requests: [], warnings: [], loading: false, busy: false, error: "" };

function useBankStore() {
  const [state, setState] = useState<BankState>(empty);
  const [draft, setDraft] = useState({ amount: "3000000", term: 24, purpose: "Пополнение оборотных средств", collateral: "Без залога" });
  const drafting = useRef(false);
  return { state, setState, draft, setDraft, drafting };
}

const BankContext = createContext<ReturnType<typeof useBankStore> | null>(null);

// Lives in the root layout: client navigation retains the session and loaded data.
export function BankProvider({ children }: { children: ReactNode }) {
  const store = useBankStore();
  return <BankContext.Provider value={store}>{children}</BankContext.Provider>;
}

export function useBankContext() {
  const store = useContext(BankContext);
  if (!store) throw new Error("BankProvider is required");
  return store;
}
