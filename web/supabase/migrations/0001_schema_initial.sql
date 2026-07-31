-- ===========================================================================
-- Pilotage pharmacie — schéma initial
--
-- Modèle : une PHARMACIE regroupe plusieurs MEMBRES (l'équipe). Chaque
-- analyse de cadencier est enregistrée avec ses lignes de stock, ce qui
-- remplace le fichier local `etat_stock_precedent.csv` : la comparaison
-- « cadencier n+1 » se fait en relisant la dernière analyse de la pharmacie.
--
-- Sécurité : Row Level Security partout. Un membre ne voit QUE les données
-- de sa propre pharmacie — aucune fuite possible entre officines.
-- ===========================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Pharmacies et membres
-- ---------------------------------------------------------------------------

create table if not exists public.pharmacies (
  id         uuid primary key default gen_random_uuid(),
  nom        text not null,
  cree_le    timestamptz not null default now()
);

create table if not exists public.membres (
  id            uuid primary key references auth.users (id) on delete cascade,
  pharmacie_id  uuid not null references public.pharmacies (id) on delete cascade,
  email         text,
  role          text not null default 'membre' check (role in ('admin', 'membre')),
  cree_le       timestamptz not null default now()
);

create index if not exists membres_pharmacie_idx on public.membres (pharmacie_id);

-- ---------------------------------------------------------------------------
-- Analyses et lignes de stock
-- ---------------------------------------------------------------------------

create table if not exists public.analyses (
  id                  uuid primary key default gen_random_uuid(),
  pharmacie_id        uuid not null references public.pharmacies (id) on delete cascade,
  cree_par            uuid references auth.users (id) on delete set null,
  date_analyse        date not null,
  -- Empreinte des colonnes du cadencier : la comparaison n+1 n'a de sens que
  -- si le document de base a la même structure.
  signature_colonnes  text,
  parametres          jsonb not null default '{}'::jsonb,
  resume              jsonb not null default '{}'::jsonb,
  cree_le             timestamptz not null default now()
);

create index if not exists analyses_pharmacie_date_idx
  on public.analyses (pharmacie_id, cree_le desc);

create table if not exists public.lignes_stock (
  id                    bigint generated always as identity primary key,
  analyse_id            uuid not null references public.analyses (id) on delete cascade,
  code_cip              text,
  nom_produit           text not null,
  alerte                text not null,
  classe                text,
  stock_actuel          integer,
  commande_en_cours     integer,
  consommation_mois     numeric,
  tendance              text,
  variabilite           text,
  stock_min             integer,
  stock_max             integer,
  stock_min_conseille   integer,
  qte_a_commander       integer,
  motif                 text,
  modifie               boolean
);

create index if not exists lignes_stock_analyse_idx on public.lignes_stock (analyse_id);
-- Accélère la comparaison n+1 (appariement CIP + libellé).
create index if not exists lignes_stock_cle_idx
  on public.lignes_stock (analyse_id, code_cip, nom_produit);

-- ---------------------------------------------------------------------------
-- Sécurité : chaque membre est cantonné à sa pharmacie
-- ---------------------------------------------------------------------------

alter table public.pharmacies  enable row level security;
alter table public.membres     enable row level security;
alter table public.analyses    enable row level security;
alter table public.lignes_stock enable row level security;

-- Pharmacie de l'utilisateur courant. SECURITY DEFINER pour éviter une
-- récursion infinie des politiques sur `membres`.
create or replace function public.pharmacie_courante()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select pharmacie_id from public.membres where id = auth.uid();
$$;

drop policy if exists "membre voit sa pharmacie" on public.pharmacies;
create policy "membre voit sa pharmacie" on public.pharmacies
  for select using (id = public.pharmacie_courante());

drop policy if exists "membre voit son equipe" on public.membres;
create policy "membre voit son equipe" on public.membres
  for select using (pharmacie_id = public.pharmacie_courante());

drop policy if exists "analyses de la pharmacie" on public.analyses;
create policy "analyses de la pharmacie" on public.analyses
  for all
  using (pharmacie_id = public.pharmacie_courante())
  with check (pharmacie_id = public.pharmacie_courante());

drop policy if exists "lignes de la pharmacie" on public.lignes_stock;
create policy "lignes de la pharmacie" on public.lignes_stock
  for all
  using (
    exists (
      select 1 from public.analyses a
      where a.id = lignes_stock.analyse_id
        and a.pharmacie_id = public.pharmacie_courante()
    )
  )
  with check (
    exists (
      select 1 from public.analyses a
      where a.id = lignes_stock.analyse_id
        and a.pharmacie_id = public.pharmacie_courante()
    )
  );

-- ---------------------------------------------------------------------------
-- Rattachement automatique d'un nouvel inscrit
--
-- L'équipe partage une seule pharmacie : à la première inscription elle est
-- créée, les suivants la rejoignent. Le nom peut être passé à l'inscription
-- via les métadonnées (`nom_pharmacie`).
-- ---------------------------------------------------------------------------

create or replace function public.rattacher_nouveau_membre()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  cible uuid;
begin
  select id into cible from public.pharmacies order by cree_le limit 1;
  if cible is null then
    insert into public.pharmacies (nom)
    values (coalesce(new.raw_user_meta_data ->> 'nom_pharmacie', 'Ma pharmacie'))
    returning id into cible;
  end if;

  insert into public.membres (id, pharmacie_id, email, role)
  values (
    new.id,
    cible,
    new.email,
    case when exists (select 1 from public.membres) then 'membre' else 'admin' end
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.rattacher_nouveau_membre();
