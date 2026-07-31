/**
 * Tests du lecteur de cadencier — portage de `TestCadencierWinPharmaCsv`.
 */
import { describe, expect, it } from "vitest";
import {
  chargerFichierTexte,
  parserCadencierWinPharma,
  parserCsvGenerique,
} from "./cadencier";

const CADENCIER_WINPHARMA = [
  '"PHARMACIE DE LA FOA M. Lauret Claude Alexandre"',
  '"92 Route Territoriale 1 BP 214"',
  '"Date :  10/07/2026 13:05"',
  '"du 01/07/2025 au 30/06/2026"',
  "",
  'CIP;Code13Réf;Nom;"Formes & presentations";Stock;' +
    '"Jun (A)";"Mai (A)";"Jun (V)";"Mai (V)";"Total (A)";"Total (V)"',
  '3352892;3400933528928;"ABUFENE  400   B/ 30";"60  COMPRIMÉ";1;0;2;5;3;2;8',
  '3525720004499;3525722032742;"3 CHENES CARBOLINE B/30";;17;12;0;3;1;12;4',
  ';;"BO COEUR WHITE BRONZE";;2;0;0;1;0;0;1',
  ';;"Qte : 3621";"Manque : -8";20;12;2;9;4;14;13',
].join("\r\n");

describe("cadencier WinPharma", () => {
  const charge = () => parserCadencierWinPharma(CADENCIER_WINPHARMA)!;

  it("le bandeau et la ligne de totaux sont éliminés", () => {
    const r = charge();
    expect(r.lignes).toHaveLength(3); // 2 produits codés + 1 sans code
    expect(r.lignes.some((l) => String(l.Produit).includes("Qte"))).toBe(false);
  });

  it("format normalisé : Produit / CIP / Stock / Ventes", () => {
    expect(charge().colonnes).toEqual([
      "Produit", "CIP", "Stock", "Ventes Mai", "Ventes Jun",
    ]);
  });

  it("ventes remises en ordre chronologique, achats ignorés", () => {
    const abufene = charge().lignes.find((l) =>
      String(l.Produit).startsWith("ABUFENE"),
    )!;
    // Ligne source : Jun (V) = 5, Mai (V) = 3 — et surtout PAS les achats.
    expect(abufene["Ventes Mai"]).toBe("3");
    expect(abufene["Ventes Jun"]).toBe("5");
  });

  it("le Code13Réf est préféré au CIP court", () => {
    const abufene = charge().lignes.find((l) =>
      String(l.Produit).startsWith("ABUFENE"),
    )!;
    expect(abufene.CIP).toBe("3400933528928");
  });

  it("un produit sans code est conservé", () => {
    const sansCode = charge().lignes.filter((l) =>
      String(l.Produit).startsWith("BO COEUR"),
    );
    expect(sansCode).toHaveLength(1);
    expect(sansCode[0].CIP).toBe("");
  });

  it("un CSV ordinaire n'est pas intercepté", () => {
    expect(parserCadencierWinPharma("CIP;Stock\n3352892;4\n")).toBeNull();
    const r = parserCsvGenerique("CIP;Stock\n3352892;4\n");
    expect(r.colonnes).toEqual(["CIP", "Stock"]);
    expect(r.lignes).toHaveLength(1);
  });
});

describe("chargerFichierTexte", () => {
  const encoder = (s: string) => new TextEncoder().encode(s).buffer as ArrayBuffer;

  it("reconnaît le cadencier WinPharma", () => {
    const r = chargerFichierTexte(encoder(CADENCIER_WINPHARMA));
    expect(r.formatWinPharma).toBe(true);
  });

  it("retombe sur le CSV générique sinon", () => {
    const r = chargerFichierTexte(encoder("Produit;Stock\nOZEMPIC;5\n"));
    expect(r.formatWinPharma).toBe(false);
    expect(r.colonnes).toEqual(["Produit", "Stock"]);
  });

  it("gère l'encodage ISO-8859-1 des exports WinPharma", () => {
    // « Réappro » encodé en latin-1 (0xE9 pour é).
    const latin1 = new Uint8Array([
      ..."Produit;R".split("").map((c) => c.charCodeAt(0)),
      0xe9,
      ..."appro\nX;12\n".split("").map((c) => c.charCodeAt(0)),
    ]);
    const r = chargerFichierTexte(latin1.buffer as ArrayBuffer);
    expect(r.colonnes).toContain("Réappro");
  });
});
