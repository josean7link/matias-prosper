# Prosper Platform — Compliance

> Regulatory stack, audit trail and SAR/STR workflow. Audience: compliance
> officers + auditors.

## 1. Regulatory framework

- **Argentina**: PSAV (Proveedores de Servicios de Activos Virtuales) registered
  with CNV. Ley 25.246 (PLA/FT) — KYC obligatorio, conservación 10 años,
  reporte UIF.
- **Custody**: Arvest Trust (fiduciario regulado). Subyacentes en Caja de
  Valores (depositario).
- **Rating**: Moody's evalúa activos del fondo subyacente periódicamente.
- **Travel Rule**: aplicable a transacciones ≥ USD 1.000 — emisor y
  beneficiario identificados con nombre completo + dirección.
- **Sanctions**: lista OFAC + UN consolidada — screening en KYB y en
  cada wallet a evaluar.

## 2. KYC (personas físicas)

Cola: `/admin/compliance/kyc`. SLAs:

| Estado     | SLA   |
|------------|-------|
| Verde      | <4h   |
| Amarillo   | <24h  |
| Rojo       | >24h (escalar) |

Documentos esperados (mínimo 4): documento de identidad anverso, reverso,
selfie con prueba de vida, proof of address (<3 meses).

Checks regulatorios automáticos:
1. AML screening (PEP + sanctions + adverse media)
2. Sanctions check (OFAC/UN)
3. PEP check
4. Document authenticity (AiPrise score)

Decisión requiere motive ≥ 20 caracteres. Audit log entry: `kyc.decision`
con `actor_user_id`, `decision`, `motive`.

## 3. KYB (personas jurídicas)

Cola: `/admin/compliance/kyb`. **8-item checklist obligatorio**:

1. Certificado verificado
2. Board resolution válido
3. UBO list completo y verificado
4. Proof of address vigente (<3 meses)
5. Estados financieros revisados
6. Sanctions check pasado
7. Sectoral risk evaluado
8. Ownership chart verificado

El botón "Aprobar" queda **disabled hasta 8/8 ticks**. La UI muestra el
counter "X/8" en tiempo real.

UBOs (Ultimate Beneficial Owners): toda persona física con ≥25% de
ownership directa o indirecta. PEP flag obligatorio.

## 4. KYT (transaction monitoring)

7 reglas configurables platform-wide en `/admin/compliance/kyt`:

| Rule ID                  | Default param                    | Severity |
|--------------------------|-----------------------------------|----------|
| `kyt.high_volume_new`    | >$50k en <7d del primer onramp    | warning  |
| `kyt.rapid_redeem`       | redeem dentro de 24h del subscribe| warning  |
| `kyt.fragmented_deposits`| >5 depósitos < $1k en 24h         | warning  |
| `kyt.geo_risky`          | counterparty en jurisdicción riesgo | critical |
| `kyt.dormant_revive`     | cuenta dormida >180d con tx >$10k | warning  |
| `kyt.same_day_round_trip`| onramp + offramp mismo día        | info     |
| `kyt.over_cap_attempt`   | intento de operar sobre cap       | info     |

Alertas: cola en `/admin/compliance/kyt` tab 2. Severity badges visibles.

## 5. Risk scoring

Score 0-100 calculado por componentes:
- **KYC freshness** (30%): edad del último refresh del KYC.
- **Volume** (25%): volumen 90d vs expected_aum_usd.
- **Geo** (25%): país declarado + países counterparties.
- **Behavior** (20%): patrones KYT (alertas históricas).

Buckets: low (<40), medium (40-60), high (60-80), critical (>80).

`/admin/compliance/risk` — donut + top-10 + drawer con drivers explicables.

## 6. SAR/STR (Suspicious Activity Report)

Cuando se detecta actividad sospechosa:

1. `/admin/compliance/risk` → seleccionar la org → "Generar borrador SAR/STR".
2. El sistema arma un JSON con: datos de la org, UBOs, últimas 50
   transacciones, alertas KYT, motive del oficial.
3. Compliance review interno antes de presentar a UIF.
4. **TODO Sprint 12+**: migrar JSON → PDF formal con firma digital.
5. Audit log: `sar.draft_generated` + `sar.submitted_to_uif` (cuando aplica).

> Plazo legal: 48h hábiles desde la detección del hecho sospechoso.

## 7. Audit trail

Inmutable, append-only. Colección `audit_logs`. Mutations bloqueadas vía
`audit_update_blocked()` y endpoint `PATCH /audit-logs/{id}` retorna 405.

Cada entry: `actor_user_id`, `action`, `resource_type`, `resource_id`,
`org_id`, `timestamp`, `ip`, `user_agent`, `metadata` (incluye
`acting_as_org` si hubo impersonación).

Acciones críticas trackeadas:
- Auth: `auth.login`, `auth.logout`, `client.session.revoke`
- KYC/KYB: `kyc.decision`, `kyb.decision`, `kyb.checklist.tick`
- Mints: `mint.requested`, `mint.approved`, `mint.executed`
- Caps: `caps.changed` (cliente + caps anteriores + nuevos)
- Compliance: `alert.acknowledged`, `alert.resolved`, `sar.*`
- Sistema: `admin.ops.wipe_demo`, `admin.ops.seed_demo_client`

Retention: **10 años** (ley 25.246).

## 8. Acceso del cliente al audit log

Cliente ve sólo sus propios entries: `GET /api/v1/audit-logs?limit=N`
con scope automático al org_id del JWT.

## 9. Compliance dashboards externos

- **Status**: `/admin/compliance/alerts` — vista centralizada con filtros
  + bulk acknowledge/resolve.
- **Limits**: `/admin/compliance/limits` — caps inline-editable + audit.
- **NAV**: dashboard interno `/admin` con snapshots diarios para reporting.

## 10. Procedimientos clave

Ver `RUNBOOK.md` para:
- Aprobar un KYB
- Investigar reconciliación unmatched
- Aumentar caps de un cliente
- Restaurar backup de Mongo
- Rotar API key comprometida
