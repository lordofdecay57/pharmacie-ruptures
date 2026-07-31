"use server";

import { clientServeur, membreCourant } from "@/lib/supabase/serveur";
import type { EtatStockLigne, LigneStock, ResumeStock } from "@/lib/calculs/stock-rotation";

export interface AnalysePrecedente {
  id: string;
  dateAnalyse: string;
  signatureColonnes: string | null;
  etat: EtatStockLigne[];
}

/**
 * Dernière analyse enregistrée pour la pharmacie — sert de référence à la
 * comparaison « cadencier n+1 » (remplace le fichier local d'état).
 */
export async function chargerAnalysePrecedente(): Promise<AnalysePrecedente | null> {
  const membre = await membreCourant();
  if (!membre?.pharmacie_id) return null;

  const supabase = await clientServeur();
  const { data: analyse } = await supabase
    .from("analyses")
    .select("id, date_analyse, signature_colonnes")
    .eq("pharmacie_id", membre.pharmacie_id)
    .order("cree_le", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!analyse) return null;

  const { data: lignes } = await supabase
    .from("lignes_stock")
    .select("code_cip, nom_produit, stock_min, stock_max")
    .eq("analyse_id", analyse.id);

  return {
    id: analyse.id,
    dateAnalyse: analyse.date_analyse,
    signatureColonnes: analyse.signature_colonnes,
    etat: (lignes ?? []).map((l) => ({
      codeCip: l.code_cip ?? "",
      nomProduit: l.nom_produit,
      stockMin: l.stock_min ?? 0,
      stockMax: l.stock_max ?? 0,
    })),
  };
}

/** Enregistre l'analyse et ses lignes ; renvoie l'issue de l'opération. */
export async function enregistrerAnalyse(entree: {
  dateAnalyse: string;
  signatureColonnes: string;
  parametres: Record<string, unknown>;
  resume: ResumeStock;
  lignes: LigneStock[];
}): Promise<{ ok: boolean; message?: string }> {
  const membre = await membreCourant();
  if (!membre?.pharmacie_id) {
    return { ok: false, message: "Compte non rattaché à une pharmacie." };
  }

  const supabase = await clientServeur();
  const { data: analyse, error: erreurAnalyse } = await supabase
    .from("analyses")
    .insert({
      pharmacie_id: membre.pharmacie_id,
      cree_par: membre.user.id,
      date_analyse: entree.dateAnalyse,
      signature_colonnes: entree.signatureColonnes,
      parametres: entree.parametres,
      resume: entree.resume,
    })
    .select("id")
    .single();

  if (erreurAnalyse || !analyse) {
    return { ok: false, message: erreurAnalyse?.message ?? "Enregistrement refusé." };
  }

  const lignes = entree.lignes.map((l) => ({
    analyse_id: analyse.id,
    code_cip: l.codeCip || null,
    nom_produit: l.nomProduit,
    alerte: l.alerte,
    classe: l.classe,
    stock_actuel: l.stockActuel,
    commande_en_cours: l.commandeEnCours,
    consommation_mois: l.consommationMois,
    tendance: l.tendance,
    variabilite: l.variabilite,
    stock_min: l.stockMin,
    stock_max: l.stockMax,
    stock_min_conseille: l.stockMinConseille,
    qte_a_commander: l.qteACommander,
    motif: l.motif,
    modifie: l.modifie ?? null,
  }));

  // Insertion par lots : un cadencier réel dépasse 3 500 lignes.
  const TAILLE_LOT = 500;
  for (let i = 0; i < lignes.length; i += TAILLE_LOT) {
    const { error } = await supabase
      .from("lignes_stock")
      .insert(lignes.slice(i, i + TAILLE_LOT));
    if (error) return { ok: false, message: error.message };
  }

  return { ok: true };
}
