/**
 * Module 2 — analyse complète : croisement cadencier × GPNC × UNIPHARMA.
 *
 * Portage de la fonction `analyser()` de `moteur_ruptures.py`. Les briques
 * élémentaires (appariement, probabilité de rupture, score de priorité…)
 * vivent dans `ruptures.ts`.
 *
 * Étapes : (1) périmètre — le produit est-il vendu ? (2) stock en jours,
 * (3) règle d'apparition STRICTE, (4) dépannage UNIPHARMA possible ?,
 * (5) quantité à commander, (6) urgence.
 */

import {
  calculerRotationMensuelle,
  calculerStockJours,
  calculerTendance,
  classerAbc,
  corrigerFauxZeros,
  normaliserCip,
  parserDate,
  parserNombre,
  type PeriodeRotation,
} from "./commun";
import {
  ANTICIPER,
  COUVERTURE_ABC,
  COUVERTURE_SANS_DATE_JOURS,
  MODERE,
  ROTATION_MIN_VIGILANCE,
  SEUIL_ALERTE_PEREMPTION_JOURS,
  SEUIL_MARGE_JUSTESSE_JOURS,
  SEUIL_VIGILANCE_JOURS,
  URGENT,
  apparier,
  classerUrgence,
  compterOccurrencesHistorique,
  compterReports,
  doitApparaitre,
  indexer,
  probabiliteRupture,
  quantiteACommander,
  rotationPossiblementSousEstimee,
  scorePriorite,
  type LigneHistorique,
} from "./ruptures";

// ---------------------------------------------------------------------------
// Types d'entrée / sortie
// ---------------------------------------------------------------------------

export interface MappingRuptures {
  cadencier: {
    libelle: string;
    cip?: string | null;
    stock: string;
    ventes: string[];
    conditionnement?: string | null;
    commandeEnCours?: string | null;
    peremption?: string | null;
  };
  gpnc: { libelle: string; cip?: string | null; dateReappro?: string | null };
  unipharma: { libelle: string; cip?: string | null };
}

export interface ParametresRuptures {
  periode: PeriodeRotation;
  historique: LigneHistorique[];
  seuilVigilanceJours: number;
  rotationMinVigilance: number;
  seuilMargeJours: number;
  delaiLivraisonJours: number;
  rotationPrudente: boolean;
  corrigerRupturesPassees: boolean;
  politiqueAbc: boolean;
}

export const PARAMETRES_RUPTURES_DEFAUT: ParametresRuptures = {
  periode: "annuelle",
  historique: [],
  seuilVigilanceJours: SEUIL_VIGILANCE_JOURS,
  rotationMinVigilance: ROTATION_MIN_VIGILANCE,
  seuilMargeJours: SEUIL_MARGE_JUSTESSE_JOURS,
  delaiLivraisonJours: 0,
  rotationPrudente: false,
  corrigerRupturesPassees: true,
  politiqueAbc: false,
};

export interface LigneACommander {
  priorite: number;
  urgence: string;
  classe: string;
  produit: string;
  stockActuel: number;
  commandeEnCours: number | "";
  rotationMois: number;
  tendance: string;
  fiabiliteRotation: string;
  stockJours: number;
  probaRupture7j: string;
  dateReapproGpnc: string;
  joursAvantReappro: number | "";
  peremption: string;
  qteACommander: number;
  commentaire: string;
}

export interface LigneSansSolution {
  produit: string;
  stockActuel: number;
  rotationMois: number;
  stockJours: number;
  dateReapproGpnc: string;
  peremption: string;
  commentaire: string;
}

export interface LigneVigilance {
  priorite: number;
  classe: string;
  produit: string;
  stockActuel: number;
  commandeEnCours: number | "";
  rotationMois: number;
  tendance: string;
  stockJours: number;
  probaRupture7j: string;
  conseil: string;
}

export interface LigneJustesse {
  produit: string;
  stockActuel: number;
  rotationMois: number;
  stockJours: number;
  dateReapproGpnc: string;
  joursAvantReappro: number | "";
  margeJours: number;
  commentaire: string;
}

export interface LigneAnalyseComplete {
  produit: string;
  dateReappro: string;
  joursAvantReappro: number | "";
  vendu: string;
  stockActuel: number | "";
  commandeEnCours: number | "";
  rotationMois: number | "";
  fiabiliteRotation: string;
  stockJours: number | "";
  peremption: string;
  dispoUnipharma: string;
  decision: string;
  onglet: string;
  motif: string;
}

export interface MatchIncertain {
  produitGpnc: string;
  rapprocheDe: string;
  score: number;
  fichier: string;
}

export interface ResumeRuptures {
  rupturesGpnc: number;
  analyses: number;
  vendus: number;
  aCommander: number;
  sansSolution: number;
  urgents: number;
  moderes: number;
  anticiper: number;
  rotationDouteuse: number;
  peremptionProche: number;
  vigilance: number;
  justesse: number;
}

export interface ResultatRuptures {
  onglet1: LigneACommander[];
  onglet2: LigneSansSolution[];
  onglet3: LigneAnalyseComplete[];
  vigilance: LigneVigilance[];
  ecartesJustesse: LigneJustesse[];
  resume: ResumeRuptures;
  alertes: string[];
  matchsIncertains: MatchIncertain[];
}

// ---------------------------------------------------------------------------
// Utilitaires locaux
// ---------------------------------------------------------------------------

const jourFr = (d: Date) =>
  `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;

/** Écart en jours entiers entre deux dates civiles. */
const ecartJours = (a: Date, b: Date) => Math.round((a.getTime() - b.getTime()) / 86_400_000);

const arrondi1 = (v: number) => Math.round(v * 10) / 10;

/** Retire les colonnes techniques (préfixe `_`) avant restitution. */
function sansInterne<T extends object>(ligne: T): T {
  const copie = { ...ligne } as Record<string, unknown>;
  for (const c of Object.keys(copie)) if (c.startsWith("_")) delete copie[c];
  return copie as T;
}

// ---------------------------------------------------------------------------
// Analyse
// ---------------------------------------------------------------------------

export function analyserRuptures(
  cadencier: Record<string, unknown>[],
  rupturesGpnc: Record<string, unknown>[],
  rupturesUnipharma: Record<string, unknown>[],
  mapping: MappingRuptures,
  dateAnalyse: Date,
  params: Partial<ParametresRuptures> = {},
): ResultatRuptures {
  const p = { ...PARAMETRES_RUPTURES_DEFAUT, ...params };
  const mCad = mapping.cadencier;
  const mGpnc = mapping.gpnc;
  const mUni = mapping.unipharma;

  const alertes: string[] = [];
  const matchsIncertains: MatchIncertain[] = [];

  const indexCad = indexer(cadencier, mCad.libelle, mCad.cip);
  const indexUni = indexer(rupturesUnipharma, mUni.libelle, mUni.cip);

  /**
   * Rotation retenue : période choisie, ou la plus élevée des deux moyennes
   * en mode prudent — un produit en croissance n'est jamais sous-couvert.
   */
  const rotationDe = (ventes: unknown[]) =>
    p.rotationPrudente
      ? Math.max(
          calculerRotationMensuelle(ventes, "annuelle"),
          calculerRotationMensuelle(ventes, "3mois"),
        )
      : calculerRotationMensuelle(ventes, p.periode);

  // Pré-calcul du cadencier en UNE passe : sert aux ruptures, à la vigilance
  // et au classement ABC.
  const infos = cadencier.map((ligne) => {
    const stock = parserNombre(ligne[mCad.stock]);
    const enCours = mCad.commandeEnCours ? parserNombre(ligne[mCad.commandeEnCours]) : 0;
    const brutes = mCad.ventes.map((c) => ligne[c]);
    const { corrigees, nbCorriges } = p.corrigerRupturesPassees
      ? corrigerFauxZeros(brutes)
      : { corrigees: brutes.map(parserNombre), nbCorriges: 0 };
    return { stock, enCours, ventes: corrigees, rotation: rotationDe(corrigees), nbCorriges };
  });
  const classes = classerAbc(infos.map((i) => i.rotation));

  // Annonces de réappro passées, groupées par produit. Seules les analyses
  // STRICTEMENT antérieures comptent : une ré-analyse antidatée ne doit pas
  // se comparer à des annonces « du futur ».
  const annoncesReappro = new Map<string, (Date | null)[]>();
  for (const l of [...p.historique]
    .filter((l) => {
      const d = parserDate(l.dateAnalyse);
      return d !== null && d.getTime() < dateAnalyse.getTime();
    })
    .sort((a, b) => a.dateAnalyse.localeCompare(b.dateAnalyse))) {
    const liste = annoncesReappro.get(l.produit) ?? [];
    liste.push(l.dateReappro ? parserDate(l.dateReappro) : null);
    annoncesReappro.set(l.produit, liste);
  }

  const onglet1: (LigneACommander & { _stockJours: number })[] = [];
  const onglet2: (LigneSansSolution & { _rotation: number; _stock: number })[] = [];
  const onglet3: LigneAnalyseComplete[] = [];
  const justesse: LigneJustesse[] = [];
  const traites = new Set<number>();

  for (const ligneGpnc of rupturesGpnc) {
    const produit = String(ligneGpnc[mGpnc.libelle] ?? "").trim();
    if (!produit || produit.toLowerCase() === "nan") continue;
    const cipGpnc = mGpnc.cip ? normaliserCip(ligneGpnc[mGpnc.cip]) : "";

    const corr = apparier(produit, cipGpnc, indexCad);
    if (corr.incertain && corr.index !== null) {
      matchsIncertains.push({
        produitGpnc: produit,
        rapprocheDe: String(cadencier[corr.index][mCad.libelle]),
        score: arrondi1(corr.score),
        fichier: "cadencier",
      });
    }

    // --- Date de réappro annoncée ---
    let dateReappro = mGpnc.dateReappro ? parserDate(ligneGpnc[mGpnc.dateReappro]) : null;
    let joursAvant: number | null = null;
    if (dateReappro) {
      joursAvant = ecartJours(dateReappro, dateAnalyse);
      if (joursAvant < 0) {
        alertes.push(
          `${produit} : date de réappro dépassée (${jourFr(dateReappro)}) — traité comme sans date.`,
        );
        dateReappro = null;
        joursAvant = null;
      }
    }

    const base = {
      produit,
      dateReappro: dateReappro ? jourFr(dateReappro) : "",
      joursAvantReappro: (joursAvant ?? "") as number | "",
    };

    // Fiabilité de la date annoncée : a-t-elle déjà été repoussée ?
    const reports = compterReports(annoncesReappro.get(produit) ?? [], dateReappro);
    const avertReports = reports
      ? ` · ⚠️ réappro déjà repoussée ${reports} fois (date peu fiable)`
      : "";

    // --- Étape 1 : le produit est-il vendu ? ---
    if (corr.index === null) {
      onglet3.push({
        ...base, vendu: "N", stockActuel: "", commandeEnCours: "", rotationMois: "",
        fiabiliteRotation: "", stockJours: "", peremption: "", dispoUnipharma: "",
        decision: "Écarté", onglet: "—", motif: "Absent du cadencier (non vendu)",
      });
      continue;
    }

    const ligneCad = cadencier[corr.index];
    traites.add(corr.index);
    const { stock, enCours, ventes, rotation, nbCorriges } = infos[corr.index];
    const classe = classes[corr.index] ?? "C";
    const stockEffectif = stock + enCours;
    const afficheEnCours: number | "" = mCad.commandeEnCours ? enCours : "";

    // --- Péremption : alerte informative, n'écarte pas le produit ---
    const datePeremption = mCad.peremption ? parserDate(ligneCad[mCad.peremption]) : null;
    let affichePeremption = "";
    if (datePeremption) {
      affichePeremption = jourFr(datePeremption);
      const joursAvantPeremption = ecartJours(datePeremption, dateAnalyse);
      if (joursAvantPeremption >= 0 && joursAvantPeremption <= SEUIL_ALERTE_PEREMPTION_JOURS) {
        alertes.push(
          `${produit} : péremption proche (${affichePeremption}, dans ${joursAvantPeremption} j) — vérifier le stock avant de commander davantage.`,
        );
      }
    }

    const tendance = calculerTendance(ventes);
    const fiabilite = nbCorriges
      ? `🔧 corrigée (${nbCorriges} mois de rupture)`
      : rotationPossiblementSousEstimee(ventes)
        ? "⚠️ rupture passée possible"
        : "OK";

    if (rotation <= 0) {
      // Rupture LONGUE : ventes écrasées à 0 sur toute la période, mais le
      // produit était déjà signalé → ne pas l'écarter en silence.
      const dejaSignale = compterOccurrencesHistorique(produit, p.historique, dateAnalyse);
      let decision = "Écarté";
      let motif = "Rotation nulle (produit non vendu)";
      if (dejaSignale > 0) {
        alertes.push(
          `${produit} : ventes à 0 sur toute la période mais déjà signalé ${dejaSignale} fois — rupture longue probable, rotation incalculable ; vérifier manuellement (dépannage UNIPHARMA possible).`,
        );
        decision = "À vérifier";
        motif = `Rotation nulle mais déjà signalé ${dejaSignale} fois (rupture longue probable)`;
      }
      onglet3.push({
        ...base, vendu: "N", stockActuel: stock, commandeEnCours: afficheEnCours,
        rotationMois: 0, fiabiliteRotation: "", stockJours: "",
        peremption: affichePeremption, dispoUnipharma: "", decision, onglet: "—", motif,
      });
      continue;
    }

    // --- Étapes 2-3 : couverture et règle d'apparition stricte ---
    // Le stock EFFECTIF (physique + commandes en cours) sert de base : une
    // commande déjà partie ne doit pas être recommandée.
    const stockJours = calculerStockJours(stockEffectif, rotation);
    const detail = {
      ...base, vendu: "O", stockActuel: stock, commandeEnCours: afficheEnCours,
      rotationMois: arrondi1(rotation), fiabiliteRotation: fiabilite,
      stockJours: arrondi1(stockJours), peremption: affichePeremption,
    };

    if (!doitApparaitre(stockJours, joursAvant)) {
      let motif =
        joursAvant !== null
          ? `Stock (${Math.round(stockJours)} j) couvre jusqu'à la réappro (${joursAvant} j)`
          : `Stock (${Math.round(stockJours)} j) ≥ 30 j de couverture`;

      // Écarté de JUSTESSE : la règle stricte tient, mais avec si peu de
      // marge qu'un glissement de réappro suffirait.
      const marge = stockJours - (joursAvant ?? COUVERTURE_SANS_DATE_JOURS);
      if (marge < p.seuilMargeJours) {
        if (reports) {
          alertes.push(
            `${produit} : écarté de justesse ALORS QUE la réappro a déjà été repoussée ${reports} fois — risque fort de rupture sèche.`,
          );
        }
        justesse.push({
          produit, stockActuel: stock, rotationMois: arrondi1(rotation),
          stockJours: arrondi1(stockJours),
          dateReapproGpnc: base.dateReappro,
          joursAvantReappro: base.joursAvantReappro,
          margeJours: arrondi1(marge),
          commentaire:
            (joursAvant !== null
              ? "Écarté par la règle stricte mais marge faible — si la réappro glisse, rupture sèche. Surveiller / dépanner au besoin."
              : "Sans date de réappro, à peine au-dessus des 30 j de couverture — surveiller la rotation.") +
            avertReports,
        });
        motif += ` — de justesse (${arrondi1(marge).toFixed(1)} j de marge)`;
      }
      onglet3.push({ ...detail, dispoUnipharma: "", decision: "Écarté", onglet: "—", motif });
      continue;
    }

    // --- Étape 4 : dépannage UNIPHARMA possible ? ---
    const corrUni = apparier(produit, cipGpnc, indexUni);
    if (corrUni.incertain && corrUni.index !== null) {
      matchsIncertains.push({
        produitGpnc: produit,
        rapprocheDe: String(rupturesUnipharma[corrUni.index][mUni.libelle]),
        score: arrondi1(corrUni.score),
        fichier: "ruptures UNIPHARMA",
      });
    }
    const urgence = classerUrgence(stockEffectif, stockJours);

    if (corrUni.index !== null) {
      // Rupture chez les DEUX fournisseurs : aucune solution d'achat.
      onglet2.push({
        produit, stockActuel: stock, rotationMois: arrondi1(rotation),
        stockJours: arrondi1(stockJours), dateReapproGpnc: base.dateReappro,
        peremption: affichePeremption,
        commentaire:
          "Anticiper l'information patient ; contacter GPNC pour confirmer la date de réappro." +
          avertReports,
        _rotation: rotation, _stock: stock,
      });
      if (reports) {
        alertes.push(
          `${produit} : rupture chez les deux ET réappro déjà repoussée ${reports} fois — confirmer la date avec GPNC.`,
        );
      }
      onglet3.push({
        ...detail, dispoUnipharma: "N", decision: "Retenu", onglet: "Onglet 2",
        motif: "Rupture GPNC + UNIPHARMA (pas de solution)",
      });
      continue;
    }

    // --- Étape 5 : quantité à commander ---
    // Le délai de livraison s'ajoute à la couverture cible : les boîtes
    // commandées aujourd'hui n'arrivent pas aujourd'hui.
    const cibleSansDate = p.politiqueAbc
      ? (COUVERTURE_ABC[classe] ?? COUVERTURE_SANS_DATE_JOURS)
      : COUVERTURE_SANS_DATE_JOURS;
    const couvertureCible = (joursAvant ?? cibleSansDate) + p.delaiLivraisonJours;

    let conditionnement: number | null = null;
    if (mCad.conditionnement) {
      const c = parserNombre(ligneCad[mCad.conditionnement]);
      conditionnement = c > 1 ? c : null;
    }
    const cmd = quantiteACommander(rotation, couvertureCible, stockEffectif, conditionnement);

    let commentaire =
      joursAvant !== null
        ? "Dépannage jusqu'à la réappro GPNC"
        : `Pas de date de réappro → objectif ${cibleSansDate} j de couverture`;
    if (enCours) commentaire += ` · ${enCours} déjà en commande (déduit du calcul)`;
    commentaire += avertReports;
    if (reports) {
      alertes.push(
        `${produit} : la date de réappro GPNC a déjà été repoussée ${reports} fois — ne pas compter dessus, privilégier le dépannage.`,
      );
    }

    const proba7 = probabiliteRupture(stockEffectif, rotation, ventes, 7);
    onglet1.push({
      priorite: scorePriorite(proba7, classe, reports, joursAvant === null),
      urgence, classe, produit, stockActuel: stock, commandeEnCours: afficheEnCours,
      rotationMois: arrondi1(rotation), tendance, fiabiliteRotation: fiabilite,
      stockJours: arrondi1(stockJours),
      probaRupture7j: `${Math.round(proba7 * 100)}%`,
      dateReapproGpnc: base.dateReappro,
      joursAvantReappro: base.joursAvantReappro,
      peremption: affichePeremption, qteACommander: cmd, commentaire,
      _stockJours: stockJours,
    });
    onglet3.push({
      ...detail, dispoUnipharma: "O", decision: "Retenu", onglet: "Onglet 1",
      motif: `À commander chez UNIPHARMA (${urgence})`,
    });
  }

  // --- Vigilance : anticiper les ruptures de VOTRE stock ---
  // Produits du cadencier HORS liste GPNC dont la couverture passe sous le
  // seuil : la rupture en rayon arrive, autant commander avant.
  const vigilance: (LigneVigilance & { _stockJours: number })[] = [];
  infos.forEach((info, idx) => {
    if (traites.has(idx)) return;
    const { stock, enCours, ventes, rotation } = info;
    if (rotation <= 0 || rotation < p.rotationMinVigilance) return;
    const stockJours = calculerStockJours(stock + enCours, rotation);
    if (stockJours >= p.seuilVigilanceJours) return;

    const classe = classes[idx] ?? "C";
    const proba7 = probabiliteRupture(stock + enCours, rotation, ventes, 7);
    vigilance.push({
      priorite: scorePriorite(proba7, classe),
      classe,
      produit: String(cadencier[idx][mCad.libelle] ?? "").trim(),
      stockActuel: stock,
      commandeEnCours: mCad.commandeEnCours ? enCours : "",
      rotationMois: arrondi1(rotation),
      tendance: calculerTendance(ventes),
      stockJours: arrondi1(stockJours),
      probaRupture7j: `${Math.round(proba7 * 100)}%`,
      conseil: "Hors ruptures GPNC identifiées — commander avant la rupture en rayon.",
      _stockJours: stockJours,
    });
  });

  // --- Tris : le score de priorité ordonne la liste du matin ---
  onglet1.sort((a, b) => b.priorite - a.priorite || a._stockJours - b._stockJours);
  onglet2.sort(
    (a, b) => Number(b._stock <= 0) - Number(a._stock <= 0) || b._rotation - a._rotation,
  );
  vigilance.sort((a, b) => b.priorite - a.priorite || a._stockJours - b._stockJours);
  justesse.sort((a, b) => a.margeJours - b.margeJours);

  const resume: ResumeRuptures = {
    rupturesGpnc: rupturesGpnc.length,
    analyses: onglet3.length,
    vendus: onglet3.filter((l) => l.vendu === "O").length,
    aCommander: onglet1.length,
    sansSolution: onglet2.length,
    urgents: onglet1.filter((l) => l.urgence === URGENT).length,
    moderes: onglet1.filter((l) => l.urgence === MODERE).length,
    anticiper: onglet1.filter((l) => l.urgence === ANTICIPER).length,
    rotationDouteuse: onglet1.filter(
      (l) => l.fiabiliteRotation === "⚠️ rupture passée possible",
    ).length,
    peremptionProche: alertes.filter((a) => a.includes("péremption proche")).length,
    vigilance: vigilance.length,
    justesse: justesse.length,
  };

  return {
    onglet1: onglet1.map(sansInterne),
    onglet2: onglet2.map(sansInterne),
    onglet3,
    vigilance: vigilance.map(sansInterne),
    ecartesJustesse: justesse,
    resume,
    alertes,
    matchsIncertains,
  };
}

/** Nom conventionnel du fichier de commande généré. */
export function nomFichierSortie(dateAnalyse: Date): string {
  const iso = [
    dateAnalyse.getFullYear(),
    String(dateAnalyse.getMonth() + 1).padStart(2, "0"),
    String(dateAnalyse.getDate()).padStart(2, "0"),
  ].join("-");
  return `commande_ruptures_${iso}.xlsx`;
}
