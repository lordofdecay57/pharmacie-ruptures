/**
 * Fonctions PURES partagées entre les deux modules métier.
 *
 * Portage fidèle de `commun.py` (application Streamlit locale) : mêmes
 * règles, mêmes seuils, mêmes cas limites. Ce module ne connaît ni les
 * ruptures fournisseurs ni la politique de stock min/max — il fournit les
 * briques génériques : parsing, statistiques de consommation.
 */

// ---------------------------------------------------------------------------
// Constantes de calcul partagées
// ---------------------------------------------------------------------------

/** Convention rotation mensuelle → journalière. */
export const JOURS_PAR_MOIS = 30;
/** Lissage exponentiel : poids du mois le plus récent. */
export const ALPHA_LISSAGE = 0.4;
/** ±20 % entre demande récente et référence → ↗ / ↘. */
export const SEUIL_TENDANCE = 0.2;
/** CV : < 0,3 stable · < 0,7 variable · au-delà forte variabilité. */
export const SEUILS_VARIABILITE: readonly [number, number] = [0.3, 0.7];

/** Période de calcul de la consommation mensuelle. */
export type PeriodeRotation = "annuelle" | "6mois" | "3mois" | "1mois" | "lissee";

// ---------------------------------------------------------------------------
// Normalisation / parsing
// ---------------------------------------------------------------------------

/** Majuscules, sans accents, ponctuation → espace, espaces réduits. */
export function normaliserLibelle(libelle: unknown): string {
  if (libelle === null || libelle === undefined) return "";
  if (typeof libelle === "number" && Number.isNaN(libelle)) return "";
  return String(libelle)
    .normalize("NFKD")
    // Retire les diacritiques (équivalent de unicodedata.combining).
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Ne garde que les chiffres (gère les CIP lus en flottant : « 3400930.0 »).
 *
 * Un CIP « 0 » (placeholder fréquent dans les exports) est traité comme
 * ABSENT — sinon deux produits distincts à CIP 0 se rapprocheraient à tort.
 */
export function normaliserCip(cip: unknown): string {
  if (cip === null || cip === undefined) return "";
  if (typeof cip === "number" && Number.isNaN(cip)) return "";
  let s = String(cip).trim();
  if (/^\d+\.0+$/.test(s)) s = s.split(".")[0]; // flottant Excel → entier
  s = s.replace(/\D/g, "");
  return s.replace(/0/g, "") === "" ? "" : s;
}

/**
 * Formes équivalentes d'un CIP pour l'appariement entre fichiers.
 *
 * Les exports mélangent CIP13 et CIP7 : le CIP13 médicament français
 * (13 chiffres, préfixe 3400) contient le CIP7 en positions 6-12
 * (ex. 3400932300778 → 3230077, Titanoréine). Les autres EAN13
 * (parapharmacie) restent tels quels.
 */
export function variantesCip(cip: string): string[] {
  if (!cip) return [];
  const formes = [cip];
  if (cip.length === 13 && cip.startsWith("3400")) {
    formes.push(cip.slice(5, 12)); // CIP7 embarqué dans le CIP13
  }
  return formes;
}

/** Nombre robuste : virgule décimale française, espaces, vide → 0. */
export function parserNombre(val: unknown): number {
  if (val === null || val === undefined) return 0;
  if (typeof val === "number") return Number.isNaN(val) ? 0 : val;
  // Espaces ordinaires ET insécables (séparateurs de milliers).
  const s = String(val).trim().replace(/[\s ]/g, "").replace(",", ".");
  if (!s) return 0;
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Date robuste, formats français en priorité. `null` si illisible ou vide.
 *
 * Renvoie une date « civile » (minuit local) pour éviter les décalages de
 * fuseau lors des comparaisons jour à jour.
 */
export function parserDate(val: unknown): Date | null {
  if (val === null || val === undefined) return null;
  if (val instanceof Date) return Number.isNaN(val.getTime()) ? null : val;
  const s = String(val).trim();
  if (!s || ["nan", "nat", "-", "?"].includes(s.toLowerCase())) return null;

  const civile = (a: number, m: number, j: number): Date | null => {
    const d = new Date(a, m - 1, j);
    // Rejette les dates « rattrapées » par JS (ex. 31/02 → 03/03).
    if (d.getFullYear() !== a || d.getMonth() !== m - 1 || d.getDate() !== j) {
      return null;
    }
    return d;
  };

  // jj/mm/aaaa · jj/mm/aa · jj-mm-aaaa · jj.mm.aaaa
  let m = s.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$/);
  if (m) {
    const jour = Number(m[1]);
    const mois = Number(m[2]);
    let annee = Number(m[3]);
    // Année sur 2 chiffres : convention pivot du siècle courant.
    if (m[3].length === 2) annee += annee < 70 ? 2000 : 1900;
    return civile(annee, mois, jour);
  }
  // aaaa-mm-jj (ISO)
  m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return civile(Number(m[1]), Number(m[2]), Number(m[3]));
  // jj/mm sans année → année en cours
  m = s.match(/^(\d{1,2})[/\-](\d{1,2})$/);
  if (m) {
    return civile(new Date().getFullYear(), Number(m[2]), Number(m[1]));
  }
  return null;
}

// ---------------------------------------------------------------------------
// Statistiques de consommation
// ---------------------------------------------------------------------------

/**
 * Tronque les zéros de TÊTE d'une série mensuelle chronologique.
 *
 * Un produit référencé en cours de période affiche des mois à 0 AVANT sa
 * première vente : ce n'est pas de la demande nulle, c'est « pas encore au
 * catalogue ». Les inclure dans une moyenne divise la rotation des produits
 * récents et fait sous-dimensionner leur stock. Série entièrement nulle :
 * inchangée.
 */
export function depuisPremiereVente(valeurs: number[]): number[] {
  const premiere = valeurs.findIndex((v) => v !== 0);
  return premiere === -1 ? valeurs : valeurs.slice(premiere);
}

/**
 * Rotation mensuelle estimée.
 *
 * `ventes` : valeurs mensuelles en ordre CHRONOLOGIQUE (la plus récente en
 * dernier). Les mois à 0 AVANT la première vente sont exclus du calcul.
 */
export function calculerRotationMensuelle(
  ventes: unknown[],
  periode: PeriodeRotation = "annuelle",
): number {
  let valeurs = depuisPremiereVente(ventes.map(parserNombre));
  if (valeurs.length === 0) return 0;

  if (periode === "1mois") return valeurs[valeurs.length - 1];
  if (periode === "6mois") valeurs = valeurs.slice(-6);
  else if (periode === "3mois") valeurs = valeurs.slice(-3);
  else if (periode === "lissee") {
    let lisse = valeurs[0];
    for (const v of valeurs.slice(1)) {
      lisse = ALPHA_LISSAGE * v + (1 - ALPHA_LISSAGE) * lisse;
    }
    return lisse;
  }
  return valeurs.reduce((a, b) => a + b, 0) / valeurs.length;
}

/**
 * Corrige les mois à 0 vente ENCADRÉS de mois actifs.
 *
 * Un 0 entre deux mois vendeurs signifie « produit en rupture », pas
 * « personne n'en voulait » : le laisser écrase la rotation et fait
 * SOUS-commander précisément les produits qui ont déjà manqué. Les zéros
 * sont remplacés par interpolation linéaire entre les mois actifs qui les
 * encadrent. Les zéros en DÉBUT ou FIN de période sont conservés
 * (lancement, arrêt de commercialisation, rupture en cours).
 */
export function corrigerFauxZeros(
  ventes: unknown[],
): { corrigees: number[]; nbCorriges: number } {
  const valeurs = ventes.map(parserNombre);
  const corrigees = [...valeurs];
  let nb = 0;
  let i = 0;
  while (i < valeurs.length) {
    if (valeurs[i] === 0) {
      let j = i;
      while (j < valeurs.length && valeurs[j] === 0) j += 1;
      if (i > 0 && j < valeurs.length) {
        // Encadré de mois actifs : interpolation linéaire.
        const gauche = valeurs[i - 1];
        const droite = valeurs[j];
        for (let k = 0; k < j - i; k += 1) {
          corrigees[i + k] = gauche + ((droite - gauche) * (k + 1)) / (j - i + 1);
          nb += 1;
        }
      }
      i = j;
    } else {
      i += 1;
    }
  }
  return { corrigees, nbCorriges: nb };
}

/** Couverture actuelle en jours. Stock ≤ 0 → 0 ; rotation nulle → +∞. */
export function calculerStockJours(
  stockActuel: number,
  rotationMensuelle: number,
): number {
  if (stockActuel <= 0) return 0;
  const rotationJournaliere = rotationMensuelle / JOURS_PAR_MOIS;
  if (rotationJournaliere <= 0) return Infinity;
  return stockActuel / rotationJournaliere;
}

/**
 * Tendance de la demande, en ordre chronologique (récent en dernier).
 *
 * - ≥ 4 mois de recul : moyenne des 3 derniers mois vs moyenne globale ;
 * - 2-3 mois (cadenciers courts) : dernier mois vs moyenne des précédents ;
 * - < 2 mois ou demande nulle : « → stable ».
 */
export function calculerTendance(
  ventes: unknown[],
  seuil: number = SEUIL_TENDANCE,
): string {
  if (ventes.length < 2) return "→ stable";
  let reference: number;
  let recente: number;
  if (ventes.length >= 4) {
    reference = calculerRotationMensuelle(ventes, "annuelle");
    recente = calculerRotationMensuelle(ventes, "3mois");
  } else {
    reference = calculerRotationMensuelle(ventes.slice(0, -1), "annuelle");
    recente = parserNombre(ventes[ventes.length - 1]);
  }
  if (reference <= 0) return "→ stable";
  const ecart = (recente - reference) / reference;
  if (ecart >= seuil) return "↗ hausse";
  if (ecart <= -seuil) return "↘ baisse";
  return "→ stable";
}

/**
 * Classement ABC (loi de Pareto) sur les volumes de ventes.
 *
 * A = les plus gros vendeurs jusqu'à 80 % du volume cumulé, B = 80-95 %,
 * C = le reste (dont les volumes nuls). Le plus gros vendeur est TOUJOURS A
 * (le cumul est évalué AVANT de l'ajouter).
 */
export function classerAbc(volumes: unknown[]): ("A" | "B" | "C")[] {
  const valeurs = volumes.map(parserNombre);
  const classes: ("A" | "B" | "C")[] = valeurs.map(() => "C");
  const total = valeurs.filter((v) => v > 0).reduce((a, b) => a + b, 0);
  if (total <= 0) return classes;

  const ordre = valeurs
    .map((v, i) => ({ v, i }))
    .sort((a, b) => b.v - a.v)
    .map((o) => o.i);

  let cumul = 0;
  for (const i of ordre) {
    if (valeurs[i] <= 0) continue;
    const partAvant = cumul / total;
    classes[i] = partAvant < 0.8 ? "A" : partAvant < 0.95 ? "B" : "C";
    cumul += valeurs[i];
  }
  return classes;
}

/**
 * Coefficient de variation σ/μ de la demande (`null` si non calculable).
 *
 * Mesure la RÉGULARITÉ des ventes : proche de 0 = très régulier, > 1 = très
 * erratique. Le recul se compte depuis la première vente. Moins de 3 mois de
 * recul ou demande nulle → `null`.
 */
export function coefficientVariation(ventes: unknown[]): number | null {
  const valeurs = depuisPremiereVente(ventes.map(parserNombre));
  if (valeurs.length < 3) return null;
  const moyenne = valeurs.reduce((a, b) => a + b, 0) / valeurs.length;
  if (moyenne <= 0) return null;
  const variance =
    valeurs.reduce((acc, v) => acc + (v - moyenne) ** 2, 0) / valeurs.length;
  return Math.sqrt(variance) / moyenne;
}

/** Variabilité de la demande, en libellé lisible (vide si inconnue). */
export function variabiliteDemande(ventes: unknown[]): string {
  const cv = coefficientVariation(ventes);
  if (cv === null) return "";
  const pct = `${Math.round(cv * 100)}%`;
  if (cv < SEUILS_VARIABILITE[0]) return `🟢 stable (CV ${pct})`;
  if (cv < SEUILS_VARIABILITE[1]) return `🟡 variable (CV ${pct})`;
  return `🔴 forte (CV ${pct})`;
}

/**
 * Signale un pic saisonnier probable : un mois ≥ 2× la moyenne.
 *
 * Nécessite au moins 6 mois de recul DEPUIS LA PREMIÈRE VENTE pour
 * distinguer saison et hasard. `nomsMois` : libellés alignés sur `ventes`.
 */
export function picSaisonnier(ventes: unknown[], nomsMois: string[]): string {
  const completes = ventes.map(parserNombre);
  const valeurs = depuisPremiereVente(completes);
  const decalage = completes.length - valeurs.length;
  if (valeurs.length < 6) return "";
  const moyenne = valeurs.reduce((a, b) => a + b, 0) / valeurs.length;
  if (moyenne <= 0) return "";
  const maximum = Math.max(...valeurs);
  if (maximum < 2 * moyenne) return "";
  let nom = "";
  if (nomsMois.length === completes.length) {
    nom = String(nomsMois[decalage + valeurs.indexOf(maximum)])
      .replace("Ventes", "")
      .trim();
  }
  return `📈 pic ${nom}`.trim();
}

// ---------------------------------------------------------------------------
// Détection automatique des colonnes (proposition, confirmée dans l'UI)
// ---------------------------------------------------------------------------

const MOTS_CLES: Record<string, string[]> = {
  libelle: ["libell", "produit", "design", "article", "nom", "denomination"],
  cip: ["cip", "code produit", "code article", "ean", "acl"],
  stock: ["stock", "qte dispo", "quantite dispo", "disponible"],
  date_reappro: [
    "reappro", "reapprovisionnement", "retour", "dispo le", "date",
  ],
  conditionnement: ["conditionnement", "colisage", "pcb", "unite de vente"],
  commande_en_cours: [
    "commande en cours", "qte commandee", "cde en cours", "en commande",
  ],
  peremption: ["peremption", "dluo", "date de peremption", "date limite"],
};

function sansAccents(s: string): string {
  return s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Propose la colonne la plus probable pour un rôle donné (ou `null`). */
export function detecterColonne(colonnes: string[], role: string): string | null {
  for (const mot of MOTS_CLES[role] ?? []) {
    for (const col of colonnes) {
      if (sansAccents(String(col)).includes(sansAccents(mot))) return col;
    }
  }
  return null;
}

/** Propose les colonnes de ventes mensuelles (mois ou mot-clé « vente »). */
export function detecterColonnesVentes(colonnes: string[]): string[] {
  const mois = [
    "janv", "fevr", "mars", "avr", "mai", "juin",
    "juil", "aout", "sept", "oct", "nov", "dec",
  ];
  return colonnes.filter((col) => {
    const c = sansAccents(String(col));
    return c.includes("vente") || c.includes("sortie") || mois.some((m) => c.includes(m));
  });
}
