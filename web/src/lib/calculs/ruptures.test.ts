/**
 * Tests du Module 2 — portage de `tests/test_moteur.py`.
 *
 * Couvre la règle d'apparition stricte, les paliers d'urgence, la quantité à
 * commander, l'appariement CIP13/CIP7, le score de priorité, la probabilité
 * de rupture et le suivi quotidien. Les cas de référence (Titanoréine,
 * Ozempic, Aranesp) sont ceux validés avec le pharmacien.
 */
import { describe, expect, it } from "vitest";
import {
  ANTICIPER,
  MODERE,
  URGENT,
  apparier,
  classerUrgence,
  comparerAAnalysePrecedente,
  compterOccurrencesHistorique,
  compterReports,
  doitApparaitre,
  indexer,
  probabiliteRupture,
  quantiteACommander,
  rotationPossiblementSousEstimee,
  scorePriorite,
  tauxDeService,
  tokenSortRatio,
  type LigneHistorique,
} from "./ruptures";
import { analyserRuptures, type MappingRuptures } from "./ruptures-analyse";

// ---------------------------------------------------------------------------
// Règle d'apparition (étape 3) — STRICTE, sans marge
// ---------------------------------------------------------------------------

describe("doitApparaitre", () => {
  it("Titanoréine : 18 j de stock pour 16 j d'attente → écartée", () => {
    expect(doitApparaitre(18, 16)).toBe(false);
  });

  it("stock insuffisant avant la réappro → retenu", () => {
    expect(doitApparaitre(10, 16)).toBe(true);
  });

  it("égalité stricte : 16 j pour 16 j → écarté (pas de marge)", () => {
    expect(doitApparaitre(16, 16)).toBe(false);
  });

  it("sans date : seuil de 30 jours de couverture", () => {
    expect(doitApparaitre(29.9, null)).toBe(true);
    expect(doitApparaitre(30, null)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Urgence (étape 6)
// ---------------------------------------------------------------------------

describe("classerUrgence", () => {
  it("stock nul → urgent", () => {
    expect(classerUrgence(0, 0)).toBe(URGENT);
  });

  it("moins de 3 jours → urgent", () => {
    expect(classerUrgence(5, 2.5)).toBe(URGENT);
  });

  it("entre 3 et 15 jours → modéré", () => {
    expect(classerUrgence(20, 9)).toBe(MODERE);
  });

  it("au-delà de 15 jours → à anticiper", () => {
    expect(classerUrgence(50, 25)).toBe(ANTICIPER);
  });
});

// ---------------------------------------------------------------------------
// Quantité à commander (étape 5)
// ---------------------------------------------------------------------------

describe("quantiteACommander", () => {
  it("Ozempic : 16,5/mois, 30 j de cible, 5 en stock → 12", () => {
    expect(quantiteACommander(16.5, 30, 5)).toBe(12);
  });

  it("toujours au moins 1 boîte", () => {
    expect(quantiteACommander(4, 2, 100)).toBe(1);
  });

  it("arrondi au conditionnement", () => {
    // Besoin de 12 → conditionnement par 10 → 20.
    expect(quantiteACommander(16.5, 30, 5, 10)).toBe(20);
  });

  it("conditionnement de 1 sans effet", () => {
    expect(quantiteACommander(16.5, 30, 5, 1)).toBe(12);
  });
});

// ---------------------------------------------------------------------------
// Score de priorité et probabilité de rupture
// ---------------------------------------------------------------------------

describe("scorePriorite", () => {
  it("risque maximal sur un produit A avec réappro repoussée → 100", () => {
    expect(scorePriorite(1, "A", 2)).toBe(100);
  });

  it("aucun risque sur un produit C fiable → faible", () => {
    expect(scorePriorite(0, "C", 0)).toBe(6);
  });

  it("une classe A pèse plus qu'une classe C à risque égal", () => {
    expect(scorePriorite(0.5, "A")).toBeGreaterThan(scorePriorite(0.5, "C"));
  });

  it("l'absence de date compte pour moitié dans la fiabilité", () => {
    expect(scorePriorite(0, "C", 0, true)).toBeGreaterThan(
      scorePriorite(0, "C", 0, false),
    );
  });
});

describe("probabiliteRupture", () => {
  it("rotation nulle → risque nul", () => {
    expect(probabiliteRupture(0, 0, [])).toBe(0);
  });

  it("demande régulière qui épuise le stock → risque certain", () => {
    // σ = 0 (ventes identiques) → repli déterministe.
    expect(probabiliteRupture(1, 30, [30, 30, 30], 7)).toBe(1);
  });

  it("stock confortable et demande régulière → risque nul", () => {
    expect(probabiliteRupture(100, 30, [30, 30, 30], 7)).toBe(0);
  });

  it("demande variable → probabilité intermédiaire", () => {
    const p = probabiliteRupture(8, 30, [10, 50, 30], 7);
    expect(p).toBeGreaterThan(0);
    expect(p).toBeLessThan(1);
  });
});

// ---------------------------------------------------------------------------
// Fiabilité de la date de réappro
// ---------------------------------------------------------------------------

describe("compterReports", () => {
  const d = (iso: string) => new Date(`${iso}T00:00:00`);

  it("aucune annonce → aucun report", () => {
    expect(compterReports([], null)).toBe(0);
  });

  it("date repoussée deux fois", () => {
    expect(
      compterReports([d("2026-05-01"), d("2026-05-10")], d("2026-05-20")),
    ).toBe(2);
  });

  it("date avancée ou stable → aucun report", () => {
    expect(compterReports([d("2026-05-20")], d("2026-05-10"))).toBe(0);
    expect(compterReports([d("2026-05-10")], d("2026-05-10"))).toBe(0);
  });

  it("les jours sans date annoncée sont ignorés", () => {
    expect(compterReports([d("2026-05-01"), null], d("2026-05-05"))).toBe(1);
  });
});

describe("rotationPossiblementSousEstimee", () => {
  it("un mois à 0 parmi des mois vendeurs → signalé", () => {
    expect(rotationPossiblementSousEstimee([10, 0, 12])).toBe(true);
  });

  it("aucune vente du tout → non signalé", () => {
    expect(rotationPossiblementSousEstimee([0, 0, 0])).toBe(false);
  });

  it("toutes les ventes positives → non signalé", () => {
    expect(rotationPossiblementSousEstimee([10, 12, 11])).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Appariement des produits
// ---------------------------------------------------------------------------

describe("apparier", () => {
  const liste = [
    { Libelle: "TITANOREINE SUPPO B/12", CIP: "3400932300778" },
    { Libelle: "OZEMPIC 1MG STYLO", CIP: "3400930012345" },
  ];
  const index = indexer(liste, "Libelle", "CIP");

  it("appariement par CIP13", () => {
    const c = apparier("Autre libellé", "3400932300778", index);
    expect(c.index).toBe(0);
    expect(c.methode).toBe("cip");
  });

  it("un CIP7 retrouve son CIP13 (et réciproquement)", () => {
    // 3400932300778 → CIP7 embarqué : 3230077
    const c = apparier("Autre libellé", "3230077", index);
    expect(c.index).toBe(0);
    expect(c.methode).toBe("cip");
  });

  it("appariement exact par libellé", () => {
    const c = apparier("titanoreine suppo b/12", "", index);
    expect(c.index).toBe(0);
    expect(c.methode).toBe("exact");
  });

  it("produit inconnu → aucune correspondance", () => {
    const c = apparier("PRODUIT INEXISTANT XYZ", "", index);
    expect(c.index).toBeNull();
  });

  it("l'ordre des mots n'empêche pas le rapprochement approché", () => {
    expect(tokenSortRatio("DOLIPRANE 1000 CPR", "CPR 1000 DOLIPRANE")).toBe(100);
  });
});

// ---------------------------------------------------------------------------
// Suivi quotidien
// ---------------------------------------------------------------------------

describe("suivi quotidien", () => {
  const historique: LigneHistorique[] = [
    { dateAnalyse: "2026-05-10", produit: "A", type: "commande" },
    { dateAnalyse: "2026-05-10", produit: "B", type: "commande" },
    { dateAnalyse: "2026-05-12", produit: "A", type: "commande" },
    { dateAnalyse: "2026-05-12", produit: "C", type: "surveillance" },
  ];

  it("compare à la dernière analyse antérieure", () => {
    const r = comparerAAnalysePrecedente(["A", "D"], historique, new Date(2026, 4, 13));
    expect(r.datePrecedente).toBe("2026-05-12");
    expect(r.nouveaux).toEqual(["D"]);
    expect(r.resolus).toEqual([]);
  });

  it("les produits disparus sont « résolus »", () => {
    const r = comparerAAnalysePrecedente(["B"], historique, new Date(2026, 4, 11));
    expect(r.datePrecedente).toBe("2026-05-10");
    expect(r.resolus).toEqual(["A"]);
  });

  it("première analyse : tout est nouveau", () => {
    const r = comparerAAnalysePrecedente(["A"], [], new Date(2026, 4, 13));
    expect(r.datePrecedente).toBeNull();
    expect(r.nouveaux).toEqual(["A"]);
  });

  it("les lignes de surveillance ne comptent pas comme signalements", () => {
    expect(compterOccurrencesHistorique("C", historique, new Date(2026, 4, 13))).toBe(0);
    expect(compterOccurrencesHistorique("A", historique, new Date(2026, 4, 13))).toBe(2);
  });

  it("taux de service : null tant que l'historique est vide", () => {
    expect(tauxDeService(["A"], [], new Date(2026, 4, 13)).taux).toBeNull();
  });

  it("taux de service calculé sur la fenêtre glissante", () => {
    const r = tauxDeService(["A", "B"], historique, new Date(2026, 4, 13), 30);
    // 2 jours × 2 produits = 4 couples ; 3 signalements (A×2, B×1) → 25 %.
    expect(r.joursAnalyses).toBe(2);
    expect(r.taux).toBeCloseTo(0.25, 5);
  });
});

// ---------------------------------------------------------------------------
// Analyse complète : cas de référence validés avec le pharmacien
// ---------------------------------------------------------------------------

describe("analyse complète des ruptures", () => {
  const DATE = new Date(2026, 4, 13); // 13/05/2026
  const dans = (jours: number) => {
    const d = new Date(DATE);
    d.setDate(d.getDate() + jours);
    return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
  };

  const cadencier = [
    // Titanoréine : 6/mois, stock 3,6 → 18 j de couverture, réappro à 16 j.
    { Produit: "TITANOREINE SUPPO B/12", CIP: "1001", Stock: 3.6,
      V1: 6, V2: 6, V3: 6 },
    // Ozempic : 16,5/mois, stock 5 → 9 j, sans date de réappro.
    { Produit: "OZEMPIC 1MG STYLO", CIP: "1002", Stock: 5,
      V1: 16, V2: 17, V3: 16.5 },
    // Aranesp : stock 0 → urgent.
    { Produit: "ARANESP 150 SOL INJ", CIP: "1003", Stock: 0,
      V1: 4, V2: 4, V3: 4 },
    // Rupture chez les deux fournisseurs.
    { Produit: "DALACINE 300 GEL", CIP: "1004", Stock: 2,
      V1: 13, V2: 13, V3: 13 },
    // Non vendu : absent des ventes.
    { Produit: "PRODUIT DORMANT", CIP: "1005", Stock: 4, V1: 0, V2: 0, V3: 0 },
  ];
  const gpnc = [
    { Libelle: "TITANOREINE SUPPO B/12", CIP: "1001", Reappro: dans(16) },
    { Libelle: "OZEMPIC 1MG STYLO", CIP: "1002", Reappro: "" },
    { Libelle: "ARANESP 150 SOL INJ", CIP: "1003", Reappro: dans(2) },
    { Libelle: "DALACINE 300 GEL", CIP: "1004", Reappro: "" },
    { Libelle: "PRODUIT DORMANT", CIP: "1005", Reappro: "" },
    { Libelle: "PRODUIT NON VENDU", CIP: "9999", Reappro: "" },
  ];
  const unipharma = [{ Designation: "DALACINE 300 GEL", CIP: "1004" }];

  const mapping: MappingRuptures = {
    cadencier: { libelle: "Produit", cip: "CIP", stock: "Stock", ventes: ["V1", "V2", "V3"] },
    gpnc: { libelle: "Libelle", cip: "CIP", dateReappro: "Reappro" },
    unipharma: { libelle: "Designation", cip: "CIP" },
  };

  const resultat = () => analyserRuptures(cadencier, gpnc, unipharma, mapping, DATE);

  it("Titanoréine est écartée : son stock couvre la réappro", () => {
    const r = resultat();
    expect(r.onglet1.some((l) => l.produit.startsWith("TITANOREINE"))).toBe(false);
    const detail = r.onglet3.find((l) => l.produit.startsWith("TITANOREINE"))!;
    expect(detail.decision).toBe("Écarté");
  });

  it("Ozempic est à commander (12 boîtes, sans date de réappro)", () => {
    const ligne = resultat().onglet1.find((l) => l.produit.startsWith("OZEMPIC"))!;
    expect(ligne.qteACommander).toBe(12);
    expect(ligne.commentaire).toContain("30 j de couverture");
  });

  it("Aranesp est urgent (stock nul) et à commander", () => {
    const ligne = resultat().onglet1.find((l) => l.produit.startsWith("ARANESP"))!;
    expect(ligne.urgence).toBe(URGENT);
    expect(ligne.qteACommander).toBeGreaterThanOrEqual(1);
  });

  it("Dalacine est sans solution : rupture chez les deux", () => {
    const r = resultat();
    expect(r.onglet2.some((l) => l.produit.startsWith("DALACINE"))).toBe(true);
    expect(r.onglet1.some((l) => l.produit.startsWith("DALACINE"))).toBe(false);
  });

  it("un produit non vendu est écarté du périmètre", () => {
    const detail = resultat().onglet3.find((l) => l.produit === "PRODUIT NON VENDU")!;
    expect(detail.vendu).toBe("N");
    expect(detail.motif).toContain("Absent du cadencier");
  });

  it("un produit à rotation nulle est écarté", () => {
    const detail = resultat().onglet3.find((l) => l.produit === "PRODUIT DORMANT")!;
    expect(detail.decision).toBe("Écarté");
    expect(detail.motif).toContain("Rotation nulle");
  });

  it("l'analyse complète trace chaque produit de la liste GPNC", () => {
    expect(resultat().onglet3).toHaveLength(gpnc.length);
  });

  it("la liste du matin est triée par score de priorité", () => {
    const priorites = resultat().onglet1.map((l) => l.priorite);
    expect([...priorites].sort((a, b) => b - a)).toEqual(priorites);
  });

  it("le résumé est cohérent avec les onglets", () => {
    const r = resultat();
    expect(r.resume.aCommander).toBe(r.onglet1.length);
    expect(r.resume.sansSolution).toBe(r.onglet2.length);
    expect(r.resume.rupturesGpnc).toBe(gpnc.length);
  });

  it("le délai de livraison augmente la quantité commandée", () => {
    const sans = analyserRuptures(cadencier, gpnc, unipharma, mapping, DATE);
    const avec = analyserRuptures(cadencier, gpnc, unipharma, mapping, DATE, {
      delaiLivraisonJours: 5,
    });
    const q = (r: typeof sans) =>
      r.onglet1.find((l) => l.produit.startsWith("OZEMPIC"))!.qteACommander;
    expect(q(avec)).toBeGreaterThan(q(sans));
  });

  it("la politique ABC change la couverture cible sans date", () => {
    const r = analyserRuptures(cadencier, gpnc, unipharma, mapping, DATE, {
      politiqueAbc: true,
    });
    const ligne = r.onglet1.find((l) => l.produit.startsWith("OZEMPIC"))!;
    // Ozempic est classe A → cible 21 j au lieu de 30.
    expect(ligne.commentaire).toContain("21 j");
  });
});
