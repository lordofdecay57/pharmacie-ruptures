/**
 * Module 1 — Gestion des stocks en rotation.
 *
 * Portage fidèle de `stock_rotation.py` (v3.1) : mêmes règles métier,
 * validées sur le cadencier réel de la pharmacie.
 *
 * Méthode : stock min = conso/jour × 14 j, stock max = conso/jour × 30 j,
 * bornes réglables, arrondies à la boîte entière supérieure. Le stock min du
 * jour est ajusté au calendrier de réception (pas de livraison le week-end).
 *
 * ISOLATION : ce module ne lit QUE le cadencier. Il ignore tout des ruptures
 * fournisseurs — ces notions appartiennent au module ruptures.
 */

import {
  JOURS_PAR_MOIS,
  SEUILS_VARIABILITE,
  type PeriodeRotation,
  calculerRotationMensuelle,
  calculerStockJours,
  calculerTendance,
  classerAbc,
  coefficientVariation,
  corrigerFauxZeros,
  normaliserLibelle,
  parserNombre,
  variabiliteDemande,
} from "./commun";

// ---------------------------------------------------------------------------
// Constantes / valeurs par défaut
// ---------------------------------------------------------------------------

/** Règle métier : sous ce seuil (et sous le min) → cible = stock max. */
export const SEUIL_ALERTE_UNITES_DEFAUT = 10;
/** Stock max sous ce seuil → le stock min est supprimé. */
export const SEUIL_MAX_SANS_MIN_UNITES = 10;
export const COUVERTURE_MIN_JOURS_DEFAUT = 14;
export const COUVERTURE_MAX_JOURS_DEFAUT = 30;
export const CONSOMMATION_DEFAUT_MENSUELLE = 0;
/** Plus de 6 mois de couverture → stock dormant. */
export const SEUIL_DORMANT_JOURS_DEFAUT = 180;
/** Rotation ≤ ce seuil (boîtes/mois) → écarté du réassort automatique. */
export const ROTATION_MIN_COMMANDE_DEFAUT = 1;
/** Variation du stock min/max à partir de laquelle une ligne ressort. */
export const SEUIL_VARIATION_AFFICHAGE = 0.1;

export interface ParametresStockRotation {
  couvertureMinJours: number;
  couvertureMaxJours: number;
  seuilAlerteUnites: number;
  periodeRotation: PeriodeRotation;
  corrigerRupturesPassees: boolean;
  consommationDefautMensuelle: number;
  seuilDormantJours: number;
  rotationMinCommandeMensuelle: number;
}

export const PARAMETRES_DEFAUT: ParametresStockRotation = {
  couvertureMinJours: COUVERTURE_MIN_JOURS_DEFAUT,
  couvertureMaxJours: COUVERTURE_MAX_JOURS_DEFAUT,
  seuilAlerteUnites: SEUIL_ALERTE_UNITES_DEFAUT,
  periodeRotation: "annuelle",
  corrigerRupturesPassees: true,
  consommationDefautMensuelle: CONSOMMATION_DEFAUT_MENSUELLE,
  seuilDormantJours: SEUIL_DORMANT_JOURS_DEFAUT,
  rotationMinCommandeMensuelle: ROTATION_MIN_COMMANDE_DEFAUT,
};

/** Colonnes du cadencier, telles que confirmées dans l'interface. */
export interface MappingCadencier {
  libelle: string;
  cip?: string | null;
  stock: string;
  ventes: string[];
  conditionnement?: string | null;
  commandeEnCours?: string | null;
  peremption?: string | null;
}

export type LigneBrute = Record<string, unknown>;

export type Alerte =
  | "🔴 Action requise"
  | "🟡 Sous le min"
  | "🟢 OK"
  | "⚪ Rotation faible";

export interface LigneStock {
  alerte: Alerte;
  classe: "A" | "B" | "C";
  codeCip: string;
  nomProduit: string;
  stockActuel: number;
  commandeEnCours: number | null;
  consommationMois: number;
  tendance: string;
  variabilite: string;
  stockMin: number;
  stockMax: number;
  stockMinConseille: number;
  cibleReassort: number;
  qteACommander: number;
  motif: string;
  /** Couverture en jours (peut valoir +∞ si aucune vente). */
  stockJours: number;
  /**
   * Consommation NON arrondie, utilisée pour le classement ABC : classer sur
   * la valeur affichée (arrondie au dixième) départagerait arbitrairement les
   * produits proches d'une frontière de classe.
   */
  consommationExacte: number;
  /** Renseigné après comparaison à l'analyse précédente. */
  modifie?: boolean;
}

export interface LigneDormant {
  codeCip: string;
  nomProduit: string;
  stockActuel: number;
  consommationMois: number;
  stockJours: number;
  stockMax: number;
  commentaire: string;
}

export interface ResumeStock {
  totalProduits: number;
  actionRequise: number;
  sousLeMin: number;
  rotationFaible: number;
  nbA: number;
  nbB: number;
  nbC: number;
  dormants: number;
  dormantsBoites: number;
  qteTotaleACommander: number;
  joursWeekend: number;
  doublonsFusionnes: number;
  nbModifiees?: number;
  nbNouvelles?: number;
  etatPrecedentExistant?: boolean;
  documentDifferent?: boolean;
}

export interface ResultatStockRotation {
  tableau: LigneStock[];
  dormants: LigneDormant[];
  resume: ResumeStock;
}

// ---------------------------------------------------------------------------
// Calculs élémentaires
// ---------------------------------------------------------------------------

/**
 * Jours de couverture à AJOUTER au stock min du jour, parce que les
 * commandes ne sont pas réceptionnées le samedi ni le dimanche.
 *
 * Une commande passée un jour ouvré est reçue le prochain jour de réception :
 * vendredi → lundi (+2 j), samedi → lundi (+1 j), dimanche-jeudi → +0.
 */
export function joursSupplementairesWeekend(dateCommande: Date | null): number {
  if (!dateCommande) return 0;
  const jour = dateCommande.getDay(); // 0 = dimanche … 6 = samedi
  if (jour === 5) return 2; // vendredi
  if (jour === 6) return 1; // samedi
  return 0;
}

/** Stock min = conso/jour × (couverture min + jours week-end éventuels). */
export function calculerStockMin(
  consommationJour: number,
  couvertureMinJours: number,
  joursSupplementaires = 0,
): number {
  return consommationJour * (couvertureMinJours + joursSupplementaires);
}

/** Stock max = conso/jour × couverture max (plafond de réassort). */
export function calculerStockMax(
  consommationJour: number,
  couvertureMaxJours: number,
): number {
  return consommationJour * couvertureMaxJours;
}

/** Arrondi à la boîte entière supérieure, à l'abri des artefacts flottants. */
function plafondBoites(valeur: number): number {
  return valeur > 0 ? Math.ceil(Number(valeur.toFixed(6))) : 0;
}

/**
 * Politique de réassort à 3 paliers.
 *
 * - stock < seuil absolu **ET** stock < stock min : urgence confirmée,
 *   cible = stock max (commande immédiate) ;
 * - stock < stock min : réassort progressif, cible = stock min ;
 * - stock ≥ stock min : rien à commander.
 *
 * Le seuil absolu ne suffit PAS à lui seul : pour un produit à faible
 * rotation, le stock min est souvent lui-même inférieur au seuil, et un
 * stock déjà au-dessus de son propre minimum déclenchait à tort une
 * commande jusqu'au max (9 alertes rouges sur 10 en pratique).
 */
export function determinerCibleReassort(
  stockActuel: number,
  stockMin: number,
  stockMax: number,
  seuilAlerteUnites: number,
): { cible: number; qte: number; motif: string } {
  let cible: number;
  let motif: string;
  if (stockActuel < seuilAlerteUnites && stockActuel < stockMin) {
    cible = stockMax;
    motif = `Stock < ${seuilAlerteUnites} unités ET sous le stock min — commande immédiate jusqu'au stock max`;
  } else if (stockActuel < stockMin) {
    cible = stockMin;
    motif = "Sous le stock min — réassort progressif jusqu'au stock min";
  } else {
    cible = stockActuel;
    motif = "Stock suffisant — aucune commande";
  }
  return { cible, qte: Math.max(0, Math.ceil(cible - stockActuel)), motif };
}

// ---------------------------------------------------------------------------
// Fusion des doublons de code CIP
// ---------------------------------------------------------------------------

/**
 * Fusionne les lignes décrivant le MÊME produit sous plusieurs codes CIP
 * (changement de générique ou de fournisseur).
 *
 * Cas réel : l'ancien code reste au cadencier avec un stock 0 et un
 * historique qui s'arrête, pendant que le nouveau code porte le stock et les
 * ventes récentes. Sans fusion, l'ancienne fiche déclenche une commande
 * fantôme d'un produit déjà en rayon.
 *
 * Fusion par libellé normalisé identique : stock et ventes ADDITIONNÉS (la
 * série redevient continue), code CIP de la ligne à l'activité la plus
 * récente. Les libellés vides ne sont jamais fusionnés entre eux.
 */
export function fusionnerDoublonsCadencier(
  cadencier: LigneBrute[],
  m: MappingCadencier,
): { lignes: LigneBrute[]; nbFusionnees: number } {
  const cles = cadencier.map((l) => normaliserLibelle(l[m.libelle]));
  const occurrences = new Map<string, number>();
  cles.forEach((c) => {
    if (c) occurrences.set(c, (occurrences.get(c) ?? 0) + 1);
  });

  const colonnesVentes = m.ventes;
  /** (index du dernier mois vendu, stock) — désigne le code encore actif. */
  const activite = (ligne: LigneBrute): [number, number] => {
    let dernier = -1;
    colonnesVentes.forEach((c, i) => {
      if (parserNombre(ligne[c]) > 0) dernier = i;
    });
    return [dernier, parserNombre(ligne[m.stock])];
  };

  const sortie: LigneBrute[] = [];
  const dejaFusionnes = new Set<string>();

  cadencier.forEach((ligne, idx) => {
    const cle = cles[idx];
    if (!cle || (occurrences.get(cle) ?? 0) < 2) {
      sortie.push(ligne);
      return;
    }
    if (dejaFusionnes.has(cle)) return; // groupe déjà émis
    dejaFusionnes.add(cle);

    const groupe = cadencier.filter((_, i) => cles[i] === cle);
    const porteuse = groupe.reduce((meilleure, candidate) => {
      const [dm, sm] = activite(meilleure);
      const [dc, sc] = activite(candidate);
      return dc > dm || (dc === dm && sc > sm) ? candidate : meilleure;
    });

    const fusion: LigneBrute = { ...porteuse };
    fusion[m.stock] = groupe.reduce((s, l) => s + parserNombre(l[m.stock]), 0);
    for (const c of colonnesVentes) {
      fusion[c] = groupe.reduce((s, l) => s + parserNombre(l[c]), 0);
    }
    sortie.push(fusion);
  });

  return { lignes: sortie, nbFusionnees: cadencier.length - sortie.length };
}

// ---------------------------------------------------------------------------
// Analyse complète du cadencier
// ---------------------------------------------------------------------------

/**
 * Calcule stock min/max et la quantité de réassort pour chaque produit.
 *
 * `dateAnalyse` sert UNIQUEMENT à l'ajustement week-end du stock min.
 */
export function analyserStockRotation(
  cadencier: LigneBrute[],
  mapping: MappingCadencier,
  params: Partial<ParametresStockRotation> = {},
  dateAnalyse: Date | null = null,
): ResultatStockRotation {
  const p: ParametresStockRotation = { ...PARAMETRES_DEFAUT, ...params };
  const m = mapping;

  // Même produit sous deux codes CIP : fusion, sinon l'ancien code à stock 0
  // déclenche une commande fantôme.
  const { lignes: lignesFusionnees, nbFusionnees } = fusionnerDoublonsCadencier(
    cadencier,
    m,
  );
  const joursWeekend = joursSupplementairesWeekend(dateAnalyse);

  const brut: LigneStock[] = [];

  for (const ligne of lignesFusionnees) {
    const stock = parserNombre(ligne[m.stock]);
    const enCours = m.commandeEnCours ? parserNombre(ligne[m.commandeEnCours]) : 0;
    // Les boîtes déjà commandées couvrent aussi la consommation à venir.
    const stockEffectif = stock + enCours;

    const cipBrut = m.cip ? ligne[m.cip] : "";
    const codeCip = cipBrut === null || cipBrut === undefined ? "" : String(cipBrut).trim();
    const nomBrut = ligne[m.libelle];
    const nomProduit = nomBrut === null || nomBrut === undefined ? "" : String(nomBrut).trim();

    const ventesBrutes = m.ventes.map((c) => ligne[c]);
    const ventes = p.corrigerRupturesPassees
      ? corrigerFauxZeros(ventesBrutes).corrigees
      : ventesBrutes.map(parserNombre);

    let rotation = calculerRotationMensuelle(ventes, p.periodeRotation);

    // Garde-fou des modes réactifs : si le calcul récent tombe à 0 alors que
    // le produit vend sur l'année (rupture/creux ponctuel), on retombe sur la
    // moyenne annuelle pour ne pas faire DISPARAÎTRE du pilotage un produit
    // qui rote réellement.
    let rotationRecenteNulle = false;
    if (rotation <= 0 && p.periodeRotation !== "annuelle") {
      const rotationAnnuelle = calculerRotationMensuelle(ventes, "annuelle");
      if (rotationAnnuelle > 0) {
        rotation = rotationAnnuelle;
        rotationRecenteNulle = true;
      }
    }

    const sansHistorique = ventesBrutes.every((v) => parserNombre(v) === 0);
    if (rotation <= 0 && sansHistorique && p.consommationDefautMensuelle > 0) {
      rotation = p.consommationDefautMensuelle;
    }
    if (rotation <= 0 && stock <= 0) continue; // ni vente ni stock : rien à piloter

    const consoJour = rotation / JOURS_PAR_MOIS;
    let stockMin = plafondBoites(
      calculerStockMin(consoJour, p.couvertureMinJours, joursWeekend),
    );
    let stockMax = plafondBoites(calculerStockMax(consoJour, p.couvertureMaxJours));
    stockMax = Math.max(stockMax, stockMin);

    // Règle officine : stock max < 10 → le stock min est SUPPRIMÉ (ces petits
    // produits ne sont pas pilotés par un point de commande automatique).
    let minSupprime = false;
    if (stockMax > 0 && stockMax < SEUIL_MAX_SANS_MIN_UNITES) {
      stockMin = 0;
      minSupprime = true;
    }

    // Produits à rotation quasi nulle : écartés du réassort automatique.
    const rotationFaible =
      p.rotationMinCommandeMensuelle > 0 &&
      rotation > 0 &&
      rotation <= p.rotationMinCommandeMensuelle;

    // Colonne CONSEILLÉE (indicative) : stock min majoré d'une marge de
    // sécurité pour les ventes IRRÉGULIÈRES, au-delà du seuil de stabilité
    // (CV 0,3) et plafonnée (CV 1,5 → +120 %).
    const cv = coefficientVariation(ventes);
    const marge = cv ? Math.max(0, Math.min(cv, 1.5) - SEUILS_VARIABILITE[0]) : 0;
    let stockMinConseille = stockMin;
    if (marge > 0) {
      const base = consoJour * (p.couvertureMinJours + joursWeekend);
      stockMinConseille = Math.max(plafondBoites(base * (1 + marge)), stockMin);
    }

    // Cible et urgence évaluées sur le stock EFFECTIF (rayon + en cours).
    let { cible, qte, motif } = determinerCibleReassort(
      stockEffectif,
      stockMin,
      stockMax,
      p.seuilAlerteUnites,
    );
    const stockJours = calculerStockJours(stockEffectif, rotation);

    let alerte: Alerte;
    if (rotationFaible) {
      cible = stock;
      qte = 0;
      alerte = "⚪ Rotation faible";
      motif = `Rotation ≤ ${p.rotationMinCommandeMensuelle}/mois — écarté du réassort automatique`;
    } else if (qte <= 0) {
      alerte = "🟢 OK";
    } else if (stockEffectif < p.seuilAlerteUnites) {
      alerte = "🔴 Action requise";
    } else {
      alerte = "🟡 Sous le min";
    }

    if (!rotationFaible && sansHistorique && rotation > 0) {
      motif += " (consommation par défaut — pas d'historique)";
    }
    if (!rotationFaible && rotationRecenteNulle) {
      motif += " · ventes récentes nulles (rupture/creux) — repli sur la moyenne annuelle";
    }
    if (enCours) {
      motif += ` · ${enCours} déjà en commande (déduit du calcul)`;
    }
    if (minSupprime && !rotationFaible) {
      motif += ` · stock min supprimé (stock max < ${SEUIL_MAX_SANS_MIN_UNITES})`;
    }

    brut.push({
      alerte,
      classe: "C", // recalculé ci-dessous (ABC sur l'ensemble)
      codeCip,
      nomProduit,
      stockActuel: Math.round(stock),
      commandeEnCours: enCours ? Math.round(enCours) : null,
      consommationMois: Math.round(rotation * 10) / 10,
      tendance: calculerTendance(ventes),
      variabilite: variabiliteDemande(ventes),
      stockMin,
      stockMax,
      stockMinConseille,
      cibleReassort: Math.round(cible),
      qteACommander: qte,
      motif,
      stockJours,
      consommationExacte: rotation,
    });
  }

  if (brut.length === 0) {
    return {
      tableau: [],
      dormants: [],
      resume: {
        totalProduits: 0, actionRequise: 0, sousLeMin: 0, rotationFaible: 0,
        nbA: 0, nbB: 0, nbC: 0, dormants: 0, dormantsBoites: 0,
        qteTotaleACommander: 0, joursWeekend, doublonsFusionnes: nbFusionnees,
      },
    };
  }

  // Classement ABC sur l'ensemble des consommations.
  const classes = classerAbc(brut.map((l) => l.consommationExacte));
  brut.forEach((l, i) => {
    l.classe = classes[i];
  });

  const dormants: LigneDormant[] = brut
    .filter((l) => l.stockActuel > 0 && l.stockJours > p.seuilDormantJours)
    .sort((a, b) => b.stockActuel - a.stockActuel)
    .map((l) => ({
      codeCip: l.codeCip,
      nomProduit: l.nomProduit,
      stockActuel: l.stockActuel,
      consommationMois: l.consommationMois,
      stockJours: l.stockJours,
      stockMax: l.stockMax,
      commentaire:
        `Plus de ${p.seuilDormantJours} j de couverture, bien au-delà du ` +
        "stock max — trésorerie immobilisée, envisager retour fournisseur " +
        "ou arrêt de réassort.",
    }));

  // Priorité d'affichage : action requise, sous le min, OK, rotation faible.
  const ordreAlerte: Record<Alerte, number> = {
    "🔴 Action requise": 0,
    "🟡 Sous le min": 1,
    "🟢 OK": 2,
    "⚪ Rotation faible": 3,
  };
  const tableau = [...brut].sort(
    (a, b) =>
      ordreAlerte[a.alerte] - ordreAlerte[b.alerte] ||
      b.qteACommander - a.qteACommander,
  );

  const compte = (a: Alerte) => tableau.filter((l) => l.alerte === a).length;
  const resume: ResumeStock = {
    totalProduits: tableau.length,
    actionRequise: compte("🔴 Action requise"),
    sousLeMin: compte("🟡 Sous le min"),
    rotationFaible: compte("⚪ Rotation faible"),
    nbA: tableau.filter((l) => l.classe === "A").length,
    nbB: tableau.filter((l) => l.classe === "B").length,
    nbC: tableau.filter((l) => l.classe === "C").length,
    dormants: dormants.length,
    dormantsBoites: dormants.reduce((s, l) => s + l.stockActuel, 0),
    qteTotaleACommander: tableau.reduce((s, l) => s + l.qteACommander, 0),
    joursWeekend,
    doublonsFusionnes: nbFusionnees,
  };

  return { tableau, dormants, resume };
}

// ---------------------------------------------------------------------------
// Cadencier n+1 : ne ressortir que les lignes modifiées (≥ 10 %)
// ---------------------------------------------------------------------------

export interface EtatStockLigne {
  codeCip: string;
  nomProduit: string;
  stockMin: number;
  stockMax: number;
}

/**
 * Clé d'appariement stable entre deux analyses : CIP + libellé normalisé.
 *
 * Combiner les deux évite les collisions quand plusieurs produits DIFFÉRENTS
 * partagent le même CIP (cas réel du cadencier) — le CIP seul les
 * confondrait et ferait ressortir des lignes à tort.
 */
export function cleProduit(cip: unknown, nom: unknown): string {
  const c = cip === null || cip === undefined ? "" : String(cip).trim();
  return `${c}|${normaliserLibelle(nom)}`;
}

/**
 * Marque les lignes dont le stock min OU max a varié depuis la dernière
 * analyse (ou qui sont nouvelles).
 *
 * `etatPrecedent` vide → tout est considéré modifié (première analyse).
 */
export function comparerAEtatPrecedent(
  tableau: LigneStock[],
  etatPrecedent: EtatStockLigne[] | null,
  seuilPct: number = SEUIL_VARIATION_AFFICHAGE,
): { tableau: LigneStock[]; nbModifiees: number; nbNouvelles: number } {
  if (tableau.length === 0) {
    return { tableau: [], nbModifiees: 0, nbNouvelles: 0 };
  }
  if (!etatPrecedent || etatPrecedent.length === 0) {
    return {
      tableau: tableau.map((l) => ({ ...l, modifie: true })),
      nbModifiees: tableau.length,
      nbNouvelles: tableau.length,
    };
  }

  const precedent = new Map<string, [number, number]>();
  for (const r of etatPrecedent) {
    precedent.set(cleProduit(r.codeCip, r.nomProduit), [
      parserNombre(r.stockMin),
      parserNombre(r.stockMax),
    ]);
  }

  let nbNouvelles = 0;
  const annote = tableau.map((l) => {
    const ancien = precedent.get(cleProduit(l.codeCip, l.nomProduit));
    if (!ancien) {
      nbNouvelles += 1;
      return { ...l, modifie: true };
    }
    const [ancienMin, ancienMax] = ancien;
    const varMin = Math.abs(l.stockMin - ancienMin) / Math.max(Math.abs(ancienMin), 1);
    const varMax = Math.abs(l.stockMax - ancienMax) / Math.max(Math.abs(ancienMax), 1);
    return { ...l, modifie: varMin >= seuilPct || varMax >= seuilPct };
  });

  return {
    tableau: annote,
    nbModifiees: annote.filter((l) => l.modifie).length,
    nbNouvelles,
  };
}

/** Extrait de quoi mémoriser l'analyse courante (référence de la suivante). */
export function etatStockAEnregistrer(tableau: LigneStock[]): EtatStockLigne[] {
  return tableau.map((l) => ({
    codeCip: l.codeCip,
    nomProduit: l.nomProduit,
    stockMin: l.stockMin,
    stockMax: l.stockMax,
  }));
}

/**
 * Empreinte de la structure du cadencier (liste de colonnes).
 *
 * La règle « ne pas ressortir les stocks inchangés » ne vaut que si le
 * document de base est le même : si le cadencier change de structure, la
 * comparaison n'a plus de sens.
 */
export function signatureColonnes(colonnes: string[]): string {
  const empreinte = colonnes.map(String).join("|");
  let h = 0;
  for (let i = 0; i < empreinte.length; i += 1) {
    h = (Math.imul(31, h) + empreinte.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}
