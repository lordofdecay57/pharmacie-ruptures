import { readFileSync } from "node:fs";
import { analyserRuptures } from "../src/lib/calculs/ruptures-analyse";

const S = "/tmp/claude-0/-home-user-pharmacie-ruptures/bef50a42-b51c-530a-8015-8f8ac8856d3f/scratchpad";
const e = JSON.parse(readFileSync(`${S}/ruptures_entrees.json`, "utf8"));
const ref = JSON.parse(readFileSync(`${S}/ref_ruptures.json`, "utf8"));
const m = e.mapping;

const res = analyserRuptures(
  e.cadencier, e.gpnc, e.unipharma,
  {
    cadencier: { libelle: m.cadencier.libelle, cip: m.cadencier.cip, stock: m.cadencier.stock, ventes: m.cadencier.ventes },
    gpnc: { libelle: m.gpnc.libelle, cip: m.gpnc.cip, dateReappro: m.gpnc.date_reappro },
    unipharma: { libelle: m.unipharma.libelle, cip: m.unipharma.cip },
  },
  new Date(2026, 6, 21),
);

console.log("TS resume:", JSON.stringify(res.resume));
const ecarts: string[] = [];
const cmp = (nom: string, a: unknown, b: unknown) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) ecarts.push(`${nom}: py=${JSON.stringify(a)} ts=${JSON.stringify(b)}`);
};
const r = ref.resume;
cmp("a_commander", r.a_commander, res.resume.aCommander);
cmp("sans_solution", r.sans_solution, res.resume.sansSolution);
cmp("vigilance", r.vigilance, res.resume.vigilance);
cmp("justesse", r.justesse, res.resume.justesse);
cmp("urgents", r.urgents, res.resume.urgents);
cmp("vendus", r.vendus, res.resume.vendus);
cmp("analyses", r.analyses, res.resume.analyses);

// Onglet 1 : produits, quantités, urgences, ordre
cmp("onglet1.produits", ref.onglet1.map((l: {produit:string}) => l.produit), res.onglet1.map((l) => l.produit));
cmp("onglet1.cmd", ref.onglet1.map((l: {cmd:number}) => l.cmd), res.onglet1.map((l) => l.qteACommander));
cmp("onglet1.urgence", ref.onglet1.map((l: {urgence:string}) => l.urgence), res.onglet1.map((l) => l.urgence));
cmp("onglet1.priorite", ref.onglet1.map((l: {priorite:number}) => l.priorite), res.onglet1.map((l) => l.priorite));
cmp("onglet2", ref.onglet2, res.onglet2.map((l) => l.produit));
cmp("vigilance.produits", ref.vigilance, res.vigilance.map((l) => l.produit));
cmp("justesse.produits", ref.justesse, res.ecartesJustesse.map((l) => l.produit));

console.log(`\nMODULE RUPTURES — écarts : ${ecarts.length}`);
ecarts.forEach((x) => console.log("  " + x));
