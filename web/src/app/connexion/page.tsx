"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { clientNavigateur } from "@/lib/supabase/navigateur";

/** Connexion / création de compte pour l'équipe de la pharmacie. */
export default function Connexion() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [inscription, setInscription] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  async function soumettre(e: React.FormEvent) {
    e.preventDefault();
    setEnCours(true);
    setMessage(null);
    const supabase = clientNavigateur();

    const { error } = inscription
      ? await supabase.auth.signUp({ email, password: motDePasse })
      : await supabase.auth.signInWithPassword({ email, password: motDePasse });

    setEnCours(false);
    if (error) {
      setMessage(error.message);
      return;
    }
    if (inscription) {
      setMessage(
        "Compte créé. Si la confirmation par e-mail est activée, validez le " +
          "lien reçu avant de vous connecter.",
      );
      return;
    }
    router.push("/analyse");
    router.refresh();
  }

  return (
    <main className="min-h-dvh flex items-center justify-center bg-stone-50 p-6">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl bg-gradient-to-br from-teal-700 to-teal-600 p-6 text-white">
          <h1 className="text-xl font-bold">💊 Pilotage pharmacie</h1>
          <p className="mt-1 text-sm text-teal-50">
            Stock en rotation &amp; ruptures fournisseurs
          </p>
        </div>

        <form
          onSubmit={soumettre}
          className="mt-4 space-y-4 rounded-2xl border border-stone-200 bg-white p-6"
        >
          <h2 className="font-semibold text-stone-900">
            {inscription ? "Créer un compte" : "Connexion"}
          </h2>

          <label className="block text-sm">
            <span className="text-stone-600">Adresse e-mail</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 outline-none focus:border-teal-600"
            />
          </label>

          <label className="block text-sm">
            <span className="text-stone-600">Mot de passe</span>
            <input
              type="password"
              required
              minLength={6}
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 outline-none focus:border-teal-600"
            />
          </label>

          {message && (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              {message}
            </p>
          )}

          <button
            type="submit"
            disabled={enCours}
            className="w-full rounded-lg bg-teal-700 py-2 font-medium text-white hover:bg-teal-800 disabled:opacity-50"
          >
            {enCours ? "…" : inscription ? "Créer le compte" : "Se connecter"}
          </button>

          <button
            type="button"
            onClick={() => { setInscription(!inscription); setMessage(null); }}
            className="w-full text-sm text-teal-700 underline"
          >
            {inscription
              ? "J'ai déjà un compte"
              : "Créer un compte pour l'équipe"}
          </button>
        </form>
      </div>
    </main>
  );
}
