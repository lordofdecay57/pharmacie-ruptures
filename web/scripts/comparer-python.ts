import { readFileSync } from "node:fs";
import { analyserStockRotation } from "../src/lib/calculs/stock-rotation";

const S = "/tmp/claude-0/-home-user-pharmacie-ruptures/bef50a42-b51c-530a-8015-8f8ac8856d3f/scratchpad";
const data = JSON.parse(readFileSync(`${S}/cadencier.json`, "utf8"));
const ref = JSON.parse(readFileSync(`${S}/ref_python.json`, "utf8"));

const m = data.mapping;
const res = analyserStockRotation(
  data.lignes,
  { libelle: m.libelle, cip: m.cip, stock: m.stock, ventes: m.ventes },
  {},
  new Date(2026, 6, 21),
);
console.log("TypeScript — lignes:", res.tableau.length);
console.log("Résumé TS:", JSON.stringify(res.resume));

// Comparaison ligne à ligne, appariée par CIP+nom
const cle = (c: string, n: string) => `${c}|${n}`;
const tsMap = new Map(res.tableau.map((l) => [cle(l.codeCip, l.nomProduit), l]));
let ecarts = 0;
const exemples: string[] = [];
for (const r of ref) {
  const t = tsMap.get(cle(r.cip, r.nom));
  if (!t) { ecarts++; if (exemples.length < 5) exemples.push(`ABSENT: ${r.nom}`); continue; }
  if (t.stockMin !== r.min || t.stockMax !== r.max || t.qteACommander !== r.qte || t.alerte !== r.alerte) {
    ecarts++;
    if (exemples.length < 5) exemples.push(
      `${r.nom}: py(min=${r.min},max=${r.max},qte=${r.qte},${r.alerte}) ts(min=${t.stockMin},max=${t.stockMax},qte=${t.qteACommander},${t.alerte})`);
  }
}
console.log(`\nÉcarts sur ${ref.length} produits : ${ecarts}`);
exemples.forEach((e) => console.log("  " + e));
