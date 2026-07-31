import { chargerAnalysePrecedente } from "./actions";
import { membreCourant } from "@/lib/supabase/serveur";
import Analyseur from "./analyseur";

export const metadata = { title: "Analyse — Pilotage pharmacie" };

/** Page principale : charge la dernière analyse puis délègue au client. */
export default async function PageAnalyse() {
  const membre = await membreCourant();
  const precedente = await chargerAnalysePrecedente();

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="rounded-2xl bg-gradient-to-br from-teal-700 to-teal-600 p-6 text-white">
        <h1 className="text-2xl font-bold">💊 Pilotage pharmacie</h1>
        <p className="mt-1 text-sm text-teal-50">
          Stock en rotation — stock min / max par produit à partir du cadencier.
        </p>
        <p className="mt-3 text-xs text-teal-100">
          Connecté : {membre?.email ?? "—"}
          {precedente && ` · dernière analyse : ${precedente.dateAnalyse}`}
        </p>
      </header>

      <div className="mt-6">
        <Analyseur precedente={precedente} />
      </div>
    </main>
  );
}
