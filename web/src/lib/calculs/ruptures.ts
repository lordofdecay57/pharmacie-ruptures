/**
 * Module 2 — Gestion des ruptures fournisseurs.
 *
 * Portage fidèle de `moteur_ruptures.py` : croise le cadencier de la
 * pharmacie avec la liste de ruptures du fournisseur principal (GPNC) et
 * celle du dépanneur (UNIPHARMA), et produit les onglets de décision.
 *
 * Règle d'apparition STRICTE, sans marge : un produit n'apparaît que si son
 * stock (en jours) est INFÉRIEUR au délai avant réapprovisionnement — ou à
 * 30 jours de couverture quand aucune date n'est annoncée.
 *
 * ISOLATION : ce module ne connaît pas la politique de stock min/max
 * (stock-rotation.ts). Les deux ne se croisent que via `commun.ts`.
 */

import {
  JOURS_PAR_MOIS,
  calculerRotationMensuelle,
  calculerStockJours,
  calculerTendance,
  classerAbc,
  corrigerFauxZeros,
  normaliserCip,
  normaliserLibelle,
  parserDate,
  parserNombre,
  variantesCip,
  type PeriodeRotation,
} from "./commun";

// ---------------------------------------------------------------------------
// Constantes métier
// ---------------------------------------------------------------------------

/** Objectif de couverture quand aucune date de réappro n'est annoncée. */
export const COUVERTURE_SANS_DATE_JOURS = 30;
/** DLUO à moins de ~3 mois → alerte informative. */
export const SEUIL_ALERTE_PEREMPTION_JOURS = 90;
/** Couverture sous ce seuil, hors rupture GPNC → onglet Vigilance. */
export const SEUIL_VIGILANCE_JOURS = 7;
/** Sous ce volume de ventes, pas de vigilance (évite le bruit). */
export const ROTATION_MIN_VIGILANCE = 5;
/** Écarté par la règle stricte avec moins de marge → à surveiller. */
export const SEUIL_MARGE_JUSTESSE_JOURS = 3;
/** Score minimal pour accepter un rapprochement approximatif. */
export const SEUIL_MATCH = 80;
/** En dessous : correspondance « incertaine », à faire vérifier. */
export const SEUIL_CERTAIN = 92;
/** Couverture cible sans date, si la politique ABC est activée. */
export const COUVERTURE_ABC: Record<string, number> = { A: 21, B: 30, C: 14 };
/** Poids du volume (classe ABC) dans le score de priorité. */
export const POIDS_CLASSE: Record<string, number> = { A: 1.0, B: 0.5, C: 0.2 };

export const URGENT = "🔴 URGENT";
export const MODERE = "🟡 MODÉRÉ";
export const ANTICIPER = "🟢 À ANTICIPER";

// ---------------------------------------------------------------------------
// Rapprochement des produits entre fichiers
// ---------------------------------------------------------------------------

export interface Correspondance {
  index: number | null;
  methode: "cip" | "exact" | "fuzzy" | "aucune";
  score: number;
  incertain: boolean;
}

/** Longueur de la plus longue sous-séquence commune. */
function lcs(a: string, b: string): number {
  const precedent = new Array<number>(b.length + 1).fill(0);
  const courant = new Array<number>(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i += 1) {
    courant[0] = 0;
    for (let j = 1; j <= b.length; j += 1) {
      courant[j] =
        a[i - 1] === b[j - 1]
          ? precedent[j - 1] + 1
          : Math.max(precedent[j], courant[j - 1]);
    }
    precedent.splice(0, precedent.length, ...courant);
  }
  return precedent[b.length];
}

/**
 * Similarité 0-100 façon `rapidfuzz.fuzz.token_sort_ratio` : les mots sont
 * triés avant comparaison, ce qui rend l'ordre des termes indifférent
 * (« DOLIPRANE 1000 CPR » ≈ « CPR DOLIPRANE 1000 »).
 */
export function tokenSortRatio(a: string, b: string): number {
  const trier = (s: string) => s.split(/\s+/).filter(Boolean).sort().join(" ");
  const x = trier(a);
  const y = trier(b);
  if (!x.length && !y.length) return 100;
  if (!x.length || !y.length) return 0;
  return (2 * lcs(x, y) * 100) / (x.length + y.length);
}

export interface IndexListe {
  parCip: Map<string, number>;
  parLibelle: Map<string, number>;
  libellesNormalises: [string, number][];
}

/** Construit les index (CIP → ligne, libellé normalisé → ligne). */
export function indexer(
  lignes: Record<string, unknown>[],
  colLibelle: string,
  colCip?: string | null,
): IndexListe {
  const parCip = new Map<string, number>();
  const parLibelle = new Map<string, number>();
  const libellesNormalises: [string, number][] = [];

  lignes.forEach((ligne, idx) => {
    if (colCip) {
      // CIP13 ET CIP7 indexés : les exports mélangent les deux formes.
      for (const forme of variantesCip(normaliserCip(ligne[colCip]))) {
        if (!parCip.has(forme)) parCip.set(forme, idx);
      }
    }
    const norme = normaliserLibelle(ligne[colLibelle]);
    if (norme) {
      if (!parLibelle.has(norme)) parLibelle.set(norme, idx);
      libellesNormalises.push([norme, idx]);
    }
  });

  return { parCip, parLibelle, libellesNormalises };
}

/** Rapproche un produit d'une liste indexée : CIP > libellé exact > approché. */
export function apparier(
  libelle: string,
  cip: string,
  index: IndexListe,
): Correspondance {
  for (const forme of variantesCip(cip)) {
    const trouve = index.parCip.get(forme);
    if (trouve !== undefined) {
      return { index: trouve, methode: "cip", score: 100, incertain: false };
    }
  }
  const norme = normaliserLibelle(libelle);
  if (!norme) return { index: null, methode: "aucune", score: 0, incertain: false };

  const exact = index.parLibelle.get(norme);
  if (exact !== undefined) {
    return { index: exact, methode: "exact", score: 100, incertain: false };
  }

  let meilleur: number | null = null;
  let meilleurScore = 0;
  for (const [autre, idx] of index.libellesNormalises) {
    const s = tokenSortRatio(norme, autre);
    if (s > meilleurScore) {
      meilleur = idx;
      meilleurScore = s;
    }
  }
  if (meilleur !== null && meilleurScore >= SEUIL_MATCH) {
    return {
      index: meilleur,
      methode: "fuzzy",
      score: meilleurScore,
      incertain: meilleurScore < SEUIL_CERTAIN,
    };
  }
  return { index: null, methode: "aucune", score: 0, incertain: false };
}

// ---------------------------------------------------------------------------
// Calculs élémentaires
// ---------------------------------------------------------------------------

/** Fonction d'erreur (approximation d'Abramowitz & Stegun, 7.1.26). */
function erf(x: number): number {
  const signe = x < 0 ? -1 : 1;
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-x * x);
  return signe * y;
}

/**
 * Probabilité d'être en rupture d'ici `horizonJours`.
 *
 * La demande sur l'horizon est modélisée en loi Normale(μ, σ) à partir de la
 * moyenne et de l'écart-type MENSUELS observés (σ_h = σ_mois × √(h/30)).
 * Sans variabilité mesurable (moins de 3 mois, σ = 0), repli déterministe :
 * 1 si la demande moyenne épuise le stock, sinon 0.
 */
export function probabiliteRupture(
  stockEffectif: number,
  rotationMensuelle: number,
  ventes: unknown[],
  horizonJours = 7,
): number {
  if (rotationMensuelle <= 0) return 0;
  const demandeHorizon = (rotationMensuelle / JOURS_PAR_MOIS) * horizonJours;
  const valeurs = ventes.map(parserNombre);

  let sigmaMois = 0;
  if (valeurs.length >= 3) {
    const moyenne = valeurs.reduce((a, b) => a + b, 0) / valeurs.length;
    sigmaMois = Math.sqrt(
      valeurs.reduce((acc, v) => acc + (v - moyenne) ** 2, 0) / valeurs.length,
    );
  }
  const sigmaHorizon = sigmaMois * Math.sqrt(horizonJours / JOURS_PAR_MOIS);
  if (sigmaHorizon <= 0) return demandeHorizon >= stockEffectif ? 1 : 0;

  const z = (stockEffectif - demandeHorizon) / sigmaHorizon;
  return 0.5 * (1 - erf(z / Math.SQRT2));
}

/**
 * Score de priorité 0-100, pour trier la liste du matin.
 *
 * 50 pts de risque imminent (probabilité à 7 j) + 30 pts de poids du produit
 * (classe ABC) + 20 pts de fiabilité de la réappro (déjà repoussée → 1 ; pas
 * de date → 0,5 ; date jamais démentie → 0).
 */
export function scorePriorite(
  risqueRupture: number,
  classe: string,
  reports = 0,
  sansDate = false,
): number {
  const risque = Math.min(1, Math.max(0, risqueRupture));
  const fiabilite = reports ? 1 : sansDate ? 0.5 : 0;
  return Math.round(
    50 * risque + 30 * (POIDS_CLASSE[classe] ?? 0.2) + 20 * fiabilite,
  );
}

/**
 * Règle d'apparition STRICTE, sans buffer : avec date de réappro, le produit
 * apparaît si son stock ne couvre pas l'attente ; sans date, s'il est sous
 * 30 jours de couverture.
 */
export function doitApparaitre(
  stockJours: number,
  joursAvantReappro: number | null,
): boolean {
  if (joursAvantReappro !== null) return stockJours < joursAvantReappro;
  return stockJours < COUVERTURE_SANS_DATE_JOURS;
}

/** URGENT (stock 0 ou ≤ 3 j) · MODÉRÉ (≤ 15 j) · À ANTICIPER. */
export function classerUrgence(stockActuel: number, stockJours: number): string {
  if (stockActuel <= 0 || stockJours <= 3) return URGENT;
  if (stockJours <= 15) return MODERE;
  return ANTICIPER;
}

/**
 * Quantité à commander = arrondi supérieur de (rotation/jour × couverture −
 * stock), minimum 1, arrondie au multiple du conditionnement s'il est connu.
 */
export function quantiteACommander(
  rotationMensuelle: number,
  couvertureCibleJours: number,
  stockActuel: number,
  conditionnement: number | null = null,
): number {
  const qteCible = (rotationMensuelle / JOURS_PAR_MOIS) * couvertureCibleJours;
  let cmd = Math.max(1, Math.ceil(qteCible - stockActuel));
  if (conditionnement && conditionnement > 1) {
    cmd = Math.ceil(cmd / conditionnement) * conditionnement;
  }
  return cmd;
}

/**
 * Compte les glissements dans une suite chronologique de dates annoncées
 * (`null` = pas de date ce jour-là, ignoré), la date du jour en dernier.
 */
export function compterReports(
  annonces: (Date | null)[],
  dateReapproJour: Date | null,
): number {
  let reports = 0;
  let derniere: Date | null = null;
  for (const d of [...annonces, dateReapproJour]) {
    if (!d) continue;
    if (derniere && d.getTime() > derniere.getTime()) reports += 1;
    derniere = d;
  }
  return reports;
}

/**
 * Indice de rupture passée : au moins un mois à 0 vente alors que d'autres
 * mois vendent — la rotation calculée est alors probablement sous-estimée.
 * Toutes les valeurs à 0 = pas de demande réelle → non signalé.
 */
export function rotationPossiblementSousEstimee(ventes: unknown[]): boolean {
  const valeurs = ventes.map(parserNombre);
  if (valeurs.length === 0 || valeurs.every((v) => v <= 0)) return false;
  return valeurs.some((v) => v <= 0);
}

// ---------------------------------------------------------------------------
// Historique des analyses (suivi quotidien)
// ---------------------------------------------------------------------------

export interface LigneHistorique {
  dateAnalyse: string; // AAAA-MM-JJ
  produit: string;
  urgence?: string;
  qteACommander?: number;
  dateReappro?: string;
  /** « commande » (produit signalé) ou « surveillance » (écarté de justesse). */
  type?: string;
}

/**
 * Restreint l'historique aux produits réellement SIGNALÉS : les lignes de
 * surveillance ne servent qu'au suivi des dates annoncées.
 */
function lignesSignalees(historique: LigneHistorique[]): LigneHistorique[] {
  return historique.filter((l) => (l.type ?? "commande") !== "surveillance");
}

const enDate = (iso: string): Date | null => parserDate(iso);

/** Nombre d'analyses antérieures où le produit était déjà signalé. */
export function compterOccurrencesHistorique(
  produit: string,
  historique: LigneHistorique[],
  avantDate: Date,
): number {
  return lignesSignalees(historique).filter((l) => {
    if (l.produit !== produit) return false;
    const d = enDate(l.dateAnalyse);
    return d !== null && d.getTime() < avantDate.getTime();
  }).length;
}

/**
 * Suivi quotidien : compare les produits signalés aujourd'hui à la DERNIÈRE
 * analyse antérieure. Renvoie la date de référence, les nouveaux produits et
 * ceux qui ne sont plus signalés.
 */
export function comparerAAnalysePrecedente(
  produitsJour: string[],
  historique: LigneHistorique[],
  dateAnalyse: Date,
): { datePrecedente: string | null; nouveaux: string[]; resolus: string[] } {
  const signalees = lignesSignalees(historique);
  const anterieures = signalees.filter((l) => {
    const d = enDate(l.dateAnalyse);
    return d !== null && d.getTime() < dateAnalyse.getTime();
  });
  if (anterieures.length === 0) {
    return { datePrecedente: null, nouveaux: [...produitsJour], resolus: [] };
  }
  const datePrecedente = anterieures
    .map((l) => l.dateAnalyse)
    .sort()
    .at(-1)!;
  const produitsPrecedents = new Set(
    anterieures.filter((l) => l.dateAnalyse === datePrecedente).map((l) => l.produit),
  );
  const ensembleJour = new Set(produitsJour);
  return {
    datePrecedente,
    nouveaux: produitsJour.filter((p) => !produitsPrecedents.has(p)),
    resolus: [...produitsPrecedents].filter((p) => !ensembleJour.has(p)).sort(),
  };
}

/**
 * Taux de service des produits A : part des couples produit × jour SANS
 * rupture signalée sur la fenêtre glissante. `null` si l'historique ne
 * couvre pas encore la fenêtre.
 */
export function tauxDeService(
  produitsA: string[],
  historique: LigneHistorique[],
  dateAnalyse: Date,
  fenetreJours = 30,
): { taux: number | null; joursAnalyses: number } {
  const signalees = lignesSignalees(historique);
  if (signalees.length === 0 || produitsA.length === 0) {
    return { taux: null, joursAnalyses: 0 };
  }
  const debut = new Date(dateAnalyse);
  debut.setDate(debut.getDate() - fenetreJours);

  const dansFenetre = signalees.filter((l) => {
    const d = enDate(l.dateAnalyse);
    return d !== null && d.getTime() >= debut.getTime() && d.getTime() < dateAnalyse.getTime();
  });
  const jours = new Set(dansFenetre.map((l) => l.dateAnalyse));
  if (jours.size === 0) return { taux: null, joursAnalyses: 0 };

  const ensembleA = new Set(produitsA);
  const couples = new Set(
    dansFenetre
      .filter((l) => ensembleA.has(l.produit))
      .map((l) => `${l.dateAnalyse}|${l.produit}`),
  );
  return {
    taux: 1 - couples.size / (jours.size * ensembleA.size),
    joursAnalyses: jours.size,
  };
}
