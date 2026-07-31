"use client";

import { useMemo, useState } from "react";
import {
  detecterColonne,
  detecterColonnesVentes,
  type PeriodeRotation,
} from "@/lib/calculs/commun";
import {
  analyserStockRotation,
  comparerAEtatPrecedent,
  signatureColonnes,
  type LigneStock,
  type MappingCadencier,
  type ResultatStockRotation,
} from "@/lib/calculs/stock-rotation";
import { chargerFichierTexte } from "@/lib/fichiers/cadencier";
import { enregistrerAnalyse, type AnalysePrecedente } from "./actions";

const LIBELLE_PERIODE: Record<PeriodeRotation, string> = {
  annuelle: "Annuelle (12 mois)",
  "6mois": "Semestrielle (6 mois)",
  "3mois": "Trimestrielle (3 mois)",
  "1mois": "Mensuelle (dernier mois)",
  lissee: "Lissée (réactive)",
};

const COULEUR_ALERTE: Record<string, string> = {
  "🔴 Action requise": "bg-red-50 text-red-900",
  "🟡 Sous le min": "bg-amber-50 text-amber-900",
  "🟢 OK": "bg-emerald-50 text-emerald-900",
  "⚪ Rotation faible": "bg-stone-100 text-stone-600",
};

function Tuile({ libelle, valeur, sous }: { libelle: string; valeur: number | string; sous?: string }) {
  return (
    <div className="min-w-40 flex-1 rounded-xl border border-stone-200 bg-white p-3">
      <div className="text-xs text-stone-600">{libelle}</div>
      <div className="text-2xl font-bold text-stone-900">{valeur}</div>
      {sous && <div className="text-xs text-stone-500">{sous}</div>}
    </div>
  );
}

export default function Analyseur({ precedente }: { precedente: AnalysePrecedente | null }) {
  const [nomFichier, setNomFichier] = useState<string | null>(null);
  const [colonnes, setColonnes] = useState<string[]>([]);
  const [lignesBrutes, setLignesBrutes] = useState<Record<string, unknown>[]>([]);
  const [mapping, setMapping] = useState<MappingCadencier | null>(null);
  const [periode, setPeriode] = useState<PeriodeRotation>("annuelle");
  const [dateAnalyse, setDateAnalyse] = useState(() => new Date().toISOString().slice(0, 10));
  const [resultat, setResultat] = useState<ResultatStockRotation | null>(null);
  const [documentDifferent, setDocumentDifferent] = useState(false);
  const [voirTout, setVoirTout] = useState(false);
  const [detail, setDetail] = useState(false);
  const [recherche, setRecherche] = useState("");
  const [filtre, setFiltre] = useState("Toutes");
  const [etat, setEtat] = useState<string | null>(null);
  const [enregistre, setEnregistre] = useState(false);

  async function deposer(fichier: File) {
    setEtat("Lecture du fichier…");
    setResultat(null);
    setEnregistre(false);
    try {
      const charge = chargerFichierTexte(await fichier.arrayBuffer());
      const ventes = detecterColonnesVentes(charge.colonnes);
      setNomFichier(fichier.name);
      setColonnes(charge.colonnes);
      setLignesBrutes(charge.lignes);
      setMapping({
        libelle: detecterColonne(charge.colonnes, "libelle") ?? charge.colonnes[0],
        cip: detecterColonne(charge.colonnes, "cip"),
        stock: detecterColonne(charge.colonnes, "stock") ?? charge.colonnes[0],
        ventes,
        commandeEnCours: detecterColonne(charge.colonnes, "commande_en_cours"),
      });
      setEtat(
        `${charge.lignes.length} produits lus` +
          (charge.formatWinPharma ? " — format WinPharma reconnu." : "."),
      );
    } catch (e) {
      setEtat(`Fichier illisible : ${(e as Error).message}`);
    }
  }

  function lancer() {
    if (!mapping || lignesBrutes.length === 0) return;
    setEtat("Analyse en cours…");
    setEnregistre(false);

    const res = analyserStockRotation(
      lignesBrutes,
      mapping,
      { periodeRotation: periode },
      new Date(`${dateAnalyse}T00:00:00`),
    );

    // Cadencier n+1 : la comparaison n'a de sens que si le document de base
    // a la même structure de colonnes que la dernière analyse.
    const signature = signatureColonnes(colonnes);
    const memeDocument =
      !!precedente && precedente.signatureColonnes === signature;
    setDocumentDifferent(!!precedente && !memeDocument);

    const compare = comparerAEtatPrecedent(
      res.tableau,
      memeDocument ? precedente!.etat : null,
    );
    res.tableau = compare.tableau;
    res.resume.nbModifiees = compare.nbModifiees;
    res.resume.nbNouvelles = compare.nbNouvelles;
    res.resume.etatPrecedentExistant = memeDocument;
    setResultat(res);
    setVoirTout(!memeDocument);
    setEtat(null);
  }

  async function sauvegarder() {
    if (!resultat || !mapping) return;
    setEtat("Enregistrement…");
    const r = await enregistrerAnalyse({
      dateAnalyse,
      signatureColonnes: signatureColonnes(colonnes),
      parametres: { periodeRotation: periode },
      resume: resultat.resume,
      lignes: resultat.tableau,
    });
    setEtat(r.ok ? null : `Échec : ${r.message}`);
    setEnregistre(r.ok);
  }

  const affichees: LigneStock[] = useMemo(() => {
    if (!resultat) return [];
    let lignes = resultat.tableau;
    if (resultat.resume.etatPrecedentExistant && !voirTout) {
      lignes = lignes.filter((l) => l.modifie);
    }
    if (filtre !== "Toutes") lignes = lignes.filter((l) => l.alerte === filtre);
    const terme = recherche.trim().toUpperCase();
    if (terme) {
      lignes = lignes.filter(
        (l) =>
          l.nomProduit.toUpperCase().includes(terme) || l.codeCip.includes(terme),
      );
    }
    return lignes;
  }, [resultat, voirTout, filtre, recherche]);

  const rs = resultat?.resume;

  return (
    <div className="space-y-6">
      {/* Étape 1 — dépôt du cadencier */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5">
        <h2 className="font-semibold text-stone-900">1 · Déposez le cadencier</h2>
        <p className="mt-1 text-sm text-stone-600">
          Export WinPharma (CSV). Le fichier est analysé <b>dans votre
          navigateur</b> : il n&apos;est pas téléversé, seuls les résultats sont
          enregistrés.
        </p>
        <input
          type="file"
          accept=".csv,.txt"
          onChange={(e) => e.target.files?.[0] && deposer(e.target.files[0])}
          className="mt-3 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-teal-700 file:px-4 file:py-2 file:text-white"
        />
        {nomFichier && (
          <p className="mt-2 text-sm text-stone-700">
            📄 {nomFichier} — {lignesBrutes.length} lignes
          </p>
        )}
      </section>

      {/* Étape 2 — réglages et lancement */}
      {mapping && (
        <section className="rounded-2xl border border-stone-200 bg-white p-5">
          <h2 className="font-semibold text-stone-900">2 · Réglages et analyse</h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <label className="text-sm">
              <span className="text-stone-600">Calcul de la consommation</span>
              <select
                value={periode}
                onChange={(e) => setPeriode(e.target.value as PeriodeRotation)}
                className="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2"
              >
                {Object.entries(LIBELLE_PERIODE).map(([v, t]) => (
                  <option key={v} value={v}>{t}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="text-stone-600">Date d&apos;analyse</span>
              <input
                type="date"
                value={dateAnalyse}
                onChange={(e) => setDateAnalyse(e.target.value)}
                className="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2"
              />
            </label>
            <div className="text-sm">
              <span className="text-stone-600">Colonnes détectées</span>
              <p className="mt-1 text-xs text-stone-500">
                Produit : <b>{mapping.libelle}</b> · Stock : <b>{mapping.stock}</b>
                <br />
                {mapping.ventes.length} mois de ventes
              </p>
            </div>
          </div>
          <button
            onClick={lancer}
            className="mt-4 w-full rounded-lg bg-teal-700 py-2.5 font-medium text-white hover:bg-teal-800"
          >
            🔍 Lancer l&apos;analyse
          </button>
        </section>
      )}

      {etat && (
        <p className="rounded-lg bg-stone-100 p-3 text-sm text-stone-700">{etat}</p>
      )}

      {/* Étape 3 — résultats */}
      {resultat && rs && (
        <section className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Tuile libelle="Produits pilotés" valeur={rs.totalProduits}
                   sous={`A ${rs.nbA} · B ${rs.nbB} · C ${rs.nbC}`} />
            <Tuile libelle="🔴 Action requise" valeur={rs.actionRequise} />
            <Tuile libelle="🟡 Sous le min" valeur={rs.sousLeMin} />
            <Tuile libelle="Qté à commander" valeur={rs.qteTotaleACommander}
                   sous="hors rotation faible" />
            <Tuile libelle="⚪ Rotation faible" valeur={rs.rotationFaible} />
          </div>

          {documentDifferent && (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              📄 Le cadencier déposé a une <b>structure différente</b> de la
              dernière analyse — toutes les lignes sont affichées.
            </p>
          )}
          {rs.etatPrecedentExistant && (
            <div className="rounded-lg bg-sky-50 p-3 text-sm text-sky-900">
              🔁 <b>{rs.nbModifiees} ligne(s) modifiée(s)</b> depuis l&apos;analyse
              du {precedente?.dateAnalyse} (dont {rs.nbNouvelles} nouvelle(s)) —
              variation du stock min/max ≥ 10 %.
              <label className="ml-2 inline-flex items-center gap-1">
                <input type="checkbox" checked={voirTout}
                       onChange={(e) => setVoirTout(e.target.checked)} />
                <span>afficher aussi les lignes inchangées</span>
              </label>
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="text-stone-600">🔎 Rechercher</span>
              <input
                value={recherche}
                onChange={(e) => setRecherche(e.target.value)}
                placeholder="nom ou code CIP"
                className="mt-1 block rounded-lg border border-stone-300 px-3 py-1.5"
              />
            </label>
            <label className="text-sm">
              <span className="text-stone-600">Alerte</span>
              <select value={filtre} onChange={(e) => setFiltre(e.target.value)}
                      className="mt-1 block rounded-lg border border-stone-300 px-3 py-1.5">
                {["Toutes", "🔴 Action requise", "🟡 Sous le min", "🟢 OK", "⚪ Rotation faible"]
                  .map((f) => <option key={f}>{f}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 pb-1.5 text-sm text-stone-700">
              <input type="checkbox" checked={detail}
                     onChange={(e) => setDetail(e.target.checked)} />
              ＋ Colonnes d&apos;analyse
            </label>
            <button
              onClick={sauvegarder}
              disabled={enregistre}
              className="ml-auto rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
            >
              {enregistre ? "✓ Enregistré" : "💾 Enregistrer l'analyse"}
            </button>
          </div>

          <p className="text-xs text-stone-500">
            {affichees.length} produit(s) affiché(s). Document de base centré sur
            le stock min/max ; <b>Stock actuel</b> et <b>Qté à commander</b>{" "}
            apparaissent via « ＋ Colonnes d&apos;analyse ».
          </p>

          <div className="max-h-[32rem] overflow-auto rounded-xl border border-stone-200">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-stone-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">Alerte</th>
                  <th className="px-3 py-2 font-medium">Code CIP</th>
                  <th className="px-3 py-2 font-medium">Nom du produit</th>
                  <th className="px-3 py-2 text-right font-medium">Stock min</th>
                  <th className="px-3 py-2 text-right font-medium">Stock max</th>
                  <th className="px-3 py-2 text-right font-medium">Min conseillé</th>
                  {detail && (
                    <>
                      <th className="px-3 py-2 text-right font-medium">Stock actuel</th>
                      <th className="px-3 py-2 text-right font-medium">Qté à commander</th>
                      <th className="px-3 py-2 text-right font-medium">Conso/mois</th>
                      <th className="px-3 py-2 font-medium">Classe</th>
                      <th className="px-3 py-2 font-medium">Motif</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {affichees.slice(0, 500).map((l, i) => (
                  <tr key={`${l.codeCip}-${l.nomProduit}-${i}`} className="border-t border-stone-100">
                    <td className={`px-3 py-1.5 whitespace-nowrap ${COULEUR_ALERTE[l.alerte] ?? ""}`}>
                      {l.alerte}
                    </td>
                    <td className="px-3 py-1.5 text-stone-600">{l.codeCip}</td>
                    <td className="px-3 py-1.5">{l.nomProduit}</td>
                    <td className="px-3 py-1.5 text-right">{l.stockMin}</td>
                    <td className="px-3 py-1.5 text-right">{l.stockMax}</td>
                    <td className="px-3 py-1.5 text-right">{l.stockMinConseille}</td>
                    {detail && (
                      <>
                        <td className="px-3 py-1.5 text-right">{l.stockActuel}</td>
                        <td className="px-3 py-1.5 text-right">{l.qteACommander}</td>
                        <td className="px-3 py-1.5 text-right">{l.consommationMois}</td>
                        <td className="px-3 py-1.5">{l.classe}</td>
                        <td className="px-3 py-1.5 text-xs text-stone-500">{l.motif}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {affichees.length > 500 && (
            <p className="text-xs text-stone-500">
              Affichage limité aux 500 premières lignes — affinez la recherche.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
