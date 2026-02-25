# Skill MCP — GA4 UTM Post-Live Check

Questa skill MCP aggiunge al tuo tool UTM una sezione “Post-live check” che interroga GA4 (Analytics Data API) per verificare:

- se la campagna sta generando **sessioni**
- in quale **canale** (GA4 *Session default channel group*) viene attribuito il traffico
- se c’è un errore (nessun traffico) o un warning (canale errato)

---

## 1) Regole di stato

### A) Campagna senza traffico
**Condizione**
- `sessions_observed = 0`
- e `today >= start_date + grace_days`

**Output**
- `status_tracking = "ERRORE"`
- `status_message = "Nessun traffico rilevato con questi UTM"`

### B) Canale sbagliato
**Condizione**
- `sessions_observed > 0`
- e `channel_group_observed != expected_channel_grouping`

**Output**
- `status_tracking = "WARNING"`
- `status_message = "Il traffico è finito in [channel_group_observed] invece di [expected_channel_grouping]"`

### C) Tracking ok
**Condizione**
- `sessions_observed > 0`
- e `channel_group_observed = expected_channel_grouping`

**Output**
- `status_tracking = "OK"`
- `status_message = "Tracking e canalizzazione corretti"`

### D) (Opzionale) PENDING
Per evitare falsi negativi appena la campagna va live:

**Condizione**
- `sessions_observed = 0`
- e `today < start_date + grace_days`

**Output**
- `status_tracking = "PENDING"`
- `status_message = "Campagna live da poco: in attesa di dati"`

---

## 2) Schema input della skill

Tool name: `ga4_utm_postlive_check`

```json
{
  "ga4_property_id": "123456789",
  "grace_days": 2,
  "timezone": "Europe/Rome",
  "campaigns": [
    {
      "campaign_name": "Saldi inverno jeans donna",
      "start_date": "2026-01-10",
      "end_date": "2026-01-31",
      "utm_source": "meta",
      "utm_medium": "paid_social",
      "utm_campaign": "saldi-inverno_jeans-donna_IT_202601",
      "expected_channel_grouping": "Paid Social"
    }
  ]
}