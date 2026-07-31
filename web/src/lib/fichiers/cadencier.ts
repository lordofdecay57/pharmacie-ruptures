/**
 * Lecture des fichiers déposés par la pharmacie.
 *
 * Portage de la logique de chargement de `commun.py`, en particulier du
 * parseur dédié au cadencier WinPharma exporté en CSV : bandeau d'en-tête,
 * colonnes d'ACHATS « (A) » à ignorer, colonnes de VENTES « (V) » en ordre
 * anti-chronologique à remettre à l'endroit, ligne de totaux à écarter.
 */

import Papa from "papaparse";
import { normaliserLibelle } from "../calculs/commun";

export interface CadencierCharge {
  colonnes: string[];
  lignes: Record<string, unknown>[];
  /** Vrai si le format WinPharma a été reconnu et normalisé. */
  formatWinPharma: boolean;
}

/**
 * Décode un fichier texte. Les exports WinPharma sont en ISO-8859-1 ; on
 * tente d'abord l'UTF-8 et on bascule si le résultat contient le caractère
 * de remplacement (signe d'un mauvais décodage).
 */
export function decoderTexte(donnees: ArrayBuffer): string {
  const utf8 = new TextDecoder("utf-8").decode(donnees);
  if (!utf8.includes("�")) return utf8.replace(/^﻿/, "");
  return new TextDecoder("iso-8859-1").decode(donnees);
}

/** Sépare une ligne CSV en respectant les guillemets. */
function decouper(ligne: string, sep: string): string[] {
  const res = Papa.parse<string[]>(ligne, { delimiter: sep });
  return (res.data[0] ?? []).map((c) => String(c ?? "").trim());
}

/**
 * Cadencier WinPharma (CSV) → tableau normalisé.
 *
 * Renvoie `null` si le texte n'est pas un cadencier WinPharma, afin de
 * laisser la main au chargeur CSV générique.
 *
 * Format observé : bandeau de la pharmacie, puis en-tête
 * `CIP;Code13Réf;Nom;"Formes & presentations";Stock` suivi de 12 mois
 * d'achats « (A) » et 12 mois de ventes « (V) » du plus RÉCENT au plus
 * ancien, plus des colonnes « Total ». Seules les ventes sont retenues, dans
 * l'ordre chronologique ; le Code13Réf (13 chiffres) est préféré au CIP court
 * pour les appariements.
 */
export function parserCadencierWinPharma(texte: string): CadencierCharge | null {
  const lignes = texte.split(/\r?\n/);
  const iEntete = lignes.findIndex((l, i) => {
    if (i > 40) return false;
    const premier = (l.split(";")[0] ?? "").trim().replace(/^"|"$/g, "");
    return premier.toUpperCase() === "CIP" && l.includes("(V)");
  });
  if (iEntete === -1) return null;

  const entetes = decouper(lignes[iEntete], ";");
  const iVentes: number[] = [];
  entetes.forEach((h, i) => {
    // Colonnes de ventes mensuelles, hors totaux.
    if (/\(V\)\s*$/.test(h) && !/^total/i.test(h)) iVentes.push(i);
  });
  if (iVentes.length === 0) return null;

  const indexDe = (predicat: (h: string) => boolean) =>
    entetes.findIndex((h) => predicat(normaliserLibelle(h)));
  const iCip = indexDe((h) => h === "CIP");
  const iCode13 = indexDe((h) => h.startsWith("CODE13"));
  const iNom = indexDe((h) => h === "NOM");
  const iStock = indexDe((h) => h === "STOCK");

  // Ventes remises en ordre CHRONOLOGIQUE (le fichier les liste à l'envers).
  const iVentesChrono = [...iVentes].reverse();
  const colonnesVentes = iVentesChrono.map(
    (i) => `Ventes ${entetes[i].replace(/\(V\)/, "").trim()}`,
  );
  const colonnes = ["Produit", "CIP", "Stock", ...colonnesVentes];

  const sortie: Record<string, unknown>[] = [];
  for (const brute of lignes.slice(iEntete + 1)) {
    if (!brute.trim()) continue;
    const cellules = decouper(brute, ";");
    if (cellules.length < entetes.length - 2) continue;

    const nom = (iNom >= 0 ? cellules[iNom] : "").replace(/\s+/g, " ").trim();
    // Ligne de totaux finale (« Qte : 3621 », « Manque : -8 ») : écartée.
    if (/^(qte|manque)\s*:/i.test(nom)) continue;

    const chiffres = (v: string | undefined) => String(v ?? "").replace(/\D/g, "");
    const codes = [chiffres(cellules[iCode13]), chiffres(cellules[iCip])].filter(
      (c) => c.length >= 6,
    );
    // Le Code13Réf est préféré ; les produits sans code (parapharmacie) sont
    // conservés et s'apparient par libellé.
    const cip = codes.find((c) => c.length === 13) ?? codes[0] ?? "";
    if (!cip && !nom) continue;

    const ligne: Record<string, unknown> = {
      Produit: nom,
      CIP: cip,
      Stock: iStock >= 0 ? cellules[iStock] ?? "0" : "0",
    };
    iVentesChrono.forEach((iCol, k) => {
      ligne[colonnesVentes[k]] = cellules[iCol] ?? "0";
    });
    sortie.push(ligne);
  }

  if (sortie.length === 0) return null;
  return { colonnes, lignes: sortie, formatWinPharma: true };
}

/** Chargeur CSV générique (séparateur détecté automatiquement). */
export function parserCsvGenerique(texte: string): CadencierCharge {
  const resultat = Papa.parse<Record<string, unknown>>(texte, {
    header: true,
    skipEmptyLines: true,
    delimiter: "", // détection automatique (`;` ou `,`)
    transformHeader: (h) => h.trim(),
  });
  const lignes = resultat.data.filter((l) => Object.keys(l).length > 0);
  const colonnes = (resultat.meta.fields ?? []).map((c) => c.trim());
  return { colonnes, lignes, formatWinPharma: false };
}

/**
 * Charge un fichier déposé : cadencier WinPharma si reconnu, sinon CSV
 * générique. Les formats binaires (.xlsx, .pdf) ne sont pas gérés ici.
 */
export function chargerFichierTexte(donnees: ArrayBuffer): CadencierCharge {
  const texte = decoderTexte(donnees);
  return parserCadencierWinPharma(texte) ?? parserCsvGenerique(texte);
}
