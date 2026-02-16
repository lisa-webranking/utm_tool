# SKILL: Generazione automatica parametri UTM

## Scopo
Generare **parametri UTM coerenti** (`utm_source`, `utm_medium`, `utm_campaign` + opzionali `utm_term`, `utm_content`) e costruire l’**URL finale** rispettando naming convention e struttura del link.

## Quando attivarla (trigger)
Attiva questa skill quando l’utente:
- chiede di “creare/generare UTM”, “taggare un link”, “costruire URL tracciato”
- descrive una campagna (email, social, paid, referral, offline, ecc.) e vuole un link con UTM
- incolla un URL e chiede di aggiungere UTM

---

## Input richiesti (domande minime)
Raccogli solo ciò che serve, chiedendo **solo i campi mancanti**.

### 1) URL di destinazione (mandatory)
- `base_url` (es. `https://www.tuosito.it/pagina`)

### 2) Parametri UTM mandatory
- `traffic_type` (per aiutare a proporre `utm_medium`/`utm_source`)
- `utm_source` (sorgente)
- `utm_medium` (mezzo)
- `utm_campaign` (secondo struttura definita sotto)

### 3) Parametri opzionali
- `utm_term` (keyword / caratteristica campagna)
- `utm_content` (dettaglio per distinguere contenuti simili o un dettaglio significativo)

---

## Output atteso
Il bot deve restituire:
1) una **tabella/riassunto** dei parametri valorizzati  
2) l’**URL finale** completo

Formato consigliato (adattabile al tool):

```json
{
  "utm_source": "…",
  "utm_medium": "…",
  "utm_campaign": "…",
  "utm_term": "… (opzionale)",
  "utm_content": "… (opzionale)",
  "final_url": "https://…"
}
```

---

## Regole UTM (obbligatorie / best practice dal template)

### Parametri e significato
- **utm_source (mandatory)**: fonte principale/origine del traffico  
- **utm_medium (mandatory)**: mezzo/canale attraverso cui arriva il traffico  
- **utm_campaign (mandatory)**: nome della singola campagna  
- **utm_term (optional)**: keyword usate / caratteristiche della campagna  
- **utm_content (optional)**: differenziare contenuti simili o dettaglio importante  

### Naming convention
1) **Solo minuscole** (case-sensitive: “Facebook” ≠ “facebook”).  
2) **No spazi e no caratteri speciali**: usare `_` o `-`. Evitare `? % & $ !` ecc.  
3) **Coerenza**: definire una struttura e seguirla (non alternare “newsletter” e “email_marketing”).  
4) **Descrittivo ma conciso**: evitare nomi lunghi o ridondanti.  
5) **Trattini preferiti dentro i token**: quando separi parole *dentro lo stesso valore*, usare `-`.  

---

## Costruzione URL (regole)
- Un URL con UTM ha forma:  
  `https://www.tuosito.it?utm_source=...&utm_medium=...&utm_campaign=...`
- `?` separa URL base e parametri.
- `&` unisce i parametri.
- Se `base_url` contiene già `?`, aggiungi UTM con `&` (non duplicare `?`).

---

## Mapping suggerito per utm_medium e utm_source (dal template)

Usa `traffic_type` per proporre valori coerenti (l’utente può sempre sovrascrivere).

| Traffic type | utm_medium | utm_source (esempi) |
|---|---|---|
| Organic | `organic` | `google`, `bing`, `yahoo`, `yandex`, … |
| Referral | `referral` | `[website domain]` |
| Direct | `(none)` | `(direct)` |
| Paid campaign | `cpc` | `google`, `bing`, … |
| Affiliate campaign | `affiliate` | `tradetracker`, … |
| Display campaign | `cpm` | `reservation`, `display`, `programmatic_video`, … |
| Video campaign | `cpv` | `youtube`, … |
| Programmatic campaign | `cpm` | `rcs`, `mediamond`, `rai`, `ilsole24ore` |
| Organic email | `email|mailing_campaign` | `newsletter`, `email`, `crm` |
| Social organic | `social_org` | `facebook`, `instagram`, … (nome social) |
| Social paid | `social_paid` | `facebook`, `instagram`, … (nome social) |
| App traffic | *(non valorizzato nel template)* | `app` |
| Offline | `offline` | `brochure`, `qr_code`, `sms` |

> **Nota App traffic**: nel template `utm_medium` è vuoto. Comportamento consigliato della skill: chiedere all’utente quale medium usare **oppure** applicare un default configurabile dal tool (se previsto), mantenendo `utm_source=app`.

---

## Regole per utm_campaign (struttura + vincoli)

### Struttura (obbligatoria)
`utm_campaign = country-lingua_campaignType_campaignName_data[_CTA]`

Dove i **token sono separati da underscore `_`**.

#### Token richiesti (mandatory)
1) `country-lingua`  
   - `country` è il codice paese (es. `it`, `ch`, `es`, …)  
   - “lingua” è inclusa nello stesso token secondo la dicitura del template (rappresentala con un codice lingua coerente con le tue regole interne).  
2) `campaignType` (uno tra):  
   - `promo` (promotional)  
   - `ed` (editorial)  
   - `tr` (transactional)  
   - `awr` (awareness)  
3) `campaignName` (nome interno della campagna)  
4) `data` (data invio email / riferimento temporale campagna)  

#### Token opzionale
5) `CTA` (es. `cta`, `image`, `banner`, …)

### Golden rules (obbligatorie)
- La struttura sopra va rispettata.
- `country(-lingua)`, `campaignType`, `campaignName` sono **obbligatori**.
- Separazione tra token: **underscore `_` obbligatorio**.
- Dentro un token, separa parole con **trattino `-`** (mai spazi).
- Vietati caratteri speciali come `%` e `&`.

---

## Regole per utm_term (linee guida dal template)
- Utile per tracciare keyword e caratteristiche specifiche.
- Esempi di valori (categorie prodotto):  
  `nursing`, `toys`, `indoor`, `fashion`, `toiletries`, `car-seat`, `outdoor`

---

## Validazioni che il bot deve applicare
1) Blocca/riporta errore se mancano: `utm_source`, `utm_medium`, `utm_campaign`, `base_url`.
2) Controlla `utm_campaign`:
   - token separati da `_`
   - presenza minima dei 4 token richiesti
   - assenza di spazi, `%`, `&` e caratteri speciali
3) Forza lowercase su tutti i parametri.
4) Sostituisci spazi con `-` nei valori (se l’utente li inserisce).
5) Non cambiare il significato: se una regola non è definita nel template (es. formato data), non imporla come obbligatoria. Al massimo suggerisci un formato nel tuo tool come “consigliato”.

---

## Flow conversazionale consigliato (senza domande ridondanti)
1) Chiedi `base_url`.
2) Chiedi `traffic_type` e proponi `utm_medium` + `utm_source` coerenti (tabella sopra).
3) Costruisci `utm_campaign` chiedendo solo i token mancanti:
   - country-lingua
   - campaignType (mostra opzioni: `promo` / `ed` / `tr` / `awr`)
   - campaignName
   - data
   - CTA (opzionale)
4) Chiedi opzionali `utm_term` e `utm_content` solo se utili (es. più creatività, più varianti, keyword tracking).
5) Restituisci parametri + URL finale.

---

## Esempio output (coerente col template)
URL:
`https://www.yourwebsite.com/?utm_source=facebook&utm_medium=social&utm_campaign=it-it_promo_spring-sale_2026-02-10`
