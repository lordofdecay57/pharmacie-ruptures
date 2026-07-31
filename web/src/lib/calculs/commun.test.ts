/**
 * Tests du noyau de calculs partagés — portage de `tests/test_commun.py`.
 * Les valeurs attendues sont celles validées sur les données réelles de la
 * pharmacie : toute divergence signale une régression du portage.
 */
import { describe, expect, it } from "vitest";
import {
  calculerRotationMensuelle,
  calculerStockJours,
  calculerTendance,
  classerAbc,
  coefficientVariation,
  corrigerFauxZeros,
  detecterColonne,
  detecterColonnesVentes,
  normaliserCip,
  normaliserLibelle,
  parserDate,
  parserNombre,
  picSaisonnier,
  variabiliteDemande,
  variantesCip,
} from "./commun";

// ---------------------------------------------------------------------------
// Stock en jours
// ---------------------------------------------------------------------------

describe("calculerStockJours", () => {
  it("ozempic : 5 boîtes pour 16,5/mois ≈ 9,1 jours", () => {
    expect(calculerStockJours(5, 16.5)).toBeCloseTo(9.09, 1);
  });

  it("stock nul → 0 jour", () => {
    expect(calculerStockJours(0, 12)).toBe(0);
  });

  it("rotation nulle → couverture infinie", () => {
    expect(calculerStockJours(10, 0)).toBe(Infinity);
  });
});

// ---------------------------------------------------------------------------
// Rotation
// ---------------------------------------------------------------------------

describe("calculerRotationMensuelle", () => {
  const VENTES = [10, 10, 10, 10, 10, 10, 10, 10, 10, 20, 20, 20]; // récent en dernier

  it("annuelle : moyenne de tous les mois", () => {
    expect(calculerRotationMensuelle(VENTES, "annuelle")).toBeCloseTo(12.5);
  });

  it("trimestrielle : moyenne des 3 derniers", () => {
    expect(calculerRotationMensuelle(VENTES, "3mois")).toBeCloseTo(20);
  });

  it("semestrielle : moyenne des 6 derniers", () => {
    expect(calculerRotationMensuelle(VENTES, "6mois")).toBeCloseTo(15);
  });

  it("mensuelle : le dernier mois seul", () => {
    expect(calculerRotationMensuelle(VENTES, "1mois")).toBeCloseTo(20);
    expect(calculerRotationMensuelle([5, 8, 30], "1mois")).toBeCloseTo(30);
  });

  it("virgule décimale française", () => {
    expect(calculerRotationMensuelle(["16,5"], "annuelle")).toBeCloseTo(16.5);
  });

  it("série vide → 0", () => {
    expect(calculerRotationMensuelle([], "annuelle")).toBe(0);
  });

  it("lissage exponentiel α=0,4 sur [10,10,20] → 14", () => {
    expect(calculerRotationMensuelle([10, 10, 20], "lissee")).toBeCloseTo(14);
  });

  it("le lissage suit aussi les baisses", () => {
    expect(calculerRotationMensuelle([20, 20, 20, 5, 5, 5], "lissee")).toBeLessThan(10);
  });
});

describe("produit récemment référencé", () => {
  // Les mois à 0 AVANT la première vente ne comptent pas : sinon un
  // générique lancé il y a 4 mois voit sa rotation divisée par 3.
  const LANCE_RECEMMENT = [0, 0, 0, 0, 0, 0, 0, 0, 90, 100, 95, 99];

  it("moyenne calculée depuis la première vente", () => {
    expect(calculerRotationMensuelle(LANCE_RECEMMENT, "annuelle")).toBeCloseTo(96);
  });

  it("lissage calculé depuis la première vente", () => {
    expect(calculerRotationMensuelle(LANCE_RECEMMENT, "lissee")).toBeGreaterThan(90);
  });

  it("les zéros de FIN (arrêt de vente) restent comptés", () => {
    expect(calculerRotationMensuelle([12, 12, 0, 0], "annuelle")).toBeCloseTo(6);
  });

  it("série entièrement nulle → 0", () => {
    expect(calculerRotationMensuelle([0, 0, 0], "annuelle")).toBe(0);
  });

  it("variabilité mesurée depuis la première vente", () => {
    expect(variabiliteDemande([0, 0, 0, 0, 10, 10, 10, 10])).toContain("stable");
  });

  it("pas de faux pic saisonnier dû aux mois d'avant référencement", () => {
    const ventes = [0, 0, 0, 0, 0, 0, 10, 10, 10, 10, 12, 10];
    const noms = Array.from({ length: 12 }, (_, i) => `Ventes M${i}`);
    expect(picSaisonnier(ventes, noms)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Normalisation / parsing
// ---------------------------------------------------------------------------

describe("normalisation", () => {
  it("libellé : majuscules, sans accents, ponctuation réduite", () => {
    expect(normaliserLibelle("  Titanoréine® suppo. B/12 ")).toBe(
      "TITANOREINE SUPPO B 12",
    );
  });

  it("CIP lu en flottant Excel", () => {
    expect(normaliserCip("3400930.0")).toBe("3400930");
  });

  it("CIP « 0 » traité comme absent", () => {
    expect(normaliserCip("0")).toBe("");
    expect(normaliserCip("000")).toBe("");
    expect(normaliserCip(0)).toBe("");
  });

  it("parserNombre : virgule, espaces, vide", () => {
    expect(parserNombre("16,5")).toBeCloseTo(16.5);
    expect(parserNombre("1 234")).toBeCloseTo(1234);
    expect(parserNombre("")).toBe(0);
    expect(parserNombre("abc")).toBe(0);
    expect(parserNombre(null)).toBe(0);
  });

  it("parserDate : formats français en priorité", () => {
    expect(parserDate("03/06/26")).toEqual(new Date(2026, 5, 3));
    expect(parserDate("03/06/2026")).toEqual(new Date(2026, 5, 3));
    expect(parserDate("2026-06-03")).toEqual(new Date(2026, 5, 3));
    expect(parserDate("")).toBeNull();
    expect(parserDate("nan")).toBeNull();
  });
});

describe("variantesCip", () => {
  it("un CIP13 médicament contient son CIP7", () => {
    // Titanoréine : 3400932300778 → 3230077
    expect(variantesCip("3400932300778")).toContain("3230077");
  });

  it("un EAN13 de parapharmacie n'est pas transformé", () => {
    expect(variantesCip("3282770104783")).toEqual(["3282770104783"]);
  });
});

// ---------------------------------------------------------------------------
// Tendance
// ---------------------------------------------------------------------------

describe("calculerTendance", () => {
  it("hausse", () => {
    expect(calculerTendance([10, 10, 10, 10, 10, 20, 20, 20])).toBe("↗ hausse");
  });

  it("baisse", () => {
    expect(calculerTendance([20, 20, 20, 20, 20, 5, 5, 5])).toBe("↘ baisse");
  });

  it("stable", () => {
    expect(calculerTendance([10, 10, 10, 10, 10, 10])).toBe("→ stable");
  });

  it("cadencier court : dernier mois vs précédents", () => {
    expect(calculerTendance([5, 20, 20])).toBe("↗ hausse");
  });

  it("demande nulle → stable", () => {
    expect(calculerTendance([0, 0, 0, 0])).toBe("→ stable");
  });
});

// ---------------------------------------------------------------------------
// Correction des faux zéros (ruptures passées)
// ---------------------------------------------------------------------------

describe("corrigerFauxZeros", () => {
  it("un zéro intérieur est interpolé", () => {
    const { corrigees, nbCorriges } = corrigerFauxZeros([10, 0, 10]);
    expect(corrigees[1]).toBeCloseTo(10);
    expect(nbCorriges).toBe(1);
  });

  it("une série de zéros intérieurs est interpolée", () => {
    const { corrigees, nbCorriges } = corrigerFauxZeros([12, 0, 0, 12]);
    expect(nbCorriges).toBe(2);
    expect(corrigees[1]).toBeGreaterThan(0);
    expect(corrigees[2]).toBeGreaterThan(0);
  });

  it("les zéros de bord sont conservés", () => {
    const { corrigees, nbCorriges } = corrigerFauxZeros([0, 10, 10, 0]);
    expect(corrigees[0]).toBe(0);
    expect(corrigees[3]).toBe(0);
    expect(nbCorriges).toBe(0);
  });

  it("série tout à zéro conservée", () => {
    const { corrigees, nbCorriges } = corrigerFauxZeros([0, 0, 0]);
    expect(corrigees).toEqual([0, 0, 0]);
    expect(nbCorriges).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Classement ABC
// ---------------------------------------------------------------------------

describe("classerAbc", () => {
  it("le plus gros vendeur est toujours A", () => {
    expect(classerAbc([100, 1, 1])[0]).toBe("A");
  });

  it("les volumes nuls sont en C", () => {
    const classes = classerAbc([100, 50, 0]);
    expect(classes[2]).toBe("C");
  });

  it("répartition Pareto 80 / 95 %", () => {
    const classes = classerAbc([80, 15, 5]);
    expect(classes[0]).toBe("A");
    expect(new Set(classes).size).toBeGreaterThan(1);
  });

  it("tout à zéro → tout en C", () => {
    expect(classerAbc([0, 0])).toEqual(["C", "C"]);
  });
});

// ---------------------------------------------------------------------------
// Variabilité / saisonnalité
// ---------------------------------------------------------------------------

describe("variabilité et saisonnalité", () => {
  it("demande stable → CV faible", () => {
    expect(variabiliteDemande([10, 10, 10, 10, 10, 10])).toContain("stable");
  });

  it("demande très variable → forte", () => {
    expect(variabiliteDemande([1, 30, 2, 28, 1, 30])).toContain("forte");
  });

  it("moins de 3 mois de recul → inconnu", () => {
    expect(variabiliteDemande([10, 10])).toBe("");
    expect(coefficientVariation([10, 10])).toBeNull();
  });

  it("pic saisonnier nommé", () => {
    const ventes = [2, 2, 2, 2, 2, 2, 2, 40];
    const noms = ["Ventes jan", "Ventes fev", "Ventes mar", "Ventes avr",
      "Ventes mai", "Ventes juin", "Ventes juil", "Ventes aout"];
    expect(picSaisonnier(ventes, noms)).toContain("aout");
  });

  it("pas de pic sur une demande régulière", () => {
    expect(picSaisonnier([10, 10, 10, 10, 10, 10], [])).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Détection des colonnes
// ---------------------------------------------------------------------------

describe("détection des colonnes", () => {
  it("reconnaît les rôles du cadencier WinPharma", () => {
    const cols = ["Produit", "CIP", "Stock", "Ventes Jul", "Ventes Aou"];
    expect(detecterColonne(cols, "libelle")).toBe("Produit");
    expect(detecterColonne(cols, "cip")).toBe("CIP");
    expect(detecterColonne(cols, "stock")).toBe("Stock");
  });

  it("reconnaît le format réel UNIPHARMA", () => {
    const cols = ["CIP13", "CIP", "Libelle", "Réappro", "Rembt", "TGC", "Situation"];
    expect(detecterColonne(cols, "libelle")).toBe("Libelle");
    expect(detecterColonne(cols, "date_reappro")).toBe("Réappro");
  });

  it("liste les colonnes de ventes mensuelles", () => {
    const cols = ["Produit", "CIP", "Stock", "Ventes Jul", "Ventes Aou", "Ventes Sep"];
    expect(detecterColonnesVentes(cols)).toEqual([
      "Ventes Jul", "Ventes Aou", "Ventes Sep",
    ]);
  });

  it("ne prend pas une colonne texte pour une colonne de ventes", () => {
    expect(detecterColonnesVentes(["CIP", "Stock"])).toEqual([]);
  });
});
