/**
 * Tests du Module 1 — portage de `tests/test_stock_rotation.py`.
 *
 * Couvre les règles métier affinées avec le pharmacien : couvertures 14/30 j,
 * ajustement week-end, seuil des 10 unités en double condition, suppression
 * du stock min pour les petits produits, écart des rotations faibles,
 * garde-fou des modes réactifs, colonne conseillée, comparaison n+1.
 */
import { describe, expect, it } from "vitest";
import {
  type LigneBrute,
  type MappingCadencier,
  analyserStockRotation,
  calculerStockMax,
  calculerStockMin,
  comparerAEtatPrecedent,
  determinerCibleReassort,
  etatStockAEnregistrer,
  joursSupplementairesWeekend,
} from "./stock-rotation";

const MAPPING: MappingCadencier = {
  libelle: "Produit",
  cip: "CIP",
  stock: "Stock",
  ventes: ["Ventes avril", "Ventes mai", "Ventes juin"],
};

const trouver = <T extends { nomProduit: string }>(tableau: T[], nom: string): T =>
  tableau.find((l) => l.nomProduit === nom)!;

// ---------------------------------------------------------------------------
// Bornes de couverture
// ---------------------------------------------------------------------------

describe("calcul des bornes", () => {
  it("stock min = conso/jour × 14 j", () => {
    expect(calculerStockMin(2, 14)).toBeCloseTo(28);
  });

  it("stock min gonflé par les jours week-end", () => {
    expect(calculerStockMin(2, 14, 2)).toBeCloseTo(32);
  });

  it("stock max = conso/jour × 30 j", () => {
    expect(calculerStockMax(2, 30)).toBeCloseTo(60);
  });
});

describe("joursSupplementairesWeekend", () => {
  it("vendredi → +2 jours (commande reçue lundi)", () => {
    expect(joursSupplementairesWeekend(new Date(2026, 4, 15))).toBe(2);
  });

  it("samedi → +1 jour", () => {
    expect(joursSupplementairesWeekend(new Date(2026, 4, 16))).toBe(1);
  });

  it("dimanche à jeudi → aucun ajustement", () => {
    for (const jour of [10, 11, 12, 13, 14, 17]) {
      expect(joursSupplementairesWeekend(new Date(2026, 4, jour))).toBe(0);
    }
  });

  it("sans date → aucun ajustement", () => {
    expect(joursSupplementairesWeekend(null)).toBe(0);
  });

  it("le stock min du vendredi est plus élevé que celui du mardi", () => {
    // Conso 30/mois = 1/j : min 14 en semaine, 16 le vendredi.
    const cadencier: LigneBrute[] = [{
      Produit: "PRODUIT REGULIER", CIP: "5001", Stock: 15,
      "Ventes avril": 30, "Ventes mai": 30, "Ventes juin": 30,
    }];
    const mardi = analyserStockRotation(cadencier, MAPPING, {}, new Date(2026, 4, 12));
    const vendredi = analyserStockRotation(cadencier, MAPPING, {}, new Date(2026, 4, 15));
    expect(mardi.tableau[0].stockMin).toBe(14);
    expect(vendredi.tableau[0].stockMin).toBe(16);
    // Stock 15 : suffisant le mardi, sous le min le vendredi.
    expect(mardi.tableau[0].alerte).toBe("🟢 OK");
    expect(vendredi.tableau[0].alerte).toBe("🟡 Sous le min");
    expect(vendredi.resume.joursWeekend).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Règle des 10 unités : urgence CONFIRMÉE (double condition)
// ---------------------------------------------------------------------------

describe("règle des 10 unités", () => {
  it("sous le seuil ET sous le min → cible = stock max", () => {
    const r = determinerCibleReassort(8, 15, 40, 10);
    expect(r.cible).toBe(40);
    expect(r.qte).toBe(32);
    expect(r.motif).toContain("immédiate");
  });

  it("sous le seuil mais déjà au-dessus du min → aucune commande", () => {
    // Cœur du correctif : un produit à faible rotation a souvent un stock min
    // inférieur au seuil absolu. Le seuil SEUL ne doit pas déclencher.
    const r = determinerCibleReassort(8, 3, 12, 10);
    expect(r.cible).toBe(8);
    expect(r.qte).toBe(0);
    expect(r.motif.toLowerCase()).toContain("suffisant");
  });

  it("au seuil exact : pas dans la zone critique", () => {
    const r = determinerCibleReassort(10, 15, 40, 10);
    expect(r.cible).toBe(15);
    expect(r.motif).toContain("progressif");
  });

  it("entre le seuil et le min → réassort progressif", () => {
    const r = determinerCibleReassort(12, 20, 50, 10);
    expect(r.cible).toBe(20);
    expect(r.qte).toBe(8);
  });

  it("stock suffisant → aucune commande", () => {
    expect(determinerCibleReassort(25, 20, 50, 10).qte).toBe(0);
  });

  it("jamais de quantité négative", () => {
    expect(determinerCibleReassort(8, 3, 6, 10).qte).toBe(0);
  });

  it("stock égal à son propre min : pas de fausse urgence", () => {
    // Cas réel : KETOCONAZOLE CREME — stock 9, min 9, sous le seuil de 10.
    const r = determinerCibleReassort(9, 9, 18, 10);
    expect(r.qte).toBe(0);
  });

  it("urgence confirmée même pour une petite rotation", () => {
    const r = determinerCibleReassort(5, 7, 15, 10);
    expect(r.cible).toBe(15);
    expect(r.qte).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// Suppression du stock min quand le stock max < 10
// ---------------------------------------------------------------------------

describe("stock min supprimé si stock max < 10", () => {
  it("petit produit : min supprimé, aucune commande automatique", () => {
    const cadencier: LigneBrute[] = [{
      Produit: "PETIT MAX", CIP: "9300", Stock: 1,
      "Ventes avril": 5, "Ventes mai": 5, "Ventes juin": 5,
    }];
    const ligne = analyserStockRotation(cadencier, MAPPING).tableau[0];
    expect(ligne.stockMax).toBeLessThan(10);
    expect(ligne.stockMin).toBe(0);
    expect(ligne.motif).toContain("stock min supprimé");
    expect(ligne.qteACommander).toBe(0);
  });

  it("gros vendeur : min conservé", () => {
    const cadencier: LigneBrute[] = [{
      Produit: "GROS VENDEUR", CIP: "9302", Stock: 0,
      "Ventes avril": 40, "Ventes mai": 40, "Ventes juin": 40,
    }];
    const ligne = analyserStockRotation(cadencier, MAPPING).tableau[0];
    expect(ligne.stockMax).toBeGreaterThanOrEqual(10);
    expect(ligne.stockMin).toBeGreaterThan(0);
    expect(ligne.motif).not.toContain("stock min supprimé");
  });
});

// ---------------------------------------------------------------------------
// Garde-fou des modes réactifs
// ---------------------------------------------------------------------------

describe("garde-fou du mode mensuel", () => {
  const MAPPING_12: MappingCadencier = {
    libelle: "Produit", cip: "CIP", stock: "Stock",
    ventes: Array.from({ length: 12 }, (_, i) => `M${i}`),
  };
  const cadencier = (): LigneBrute[] => {
    const l: LigneBrute = { Produit: "EN RUPTURE CE MOIS", CIP: "9100", Stock: 3 };
    for (let i = 0; i < 11; i += 1) l[`M${i}`] = 10;
    l.M11 = 0; // dernier mois : rupture
    return [l];
  };

  it("un produit en rupture le dernier mois ne disparaît pas", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_12, { periodeRotation: "1mois" });
    expect(r.tableau).toHaveLength(1);
    const ligne = r.tableau[0];
    expect(ligne.consommationMois).toBeGreaterThan(5); // repli sur l'annuelle
    expect(ligne.motif).toContain("repli sur la moyenne annuelle");
    expect(ligne.qteACommander).toBeGreaterThan(0);
  });

  it("le mode annuel ne mentionne pas de repli", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_12);
    expect(r.tableau[0].motif).not.toContain("repli");
  });
});

// ---------------------------------------------------------------------------
// Rotation faible écartée du réassort
// ---------------------------------------------------------------------------

describe("rotation faible écartée", () => {
  const cadencier = (): LigneBrute[] => [
    { Produit: "ROTATION LENTE", CIP: "8001", Stock: 0,
      "Ventes avril": 1, "Ventes mai": 1, "Ventes juin": 1 },
    { Produit: "ROTATION NORMALE", CIP: "8002", Stock: 0,
      "Ventes avril": 20, "Ventes mai": 20, "Ventes juin": 20 },
  ];

  it("le produit lent est écarté par défaut (≤ 1/mois)", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    const lent = trouver(r.tableau, "ROTATION LENTE");
    expect(lent.alerte).toBe("⚪ Rotation faible");
    expect(lent.qteACommander).toBe(0);
    expect(lent.motif).toContain("écarté");
  });

  it("le produit normal reste commandé", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    const normal = trouver(r.tableau, "ROTATION NORMALE");
    expect(normal.alerte).toBe("🔴 Action requise");
    expect(normal.qteACommander).toBeGreaterThan(0);
  });

  it("seuil réglable", () => {
    const r = analyserStockRotation(cadencier(), MAPPING, {
      rotationMinCommandeMensuelle: 25,
    });
    expect(r.resume.rotationFaible).toBe(2);
    expect(r.resume.qteTotaleACommander).toBe(0);
  });

  it("désactivable avec 0", () => {
    const r = analyserStockRotation(cadencier(), MAPPING, {
      rotationMinCommandeMensuelle: 0,
    });
    expect(r.tableau.some((l) => l.alerte === "⚪ Rotation faible")).toBe(false);
    expect(trouver(r.tableau, "ROTATION NORMALE").qteACommander).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Commandes déjà en cours
// ---------------------------------------------------------------------------

describe("commandes en cours déduites", () => {
  const MAPPING_EC: MappingCadencier = { ...MAPPING, commandeEnCours: "En cours" };
  const cadencier = (): LigneBrute[] => [
    { Produit: "AVEC COMMANDE EN COURS", CIP: "7001", Stock: 2, "En cours": 30,
      "Ventes avril": 30, "Ventes mai": 30, "Ventes juin": 30 },
    { Produit: "SANS COMMANDE EN COURS", CIP: "7002", Stock: 2, "En cours": 0,
      "Ventes avril": 30, "Ventes mai": 30, "Ventes juin": 30 },
  ];

  it("ce qui est déjà en route n'est pas recommandé", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_EC);
    const avec = trouver(r.tableau, "AVEC COMMANDE EN COURS");
    const sans = trouver(r.tableau, "SANS COMMANDE EN COURS");
    expect(avec.qteACommander).toBe(0);
    expect(sans.qteACommander).toBeGreaterThan(0);
    expect(avec.stockActuel).toBe(2); // le stock AFFICHÉ reste le physique
    expect(avec.alerte).toBe("🟢 OK");
    expect(sans.alerte).toBe("🔴 Action requise");
  });

  it("la déduction est mentionnée dans le motif", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_EC);
    expect(trouver(r.tableau, "AVEC COMMANDE EN COURS").motif).toContain(
      "déjà en commande",
    );
  });

  it("colonne non mappée : comportement inchangé", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    expect(trouver(r.tableau, "AVEC COMMANDE EN COURS").qteACommander).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Fusion des doublons de code CIP
// ---------------------------------------------------------------------------

describe("fusion des doublons", () => {
  const MAPPING_4: MappingCadencier = {
    libelle: "Produit", cip: "CIP", stock: "Stock",
    ventes: ["Ventes dec", "Ventes jan", "Ventes fev", "Ventes mar"],
  };
  const cadencier = (): LigneBrute[] => [
    // Ancien code : ventes jusqu'en janvier puis plus rien.
    { Produit: "BISOPROLOL 2,5 B/ 30", CIP: "3400935295637", Stock: 0,
      "Ventes dec": 90, "Ventes jan": 87, "Ventes fev": 0, "Ventes mar": 0 },
    // Nouveau code : prend le relais dès janvier.
    { Produit: "BISOPROLOL 2,5 B/ 30", CIP: "3400930227336", Stock: 79,
      "Ventes dec": 0, "Ventes jan": 10, "Ventes fev": 109, "Ventes mar": 119 },
    { Produit: "AUTRE PRODUIT", CIP: "4009", Stock: 50,
      "Ventes dec": 5, "Ventes jan": 5, "Ventes fev": 5, "Ventes mar": 5 },
  ];

  it("une seule ligne par produit", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_4);
    expect(r.tableau.filter((l) => l.nomProduit === "BISOPROLOL 2,5 B/ 30")).toHaveLength(1);
    expect(r.resume.doublonsFusionnes).toBe(1);
  });

  it("pas de commande fantôme sur l'ancien code", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_4);
    const ligne = trouver(r.tableau, "BISOPROLOL 2,5 B/ 30");
    expect(ligne.stockActuel).toBe(79);
    expect(ligne.qteACommander).toBe(0);
    expect(ligne.alerte).toBe("🟢 OK");
  });

  it("le CIP du code actif est conservé", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_4);
    expect(trouver(r.tableau, "BISOPROLOL 2,5 B/ 30").codeCip).toBe("3400930227336");
  });

  it("ventes additionnées mois par mois", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_4);
    // (90 + 97 + 109 + 119) / 4 = 103,75 → série redevenue continue.
    expect(trouver(r.tableau, "BISOPROLOL 2,5 B/ 30").consommationMois).toBeCloseTo(103.8, 1);
  });

  it("les produits sans doublon sont intacts", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_4);
    expect(trouver(r.tableau, "AUTRE PRODUIT").stockActuel).toBe(50);
  });

  it("les libellés vides ne sont jamais fusionnés", () => {
    const cad: LigneBrute[] = [
      { Produit: "", CIP: "111111", Stock: 5, "Ventes avril": 10, "Ventes mai": 10, "Ventes juin": 10 },
      { Produit: "", CIP: "222222", Stock: 6, "Ventes avril": 20, "Ventes mai": 20, "Ventes juin": 20 },
      { Produit: "NOMMÉ", CIP: "333333", Stock: 7, "Ventes avril": 30, "Ventes mai": 30, "Ventes juin": 30 },
    ];
    const r = analyserStockRotation(cad, MAPPING);
    expect(r.resume.totalProduits).toBe(3);
    expect(r.resume.doublonsFusionnes).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Colonne conseillée (variabilité)
// ---------------------------------------------------------------------------

describe("stock min conseillé", () => {
  const MAPPING_6: MappingCadencier = {
    libelle: "Produit", cip: "CIP", stock: "Stock",
    ventes: ["V1", "V2", "V3", "V4", "V5", "V6"],
  };
  // Même moyenne (~40/mois) mais l'un régulier, l'autre en dents de scie.
  // Valeurs non nulles pour l'erratique : des 0 intérieurs seraient lissés
  // par la correction des ruptures passées, effaçant la variabilité.
  const cadencier = (): LigneBrute[] => [
    { Produit: "REGULIER", CIP: "9200", Stock: 100,
      V1: 40, V2: 40, V3: 40, V4: 40, V5: 40, V6: 40 },
    { Produit: "ERRATIQUE", CIP: "9201", Stock: 100,
      V1: 8, V2: 72, V3: 10, V4: 70, V5: 8, V6: 72 },
  ];

  it("l'erratique se voit conseiller plus que le régulier", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_6);
    const reg = trouver(r.tableau, "REGULIER");
    const err = trouver(r.tableau, "ERRATIQUE");
    expect(reg.stockMinConseille).toBe(reg.stockMin); // stable → pas de marge
    expect(err.stockMinConseille).toBeGreaterThan(err.stockMin);
  });

  it("la colonne conseillée ne change pas la quantité commandée", () => {
    const r = analyserStockRotation(cadencier(), MAPPING_6);
    // Stock 100 largement au-dessus du min → aucune commande malgré la marge.
    expect(trouver(r.tableau, "ERRATIQUE").qteACommander).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Analyse complète : cohérence d'ensemble
// ---------------------------------------------------------------------------

describe("analyse complète", () => {
  const cadencier = (): LigneBrute[] => [
    { Produit: "CRITIQUE B/12", CIP: "4001", Stock: 8,
      "Ventes avril": 30, "Ventes mai": 32, "Ventes juin": 31 },
    { Produit: "SOUS MIN", CIP: "4002", Stock: 11,
      "Ventes avril": 30, "Ventes mai": 30, "Ventes juin": 30 },
    { Produit: "STOCK OK", CIP: "4003", Stock: 200,
      "Ventes avril": 30, "Ventes mai": 32, "Ventes juin": 31 },
    { Produit: "DORMANT", CIP: "4004", Stock: 500,
      "Ventes avril": 2, "Ventes mai": 2, "Ventes juin": 2 },
    { Produit: "SANS HISTORIQUE", CIP: "4005", Stock: 0,
      "Ventes avril": 0, "Ventes mai": 0, "Ventes juin": 0 },
  ];

  it("le produit critique est signalé", () => {
    const ligne = trouver(analyserStockRotation(cadencier(), MAPPING).tableau, "CRITIQUE B/12");
    expect(ligne.alerte).toBe("🔴 Action requise");
    expect(ligne.qteACommander).toBeGreaterThan(0);
    expect(ligne.stockMax).toBeGreaterThan(ligne.stockMin);
  });

  it("le palier intermédiaire est respecté", () => {
    const ligne = trouver(analyserStockRotation(cadencier(), MAPPING).tableau, "SOUS MIN");
    expect(ligne.alerte).toBe("🟡 Sous le min");
    expect(ligne.qteACommander).toBeGreaterThan(0);
  });

  it("les actions requises sont en tête du tableau", () => {
    expect(analyserStockRotation(cadencier(), MAPPING).tableau[0].alerte).toBe("🔴 Action requise");
  });

  it("le stock dormant est détecté", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    expect(r.dormants.some((d) => d.nomProduit === "DORMANT")).toBe(true);
    expect(r.resume.dormants).toBeGreaterThanOrEqual(1);
  });

  it("un produit sans vente ni stock n'est pas piloté", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    expect(r.tableau.some((l) => l.nomProduit === "SANS HISTORIQUE")).toBe(false);
    expect(r.resume.totalProduits).toBe(4);
  });

  it("la consommation par défaut pilote les produits sans historique", () => {
    const r = analyserStockRotation(cadencier(), MAPPING, {
      consommationDefautMensuelle: 30,
    });
    const ligne = trouver(r.tableau, "SANS HISTORIQUE");
    expect(ligne).toBeTruthy();
    expect(ligne.motif).toContain("défaut");
  });

  it("le classement ABC est intégré", () => {
    const r = analyserStockRotation(cadencier(), MAPPING);
    expect(r.resume.nbA + r.resume.nbB + r.resume.nbC).toBe(r.resume.totalProduits);
  });

  it("les paramètres de couverture changent le résultat", () => {
    const larges = analyserStockRotation(cadencier(), MAPPING, {
      couvertureMinJours: 3, couvertureMaxJours: 7,
    });
    const serres = analyserStockRotation(cadencier(), MAPPING, {
      couvertureMinJours: 30, couvertureMaxJours: 90,
    });
    expect(trouver(serres.tableau, "STOCK OK").stockMax).toBeGreaterThan(
      trouver(larges.tableau, "STOCK OK").stockMax,
    );
  });

  it("stocks et quantités sont des entiers", () => {
    for (const l of analyserStockRotation(cadencier(), MAPPING).tableau) {
      for (const v of [l.stockActuel, l.stockMin, l.stockMax, l.qteACommander]) {
        expect(Number.isInteger(v)).toBe(true);
      }
      expect(l.stockMin).toBeLessThanOrEqual(l.stockMax);
      expect(l.qteACommander).toBeGreaterThanOrEqual(0);
    }
  });

  it("un CIP manquant s'affiche vide, pas « nan »", () => {
    const cad = cadencier();
    cad[0].CIP = null;
    const ligne = trouver(analyserStockRotation(cad, MAPPING).tableau, "CRITIQUE B/12");
    expect(ligne.codeCip).toBe("");
  });

  it("fonctionne avec le SEUL cadencier (isolation)", () => {
    expect(analyserStockRotation(cadencier(), MAPPING).tableau.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Cadencier n+1 : lignes modifiées (≥ 10 %)
// ---------------------------------------------------------------------------

describe("comparaison à l'analyse précédente", () => {
  const etat = (lignes: [string, string, number, number][]) =>
    lignes.map(([codeCip, nomProduit, stockMin, stockMax]) => ({
      codeCip, nomProduit, stockMin, stockMax,
    }));
  const tableau = (lignes: [string, string, number, number][]) =>
    etat(lignes).map((l) => ({ ...l }) as never as import("./stock-rotation").LigneStock);

  it("première analyse : tout est considéré modifié", () => {
    const r = comparerAEtatPrecedent(tableau([["111", "A", 10, 20], ["222", "B", 5, 12]]), null);
    expect(r.nbModifiees).toBe(2);
    expect(r.nbNouvelles).toBe(2);
  });

  it("ligne inchangée : exclue", () => {
    const r = comparerAEtatPrecedent(
      tableau([["111", "A", 10, 20]]),
      etat([["111", "A", 10, 20]]),
    );
    expect(r.tableau[0].modifie).toBe(false);
    expect(r.nbModifiees).toBe(0);
  });

  it("variation sous 10 % : exclue", () => {
    const r = comparerAEtatPrecedent(
      tableau([["111", "A", 105, 209]]), // +5 % et +4,5 %
      etat([["111", "A", 100, 200]]),
    );
    expect(r.tableau[0].modifie).toBe(false);
  });

  it("variation ≥ 10 % : incluse", () => {
    const r = comparerAEtatPrecedent(
      tableau([["111", "A", 100, 230]]), // max +15 %
      etat([["111", "A", 100, 200]]),
    );
    expect(r.tableau[0].modifie).toBe(true);
    expect(r.nbModifiees).toBe(1);
  });

  it("nouveau produit : inclus", () => {
    const r = comparerAEtatPrecedent(
      tableau([["111", "A", 10, 20], ["333", "C", 4, 9]]),
      etat([["111", "A", 10, 20]]),
    );
    expect(r.nbNouvelles).toBe(1);
    expect(r.tableau.find((l) => l.codeCip === "333")!.modifie).toBe(true);
  });

  it("deux produits partageant un CIP ne sont pas confondus", () => {
    // Cas réel du cadencier : même CIP, libellés différents.
    const r = comparerAEtatPrecedent(
      tableau([
        ["3401078641756", "SERINGUE A INSULINE 1ML", 0, 7],
        ["3401078641756", "SERINGUE INSULINE 1 ML", 0, 1],
      ]),
      etat([
        ["3401078641756", "SERINGUE A INSULINE 1ML", 0, 7],
        ["3401078641756", "SERINGUE INSULINE 1 ML", 0, 1],
      ]),
    );
    expect(r.nbModifiees).toBe(0);
  });

  it("l'état à enregistrer contient les colonnes de référence", () => {
    const r = analyserStockRotation(
      [{ Produit: "X", CIP: "1", Stock: 5, "Ventes avril": 40, "Ventes mai": 40, "Ventes juin": 40 }],
      MAPPING,
    );
    const [ligne] = etatStockAEnregistrer(r.tableau);
    expect(Object.keys(ligne).sort()).toEqual(
      ["codeCip", "nomProduit", "stockMax", "stockMin"],
    );
  });
});
