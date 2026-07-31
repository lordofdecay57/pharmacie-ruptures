import { redirect } from "next/navigation";

/** L'accueil renvoie vers l'analyse (le proxy gère l'authentification). */
export default function Accueil() {
  redirect("/analyse");
}
