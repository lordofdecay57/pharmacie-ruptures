import { readFileSync } from "node:fs";
import { chargerFichierTexte } from "../src/lib/fichiers/cadencier";
import { analyserStockRotation } from "../src/lib/calculs/stock-rotation";
import { detecterColonne, detecterColonnesVentes } from "../src/lib/calculs/commun";

const CSV = "/root/.claude/uploads/bef50a42-b51c-530a-8015-8f8ac8856d3f/3ef033a9-Candencier.csv";
const brut = readFileSync(CSV);
const charge = chargerFichierTexte(brut.buffer.slice(brut.byteOffset, brut.byteOffset + brut.byteLength) as ArrayBuffer);

console.log("Format WinPharma reconnu :", charge.formatWinPharma);
console.log("Produits lus :", charge.lignes.length, "| colonnes :", charge.colonnes.join(", "));

const mapping = {
  libelle: detecterColonne(charge.colonnes, "libelle")!,
  cip: detecterColonne(charge.colonnes, "cip"),
  stock: detecterColonne(charge.colonnes, "stock")!,
  ventes: detecterColonnesVentes(charge.colonnes),
};
console.log("Mapping auto :", JSON.stringify(mapping));

const res = analyserStockRotation(charge.lignes, mapping, {}, new Date(2026, 6, 21));
console.log("Résumé :", JSON.stringify(res.resume));

// Comparaison avec la référence Python (même fichier, mêmes paramètres)
const S = "/tmp/claude-0/-home-user-pharmacie-ruptures/bef50a42-b51c-530a-8015-8f8ac8856d3f/scratchpad";
const ref = JSON.parse(readFileSync(`${S}/ref_python.json`, "utf8"));
const cle = (c: string, n: string) => `${c}|${n}`;
const tsMap = new Map(res.tableau.map((l) => [cle(l.codeCip, l.nomProduit), l]));
let ecarts = 0;
const exemples: string[] = [];
for (const r of ref) {
  const t = tsMap.get(cle(r.cip, r.nom));
  if (!t) { ecarts++; if (exemples.length < 4) exemples.push(`ABSENT: ${r.nom}`); continue; }
  if (t.stockMin !== r.min || t.stockMax !== r.max || t.qteACommander !== r.qte || t.alerte !== r.alerte) {
    ecarts++;
    if (exemples.length < 4) exemples.push(
      `${r.nom}: py(${r.min}/${r.max}/${r.qte}/${r.alerte}) ts(${t.stockMin}/${t.stockMax}/${t.qteACommander}/${t.alerte})`);
  }
}
console.log(`\nCHAÎNE COMPLÈTE (lecture fichier + analyse) — écarts / ${ref.length} produits : ${ecarts}`);
exemples.forEach((e) => console.log("  " + e));
