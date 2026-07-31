import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Client Supabase côté serveur (composants serveur, actions, route handlers).
 *
 * Next.js 16 : `cookies()` est asynchrone — l'accès synchrone a été retiré.
 */
export async function clientServeur() {
  const magasin = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => magasin.getAll(),
        setAll: (aPoser) => {
          try {
            aPoser.forEach(({ name, value, options }) =>
              magasin.set(name, value, options),
            );
          } catch {
            // Appelé depuis un composant serveur : le rafraîchissement de
            // session est déjà assuré par le proxy, on peut ignorer.
          }
        },
      },
    },
  );
}

/** Utilisateur connecté et sa pharmacie, ou `null` si non authentifié. */
export async function membreCourant() {
  const supabase = await clientServeur();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data: membre } = await supabase
    .from("membres")
    .select("pharmacie_id, role, email")
    .eq("id", user.id)
    .single();

  return membre ? { user, ...membre } : { user, pharmacie_id: null, role: null, email: user.email };
}
