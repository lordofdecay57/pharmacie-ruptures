/**
 * Export Excel — portage de `exporter_classeur`, `exporter_excel` et
 * `exporter_stock_rotation_excel` (Python/openpyxl) vers ExcelJS.
 *
 * Mise en forme commune aux deux modules : en-têtes gras figés sur fond gris,
 * largeurs de colonnes automatiques, lignes teintées selon la valeur d'une
 * colonne (Alerte pour le stock, Urgence pour les ruptures).
 */

import ExcelJS from "exceljs";

import type { LigneDormant, LigneStock, ResultatStockRotation } from "../calculs/stock-rotation";
import type {
  LigneACommander,
  LigneAnalyseComplete,
  LigneJustesse,
  LigneSansSolution,
  LigneVigilance,
  ResultatRuptures,
} from "../calculs/ruptures-analyse";
import { ANTICIPER, MODERE, URGENT } from "../calculs/ruptures";

/** Valeur affichable dans une cellule : le vide reste vide, pas « null ». */
export type Cellule = string | number | null;

export interface Onglet {
  nom: string;
  colonnes: string[];
  lignes: Cellule[][];
}

/** Couleurs de ligne, par valeur de la colonne pilote (code ARGB openpyxl). */
export type CouleursParColonne = Record<string, Record<string, string>>;

const COULEUR_ENTETE = "FFD9D9D9";
const LARGEUR_MAX = 45;
/** Au-delà, la largeur automatique coûterait plus qu'elle n'apporte. */
const LIGNES_MESUREES = 200;

/** Excel refuse ces caractères — et tronque les noms d'onglet à 31 signes. */
function nomFeuilleValide(nom: string): string {
  return nom.replace(/[\\/*?:[\]]/g, " ").slice(0, 31) || "Feuille";
}

function largeurColonne(titre: string, lignes: Cellule[][], index: number): number {
  let largeur = titre.length;
  for (const ligne of lignes.slice(0, LIGNES_MESUREES)) {
    const valeur = ligne[index];
    const taille = valeur === null || valeur === undefined ? 0 : String(valeur).length;
    if (taille > largeur) largeur = taille;
  }
  return Math.min(largeur + 3, LARGEUR_MAX);
}

/**
 * Classeur commun : un onglet par tableau, en-tête figé, largeurs auto et
 * code couleur optionnel. Renvoie le fichier .xlsx en mémoire.
 */
export async function exporterClasseur(
  onglets: Onglet[],
  couleursParColonne: CouleursParColonne = {},
): Promise<Uint8Array> {
  const classeur = new ExcelJS.Workbook();
  classeur.created = new Date();

  for (const onglet of onglets) {
    const feuille = classeur.addWorksheet(nomFeuilleValide(onglet.nom));
    feuille.addRow(onglet.colonnes);
    for (const ligne of onglet.lignes) {
      feuille.addRow(ligne.map((v) => (v === null ? "" : v)));
    }

    feuille.views = [{ state: "frozen", ySplit: 1 }];
    const entete = feuille.getRow(1);
    entete.font = { bold: true };
    entete.alignment = { vertical: "middle" };
    entete.eachCell((cellule) => {
      cellule.fill = { type: "pattern", pattern: "solid", fgColor: { argb: COULEUR_ENTETE } };
    });

    onglet.colonnes.forEach((titre, i) => {
      feuille.getColumn(i + 1).width = largeurColonne(titre, onglet.lignes, i);
    });

    for (const [colonne, couleurs] of Object.entries(couleursParColonne)) {
      const index = onglet.colonnes.indexOf(colonne);
      if (index === -1) continue;
      onglet.lignes.forEach((ligne, i) => {
        const couleur = couleurs[String(ligne[index] ?? "")];
        if (!couleur) return;
        feuille.getRow(i + 2).eachCell((cellule) => {
          cellule.fill = { type: "pattern", pattern: "solid", fgColor: { argb: couleur } };
        });
      });
    }
  }

  const tampon = await classeur.xlsx.writeBuffer();
  return new Uint8Array(tampon as ArrayBuffer);
}

// ---------------------------------------------------------------------------
// Module 1 — stock en rotation
// ---------------------------------------------------------------------------

const COULEURS_ALERTE: Record<string, string> = {
  "🔴 Action requise": "FFF8CBAD",
  "🟡 Sous le min": "FFFFE699",
  "🟢 OK": "FFC6EFCE",
  "⚪ Rotation faible": "FFE7E6E1",
};

export const COLONNES_STOCK_ROTATION = [
  "Alerte",
  "Classe",
  "Code CIP",
  "Nom du produit",
  "Stock actuel",
  "Commande en cours",
  "Consommation/mois",
  "Tendance",
  "Variabilité",
  "Stock min (calculé)",
  "Stock max (calculé)",
  "Stock min conseillé (variabilité)",
  "Cible réassort",
  "Qté à commander",
  "Motif",
];

export const COLONNES_DORMANTS = [
  "Code CIP",
  "Nom du produit",
  "Stock actuel",
  "Consommation/mois",
  "Stock (jours)",
  "Stock max (calculé)",
  "Commentaire",
];

/** Une couverture infinie (aucune vente) s'affiche en texte, pas en nombre. */
function jours(valeur: number): Cellule {
  return Number.isFinite(valeur) ? Math.round(valeur * 10) / 10 : "∞";
}

export function lignesStockEnTableau(lignes: LigneStock[]): Cellule[][] {
  return lignes.map((l) => [
    l.alerte,
    l.classe,
    l.codeCip,
    l.nomProduit,
    l.stockActuel,
    l.commandeEnCours ?? "",
    l.consommationMois,
    l.tendance,
    l.variabilite,
    l.stockMin,
    l.stockMax,
    l.stockMinConseille,
    l.cibleReassort,
    l.qteACommander,
    l.motif,
  ]);
}

export function lignesDormantsEnTableau(lignes: LigneDormant[]): Cellule[][] {
  return lignes.map((l) => [
    l.codeCip,
    l.nomProduit,
    l.stockActuel,
    l.consommationMois,
    jours(l.stockJours),
    l.stockMax,
    l.commentaire,
  ]);
}

/**
 * Classeur de gestion du stock en rotation : min/max + dormants.
 *
 * Le fichier étant le bon de commande, les produits « ⚪ Rotation faible »
 * (écartés du réassort automatique) n'y figurent pas — ils restent
 * consultables dans l'application.
 */
export function exporterStockRotationExcel(
  resultat: ResultatStockRotation,
): Promise<Uint8Array> {
  const pilotes = resultat.tableau.filter((l) => l.alerte !== "⚪ Rotation faible");
  return exporterClasseur(
    [
      {
        nom: "Stock min-max",
        colonnes: COLONNES_STOCK_ROTATION,
        lignes: lignesStockEnTableau(pilotes),
      },
      {
        nom: "Stock dormant",
        colonnes: COLONNES_DORMANTS,
        lignes: lignesDormantsEnTableau(resultat.dormants),
      },
    ],
    { Alerte: COULEURS_ALERTE },
  );
}

// ---------------------------------------------------------------------------
// Module 2 — ruptures fournisseurs
// ---------------------------------------------------------------------------

const COULEURS_URGENCE: Record<string, string> = {
  [URGENT]: "FFF8CBAD",
  [MODERE]: "FFFFE699",
  [ANTICIPER]: "FFC6EFCE",
};

export const COLONNES_A_COMMANDER = [
  "Priorité",
  "Urgence",
  "Classe",
  "Produit",
  "Stock actuel",
  "Commande en cours",
  "Rotation/mois",
  "Tendance",
  "Fiabilité rotation",
  "Stock (jours)",
  "P(rupture 7 j)",
  "Date réappro GPNC",
  "Jours avant réappro",
  "Péremption",
  "Qté à commander (Cmd)",
  "Commentaire",
];

export const COLONNES_SANS_SOLUTION = [
  "Produit",
  "Stock actuel",
  "Rotation/mois",
  "Stock (jours)",
  "Date réappro GPNC",
  "Péremption",
  "Commentaire",
];

export const COLONNES_VIGILANCE = [
  "Priorité",
  "Classe",
  "Produit",
  "Stock actuel",
  "Commande en cours",
  "Rotation/mois",
  "Tendance",
  "Stock (jours)",
  "P(rupture 7 j)",
  "Conseil",
];

export const COLONNES_JUSTESSE = [
  "Produit",
  "Stock actuel",
  "Rotation/mois",
  "Stock (jours)",
  "Date réappro GPNC",
  "Jours avant réappro",
  "Marge (jours)",
  "Commentaire",
];

export const COLONNES_ANALYSE_COMPLETE = [
  "Produit",
  "Date réappro",
  "Jours avant réappro",
  "Vendu (O/N)",
  "Stock actuel",
  "Commande en cours",
  "Rotation/mois",
  "Fiabilité rotation",
  "Stock (jours)",
  "Péremption",
  "Dispo UNIPHARMA (O/N)",
  "Décision",
  "Onglet",
  "Motif",
];

export function lignesACommanderEnTableau(lignes: LigneACommander[]): Cellule[][] {
  return lignes.map((l) => [
    l.priorite,
    l.urgence,
    l.classe,
    l.produit,
    l.stockActuel,
    l.commandeEnCours,
    l.rotationMois,
    l.tendance,
    l.fiabiliteRotation,
    l.stockJours,
    l.probaRupture7j,
    l.dateReapproGpnc,
    l.joursAvantReappro,
    l.peremption,
    l.qteACommander,
    l.commentaire,
  ]);
}

export function lignesSansSolutionEnTableau(lignes: LigneSansSolution[]): Cellule[][] {
  return lignes.map((l) => [
    l.produit,
    l.stockActuel,
    l.rotationMois,
    l.stockJours,
    l.dateReapproGpnc,
    l.peremption,
    l.commentaire,
  ]);
}

export function lignesVigilanceEnTableau(lignes: LigneVigilance[]): Cellule[][] {
  return lignes.map((l) => [
    l.priorite,
    l.classe,
    l.produit,
    l.stockActuel,
    l.commandeEnCours,
    l.rotationMois,
    l.tendance,
    l.stockJours,
    l.probaRupture7j,
    l.conseil,
  ]);
}

export function lignesJustesseEnTableau(lignes: LigneJustesse[]): Cellule[][] {
  return lignes.map((l) => [
    l.produit,
    l.stockActuel,
    l.rotationMois,
    l.stockJours,
    l.dateReapproGpnc,
    l.joursAvantReappro,
    l.margeJours,
    l.commentaire,
  ]);
}

export function lignesAnalyseCompleteEnTableau(
  lignes: LigneAnalyseComplete[],
): Cellule[][] {
  return lignes.map((l) => [
    l.produit,
    l.dateReappro,
    l.joursAvantReappro,
    l.vendu,
    l.stockActuel,
    l.commandeEnCours,
    l.rotationMois,
    l.fiabiliteRotation,
    l.stockJours,
    l.peremption,
    l.dispoUnipharma,
    l.decision,
    l.onglet,
    l.motif,
  ]);
}

/** Classeur de décision : les 5 onglets de l'analyse des ruptures. */
export function exporterRupturesExcel(resultat: ResultatRuptures): Promise<Uint8Array> {
  return exporterClasseur(
    [
      {
        nom: "À commander UNIPHARMA",
        colonnes: COLONNES_A_COMMANDER,
        lignes: lignesACommanderEnTableau(resultat.onglet1),
      },
      {
        nom: "Rupture GPNC+UNIPHARMA",
        colonnes: COLONNES_SANS_SOLUTION,
        lignes: lignesSansSolutionEnTableau(resultat.onglet2),
      },
      {
        nom: "Vigilance stock",
        colonnes: COLONNES_VIGILANCE,
        lignes: lignesVigilanceEnTableau(resultat.vigilance),
      },
      {
        nom: "Écartés de justesse",
        colonnes: COLONNES_JUSTESSE,
        lignes: lignesJustesseEnTableau(resultat.ecartesJustesse),
      },
      {
        nom: "Analyse complète",
        colonnes: COLONNES_ANALYSE_COMPLETE,
        lignes: lignesAnalyseCompleteEnTableau(resultat.onglet3),
      },
    ],
    { Urgence: COULEURS_URGENCE },
  );
}

// ---------------------------------------------------------------------------
// Noms de fichiers et téléchargement
// ---------------------------------------------------------------------------

function jourIso(date: Date): string {
  const mois = String(date.getMonth() + 1).padStart(2, "0");
  const jour = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${mois}-${jour}`;
}

/** Nom conventionnel d'un fichier généré : `prefixe_AAAA-MM-JJ.xlsx`. */
export function nomFichierExport(prefixe: string, dateAnalyse: Date): string {
  return `${prefixe}_${jourIso(dateAnalyse)}.xlsx`;
}

const MIME_XLSX =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** Déclenche le téléchargement du classeur depuis le navigateur. */
export function telechargerClasseur(contenu: Uint8Array, nomFichier: string): void {
  const blob = new Blob([contenu as BlobPart], { type: MIME_XLSX });
  const url = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = nomFichier;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(url);
}
