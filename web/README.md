# Pilotage pharmacie — version web (Next.js + Supabase + Vercel)

Réécriture de l'utilitaire en application web : interface **Next.js**
(déployée sur **Vercel**), données et comptes d'équipe sur **Supabase**.

L'application Streamlit locale (racine du dépôt) reste opérationnelle : les
deux peuvent coexister pendant la transition.

## Ce qui est en place

| Élément | État |
|---|---|
| Moteur de calcul du stock min/max | ✅ porté en TypeScript, **0 écart** avec le moteur Python sur le cadencier réel (3 528 produits) |
| Lecture du cadencier WinPharma (CSV) | ✅ bandeau, achats (A) ignorés, ventes (V) remises en ordre |
| Comptes d'équipe + isolation des données | ✅ Supabase Auth + Row Level Security |
| Enregistrement des analyses | ✅ tables `analyses` et `lignes_stock` |
| Comparaison « cadencier n+1 » (≥ 10 %) | ✅ référence = dernière analyse en base |
| Tests automatiques | ✅ 108 tests Vitest |

**Pas encore porté** (l'application Streamlit reste la référence pour ces
points) : le module de **gestion des ruptures** GPNC/UNIPHARMA, l'**export
Excel**, la lecture des formats **PDF et .xlsx**, et le détail des réglages
avancés (couvertures et seuils réglables depuis l'interface).

## Confidentialité

Le cadencier est lu et analysé **dans le navigateur** : le fichier lui-même
n'est jamais téléversé. Seuls les **résultats** (produit, stock min/max,
quantité) sont enregistrés dans Supabase, où chaque pharmacie ne voit que ses
propres données (Row Level Security).

## Installation

### 1. Créer le projet Supabase

1. Créer un projet sur <https://supabase.com>.
2. Dans **SQL Editor**, exécuter le contenu de
   `supabase/migrations/0001_schema_initial.sql`. Cela crée les tables, la
   sécurité par pharmacie et le rattachement automatique des inscrits.
3. Dans **Project Settings → API**, relever `Project URL` et la clé
   `anon public`.

> Le premier compte créé devient **admin** et crée la pharmacie ; les
> suivants la rejoignent automatiquement comme membres.

### 2. Lancer en local

```bash
cd web
npm install
cp .env.example .env.local   # puis renseigner les deux variables
npm run dev
```

L'application est disponible sur <http://localhost:3000>.

### 3. Déployer sur Vercel

1. Sur <https://vercel.com> : **Add New → Project**, importer ce dépôt GitHub.
2. **Important** : régler *Root Directory* sur `web` (le dépôt contient aussi
   l'application Python à la racine).
3. Ajouter les variables d'environnement :
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
4. **Deploy**. Les déploiements suivants sont automatiques à chaque `push`.

Enfin, dans Supabase → **Authentication → URL Configuration**, ajouter
l'adresse Vercel (`https://…vercel.app`) aux *Redirect URLs*.

## Commandes

```bash
npm run dev      # développement
npm run build    # build de production
npm test         # tests (Vitest)
npm run verifier # tests + typecheck + comparaison au moteur Python
```

## Organisation

```
web/
├── src/
│   ├── app/
│   │   ├── analyse/          # page principale (dépôt, analyse, tableau)
│   │   ├── connexion/        # authentification de l'équipe
│   │   └── page.tsx
│   ├── lib/
│   │   ├── calculs/          # moteur métier porté depuis Python
│   │   │   ├── commun.ts     # parsing, rotation, ABC, tendance…
│   │   │   └── stock-rotation.ts
│   │   ├── fichiers/         # lecture du cadencier WinPharma
│   │   └── supabase/         # clients navigateur et serveur
│   └── proxy.ts              # session + protection des pages (ex-middleware)
├── supabase/migrations/      # schéma SQL
└── scripts/                  # comparaison au moteur Python
```

## Fidélité des calculs

`scripts/comparer-python.ts` rejoue l'analyse TypeScript sur le cadencier réel
et la compare, produit par produit, aux résultats du moteur Python : stock
min, stock max, quantité à commander et alerte doivent être **identiques**.
C'est le garde-fou de non-régression de la réécriture.
