import ExcelJS from "exceljs";
import { describe, expect, it } from "vitest";

import {
  COLONNES_STOCK_ROTATION,
  exporterClasseur,
  exporterStockRotationExcel,
  nomFichierExport,
} from "./export-excel";
import type { ResultatStockRotation, LigneStock } from "../calculs/stock-rotation";

async function relire(contenu: Uint8Array): Promise<ExcelJS.Workbook> {
  const classeur = new ExcelJS.Workbook();
  await classeur.xlsx.load(contenu as unknown as ArrayBuffer);
  return classeur;
}

function ligne(partiel: Partial<LigneStock>): LigneStock {
  return {
    alerte: "🟢 OK",
    classe: "B",
    codeCip: "1234567",
    nomProduit: "PRODUIT",
    stockActuel: 10,
    commandeEnCours: null,
    consommationMois: 5,
    tendance: "→ stable",
    variabilite: "régulière",
    stockMin: 3,
    stockMax: 5,
    stockMinConseille: 3,
    cibleReassort: 0,
    qteACommander: 0,
    motif: "",
    stockJours: 60,
    consommationExacte: 5,
    ...partiel,
  };
}

describe("exporterClasseur", () => {
  it("écrit un onglet par tableau avec l'en-tête en première ligne", async () => {
    const contenu = await exporterClasseur([
      { nom: "Un", colonnes: ["A", "B"], lignes: [["x", 1]] },
      { nom: "Deux", colonnes: ["C"], lignes: [] },
    ]);
    const classeur = await relire(contenu);
    expect(classeur.worksheets.map((f) => f.name)).toEqual(["Un", "Deux"]);
    const feuille = classeur.getWorksheet("Un")!;
    expect(feuille.getRow(1).values).toEqual([undefined, "A", "B"]);
    expect(feuille.getRow(2).values).toEqual([undefined, "x", 1]);
  });

  it("fige l'en-tête et le met en gras", async () => {
    const contenu = await exporterClasseur([
      { nom: "Un", colonnes: ["A"], lignes: [["x"]] },
    ]);
    const feuille = (await relire(contenu)).getWorksheet("Un")!;
    expect(feuille.getRow(1).getCell(1).font?.bold).toBe(true);
    expect(feuille.views[0]).toMatchObject({ state: "frozen", ySplit: 1 });
  });

  it("teinte les lignes selon la colonne pilote", async () => {
    const contenu = await exporterClasseur(
      [
        {
          nom: "Un",
          colonnes: ["Alerte", "Nom"],
          lignes: [
            ["rouge", "A"],
            ["autre", "B"],
          ],
        },
      ],
      { Alerte: { rouge: "FFF8CBAD" } },
    );
    const feuille = (await relire(contenu)).getWorksheet("Un")!;
    const teinte = (n: number) =>
      (feuille.getRow(n).getCell(1).fill as ExcelJS.FillPattern | undefined)?.fgColor?.argb;
    expect(teinte(2)).toBe("FFF8CBAD");
    expect(teinte(3)).toBeUndefined();
  });

  it("ignore le code couleur quand la colonne pilote est absente", async () => {
    const contenu = await exporterClasseur(
      [{ nom: "Un", colonnes: ["Nom"], lignes: [["rouge"]] }],
      { Alerte: { rouge: "FFF8CBAD" } },
    );
    const feuille = (await relire(contenu)).getWorksheet("Un")!;
    expect((feuille.getRow(2).getCell(1).fill as ExcelJS.FillPattern | undefined)?.fgColor)
      .toBeUndefined();
  });

  it("assainit les noms d'onglet interdits par Excel", async () => {
    const contenu = await exporterClasseur([
      { nom: "Stock/Min: 2024", colonnes: ["A"], lignes: [] },
    ]);
    expect((await relire(contenu)).worksheets[0].name).toBe("Stock Min  2024");
  });

  it("adapte la largeur des colonnes au contenu, sans dépasser 45", async () => {
    const contenu = await exporterClasseur([
      { nom: "Un", colonnes: ["A"], lignes: [["x".repeat(80)]] },
    ]);
    expect((await relire(contenu)).getWorksheet("Un")!.getColumn(1).width).toBe(45);
  });
});

describe("exporterStockRotationExcel", () => {
  const resultat: ResultatStockRotation = {
    tableau: [
      ligne({ nomProduit: "PILOTE", alerte: "🔴 Action requise", qteACommander: 4 }),
      ligne({ nomProduit: "DORMANT LENT", alerte: "⚪ Rotation faible" }),
    ],
    dormants: [
      {
        codeCip: "999",
        nomProduit: "VIEUX STOCK",
        stockActuel: 40,
        consommationMois: 0,
        stockJours: Infinity,
        stockMax: 0,
        commentaire: "Aucune vente",
      },
    ],
    resume: {
      totalProduits: 2,
      actionRequise: 1,
      sousLeMin: 0,
      rotationFaible: 1,
      nbA: 0,
      nbB: 2,
      nbC: 0,
      dormants: 1,
      dormantsBoites: 40,
      qteTotaleACommander: 4,
      joursWeekend: 0,
      doublonsFusionnes: 0,
    },
  };

  it("produit les deux onglets attendus", async () => {
    const classeur = await relire(await exporterStockRotationExcel(resultat));
    expect(classeur.worksheets.map((f) => f.name)).toEqual([
      "Stock min-max",
      "Stock dormant",
    ]);
    expect(classeur.getWorksheet("Stock min-max")!.getRow(1).values).toEqual([
      undefined,
      ...COLONNES_STOCK_ROTATION,
    ]);
  });

  it("écarte du bon de commande les produits à rotation faible", async () => {
    const feuille = (await relire(await exporterStockRotationExcel(resultat)))
      .getWorksheet("Stock min-max")!;
    expect(feuille.rowCount).toBe(2); // en-tête + le seul produit piloté
    expect(feuille.getRow(2).getCell(4).value).toBe("PILOTE");
  });

  it("teinte la ligne selon l'alerte", async () => {
    const feuille = (await relire(await exporterStockRotationExcel(resultat)))
      .getWorksheet("Stock min-max")!;
    const fond = feuille.getRow(2).getCell(1).fill as ExcelJS.FillPattern;
    expect(fond.fgColor?.argb).toBe("FFF8CBAD");
  });

  it("affiche une couverture infinie en texte", async () => {
    const feuille = (await relire(await exporterStockRotationExcel(resultat)))
      .getWorksheet("Stock dormant")!;
    expect(feuille.getRow(2).getCell(5).value).toBe("∞");
  });
});

describe("nomFichierExport", () => {
  it("date le fichier au format AAAA-MM-JJ", () => {
    expect(nomFichierExport("stock_min_max", new Date(2026, 6, 3))).toBe(
      "stock_min_max_2026-07-03.xlsx",
    );
  });
});
