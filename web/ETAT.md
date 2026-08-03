# Portage web — SUSPENDU

Ce dossier contient une réécriture de l'utilitaire en application web
(Next.js + Supabase + Vercel), engagée puis **arrêtée** : le choix retenu
est de **conserver l'architecture Python** de la racine du dépôt.

**La source de vérité est l'application Streamlit à la racine.** Ce dossier
n'est plus suivi : il ne reçoit ni les corrections, ni les modules récents.

## Où en était le portage

| Élément | État |
|---|---|
| Moteur stock min/max | porté, **0 écart** avec Python sur 3 528 produits |
| Moteur ruptures GPNC/UNIPHARMA | porté, **0 écart** sur les fichiers réels |
| Lecture du cadencier WinPharma (CSV) | portée |
| Export Excel | porté (ExcelJS) |
| Comptes d'équipe, enregistrement des analyses | en place (Supabase) |
| Tests | 168 tests Vitest |

**Jamais porté** : le module de **stock fermé** (créé après l'arrêt), la
lecture des formats **PDF et .xlsx**, l'interface des ruptures et les
réglages avancés.

## Que faire de ce dossier

- **Le garder** ne coûte rien : il n'est pas exécuté par l'application
  Python et ses dépendances (`web/node_modules/`) ne sont pas versionnées.
- **Le supprimer** est sans risque pour l'application Python.

Reprendre le portage supposerait de repartir de l'état actuel du code
Python, qui a divergé depuis.
