# Disk / Git hygiene — estado (Jun 2026)

## Hecho
- `frontend/.next` UNTRACKED de git (`git rm -r --cached`) + agregado a `.gitignore`
  (`.next/`, `frontend/.next/`). Esto detiene el crecimiento de `.git` (~5.8GB).
- `git prune --expire=now` ejecutado: no liberó espacio porque los ~3.5GB de
  objetos sueltos son ALCANZABLES (historial de commits con .next adentro).

## NO hacer
- NO correr `git gc --aggressive` ni `git repack -a` con <2GB libres: el repack
  necesita espacio temporal y un ENOSPC a mitad deja `tmp_pack_*` (el bug recurrente).
- NO reescribir historial (filter-repo): rompe checkpoints/rollback de Emergent.

## Si el disco vuelve a llenarse
1. `df -h /app` + borrar `/app/.git/objects/pack/tmp_*` si existen.
2. Candidatos a borrar: `/app/prosper-project.zip` (114M, export ya entregado al usuario),
   `/app/frontend/node_modules/.cache` (84M, regenerable).
3. `.env` files SIGUEN trackeados a propósito (el deploy de Emergent los necesita
   para inyectar secrets — ver comentario en .gitignore). No des-trackear.
