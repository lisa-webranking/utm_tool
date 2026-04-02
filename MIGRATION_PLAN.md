# Piano di Migrazione — UTM Governance Tool

> Stato attuale: monolite Streamlit (~200KB `app.py` + ~96KB `chatbot_ui.py`) con persistenza su file JSON, OAuth locale, zero test.
> Obiettivo: applicazione production-ready, multi-utente, deployabile su Cloud Run.

---

## Indice

1. [Stato attuale e problemi critici](#1-stato-attuale-e-problemi-critici)
2. [Architettura target](#2-architettura-target)
3. [Fase 0 — Hotfix immediati](#3-fase-0--hotfix-immediati-1-2-giorni)
4. [Fase 1 — Estrazione del data layer](#4-fase-1--estrazione-del-data-layer-3-4-giorni)
5. [Fase 2 — Separazione backend / UI](#5-fase-2--separazione-backend--ui-4-5-giorni)
6. [Fase 3 — Containerizzazione e Cloud Run](#6-fase-3--containerizzazione-e-cloud-run-3-4-giorni)
7. [Fase 4 — Hardening e observability](#7-fase-4--hardening-e-observability-2-3-giorni)
8. [Fase 5 (opzionale) — Migrazione frontend a Next.js](#8-fase-5-opzionale--migrazione-frontend-a-nextjs)
9. [Decisioni architetturali aperte](#9-decisioni-architetturali-aperte)

---

## 1. Stato attuale e problemi critici

### 1.1 Persistenza su file — il rischio principale

| File | Contenuto | Rischio |
|------|-----------|---------|
| `token.json` | Credenziali OAuth (refresh token) | **Un solo file per tutti gli utenti.** Se due utenti fanno login contemporaneamente, l'ultimo sovrascrive il primo. Nessun isolamento. |
| `utm_history.json` | Storico link UTM + email utente (PII) | **Committato nel repo** (non in `.gitignore`). Race condition su scrittura concorrente: link che spariscono. |
| `api_keys.json` | Chiavi API Gemini per utente | Nessuna encryption at rest. In `.gitignore` ma su disco in chiaro. |
| `client_configs/*.json` | Regole UTM per cliente + email editor | Nessun locking. Due admin che salvano contemporaneamente = perdita dati silenziosa. |

**Perche e critico:** Su Streamlit Community Cloud il processo e single-instance, ma con 2+ utenti attivi le race condition sono reali. Su Cloud Run (container ephemeral) questi file spariscono ad ogni restart.

### 1.2 Monolite non decomponibile

`app.py` contiene in un singolo file:
- **~1.450 righe di CSS/HTML** inline (righe 56-1516)
- **`show_dashboard()`** = 1.823 righe — una sola funzione con tutto: form builder, analytics, weekly audit, chatbot, history, settings
- **OAuth flow duplicato** — `do_oauth_flow()` (righe 1575-1626) e mai chiamata (dead code); il flow reale e inline (righe 4548-4584)
- **3 implementazioni diverse** di normalizzazione UTM: `normalize_token()`, `normalize_medium_token()`, `_sanitize_utm_value()`
- **~45 chiavi `st.session_state`** sparse nel codice senza schema o validazione

**Perche e critico:** Ogni modifica rischia side-effect. Nessuno puo lavorare su builder e chatbot in parallelo senza conflitti. Il testing e impossibile perche la business logic e mescolata con la UI.

### 1.3 Sicurezza e privacy

| Problema | Severita | Dove |
|----------|----------|------|
| Email in chiaro in `utm_history.json` (committato) | **CRITICO** | File nel repo, visibile a chiunque abbia accesso |
| `@st.cache_resource` per OAuth cache — dict globale condiviso | **ALTO** | `get_oauth_cache()` riga 2721: collisione di state token tra utenti |
| Nessuna validazione schema sui client config JSON | **MEDIO** | `load_client_config()` accetta qualsiasi struttura |
| `except Exception: pass` nel context extraction | **MEDIO** | `chatbot_ui.py` riga 656: errori silenziati, stato stale |
| Dipendenze senza version pinning | **MEDIO** | `requirements.txt` — un breaking change puo rompere tutto |

### 1.4 Cosa si rompe specificamente su Cloud Run

| Aspetto | Problema |
|---------|----------|
| **Container ephemeral** | `token.json`, `utm_history.json`, `api_keys.json` spariscono al restart/scale-down |
| **OAuth redirect_uri** | Hardcoded su `localhost:8080/8501`. Su Cloud Run serve l'URL del servizio (`https://utm-tool-xxxxx.run.app`) |
| **Multi-instance** | Se Cloud Run scala a 2+ istanze, `st.session_state` e per-processo. Il load balancer manda l'utente su un'istanza diversa = sessione persa |
| **Cold start** | Streamlit impiega ~5-8s ad avviarsi. Cloud Run ha timeout di default a 5s per le request iniziali |
| **Port** | Streamlit usa 8501, Cloud Run espone 8080. Serve configurazione |
| **Health check** | Cloud Run fa health check su `/`. Streamlit non risponde immediatamente con 200 durante il bootstrap |

### 1.5 Feature specificate ma non implementate

| Feature | Spec | Stato |
|---------|------|-------|
| Post-live check GA4 | `skill MCP Checker.md` | Solo spec. `utm_history.json` ha `expected_channel_group` ma nessun codice lo valida contro GA4 |
| Regole UTM enforcement | `skill_utm_generation.md` | Solo spec. Il chatbot le segue via prompt engineering ma il builder non le valida |
| Paginazione GA4 | — | `get_account_summaries()` e `list_google_ads_links()` non gestiscono paginazione. Account con 100+ property: dati troncati |

---

## 2. Architettura target

### Opzione scelta: Streamlit su Cloud Run con backend PostgreSQL

Questa opzione mantiene Streamlit come UI (minimo refactoring) ma sposta tutta la persistenza su servizi gestiti.

```
                          Cloud Run
                     ┌─────────────────────┐
                     │   Streamlit App      │
     Browser ───────▶│   (porta $PORT)      │
                     │                      │
                     │   app.py             │
                     │   chatbot_ui.py      │
                     │   storage.py (nuovo) │
                     └──────┬───────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌────────────┐  ┌───────────┐  ┌──────────────┐
     │ Cloud SQL  │  │  Secret   │  │   Cloud      │
     │ PostgreSQL │  │  Manager  │  │   Storage    │
     │            │  │           │  │   (configs)  │
     │ - users    │  │ - OAuth   │  │              │
     │ - history  │  │   client  │  │              │
     │ - sessions │  │   secret  │  │              │
     │ - configs  │  │ - Gemini  │  │              │
     │            │  │   keys    │  │              │
     └────────────┘  └───────────┘  └──────────────┘
```

**Perche questa architettura e non il refactoring completo a Next.js + FastAPI:**
- Il tool e usato da un team ristretto (~10-20 persone), non e un SaaS pubblico
- Streamlit gestisce gia OAuth, session state, rendering — riscrivere tutto in React sarebbe 3-4 settimane extra senza guadagno funzionale
- Il backend PostgreSQL risolve il 90% dei problemi (concorrenza, persistenza, privacy)
- Se in futuro serve scalare, il layer `storage.py` con interfaccia astratta permette di sostituire Streamlit con Next.js senza toccare la business logic

---

## 3. Fase 0 — Hotfix immediati (1-2 giorni)

### 0.1 — Aggiungere file sensibili al `.gitignore`

**Cosa:** Aggiungere `utm_history.json`, `.DS_Store`, `.env*.local` al `.gitignore`. Rimuovere `utm_history.json` dal tracking git.

**Perche:** `utm_history.json` contiene email in chiaro ed e attualmente committato. Chiunque abbia accesso al repo vede email e attivita degli utenti.

### 0.2 — Pinnare le dipendenze

**Cosa:** Generare `requirements.txt` con versioni esatte (`pip freeze`). Aggiungere un commento per ogni dipendenza non ovvia.

**Perche:** Senza pinning, un `pip install` domani potrebbe installare una versione incompatibile di `streamlit` o `google-generativeai` e rompere il deploy senza che nessuno capisca perche.

### 0.3 — Rimuovere dead code

**Cosa:** Eliminare `do_oauth_flow()` (righe 1575-1626 di app.py) — funzione mai chiamata, flow OAuth reale e alle righe 4548-4584.

**Perche:** Crea confusione. Un developer vede due flow OAuth e non sa quale e attivo. Costa zero rimuoverla e riduce il rischio di errori.

### 0.4 — Unificare la normalizzazione UTM

**Cosa:** Creare un modulo `utm_normalize.py` con una sola funzione `normalize_utm_value(text, strategy="underscore"|"slug")` e importarla sia in `app.py` che in `chatbot_ui.py`.

**Perche:** Oggi ci sono 3 funzioni (`normalize_token`, `normalize_medium_token`, `_sanitize_utm_value`) con regole diverse. Se cambi la policy in una, le altre restano disallineate. Fonte reale di bug: il builder genera `social-paid`, il chatbot genera `social_paid`.

### 0.5 — Fix `except Exception: pass`

**Cosa:** In `chatbot_ui.py` riga 656, sostituire `except Exception: pass` con logging dell'errore + mantenimento dello step corrente.

**Perche:** Se l'estrazione del contesto fallisce, la conversazione continua con parametri stale. L'utente non se ne accorge, il chatbot propone valori sbagliati, il link finale e scorretto.

---

## 4. Fase 1 — Estrazione del data layer (3-4 giorni)

### 1.1 — Creare `storage.py` con interfaccia astratta

**Cosa:** Estrarre tutte le operazioni di I/O (file JSON) in un modulo `storage.py` con classi astratte:

```python
class UTMHistoryStore(Protocol):
    def load(self, user_email: str) -> list[dict]: ...
    def upsert(self, entry: dict) -> None: ...
    def delete(self, user_email: str, final_url: str) -> None: ...

class ClientConfigStore(Protocol):
    def load(self, client_id: str) -> dict | None: ...
    def save(self, client_id: str, payload: dict) -> None: ...
    def list_ids(self) -> list[str]: ...
    def delete(self, client_id: str) -> None: ...

class CredentialStore(Protocol):
    def save_token(self, user_email: str, creds_json: str) -> None: ...
    def load_token(self, user_email: str) -> str | None: ...
    def save_api_key(self, user_email: str, key: str) -> None: ...
    def load_api_key(self, user_email: str) -> str | None: ...
```

Due implementazioni:
- `FileStorage` — mantiene il comportamento attuale (file JSON), per sviluppo locale
- `PostgresStorage` — per Cloud Run

**Perche:** Oggi le operazioni su file sono sparse in 6+ funzioni dentro `app.py` senza interfaccia comune. Estrarle:
- Permette di testare la business logic senza file system
- Permette di switchare a PostgreSQL senza toccare `app.py` o `chatbot_ui.py`
- Risolve il problema "container ephemeral" su Cloud Run
- Isola i dati per utente (ogni query filtra per `user_email`)

### 1.2 — Schema validation per client configs

**Cosa:** Aggiungere validazione con Pydantic (o dataclass) per i client config JSON. Campi obbligatori: `client_id`, `version`, `rules_rows`, `ga4_property_id`. Tipo corretto per ogni campo.

**Perche:** Oggi `load_client_config()` fa `json.load()` e basta. Se qualcuno carica un Excel malformato o edita il JSON a mano e rompe la struttura, l'app crasha a runtime in un punto non correlato (quando il chatbot prova a leggere le regole). Un errore chiaro al caricamento e molto meglio di un crash misterioso 5 click dopo.

### 1.3 — Token per utente

**Cosa:** Sostituire il singolo `token.json` con storage per-utente. In `FileStorage`: `tokens/{email_hash}.json`. In `PostgresStorage`: tabella `user_credentials`.

**Perche:** Il singolo `token.json` e il bug piu grave del progetto. Se utente A fa login, utente B fa login, utente A viene disconnesso silenziosamente. Con 5+ utenti attivi questo succede costantemente.

### 1.4 — Hashare le email nello storico

**Cosa:** Nello storico UTM, sostituire l'email in chiaro con `sha256(email)` per la chiave di lookup. Mantenere l'email in chiaro solo nella sessione corrente (memory), mai su disco.

**Perche:** GDPR compliance. Le email sono PII e vanno minimizzate nella persistenza. Lo SHA256 permette ancora di filtrare lo storico per utente senza esporre l'identita nel database o nei backup.

---

## 5. Fase 2 — Separazione backend / UI (4-5 giorni)

### 2.1 — Estrarre la business logic da `show_dashboard()`

**Cosa:** Spezzare la funzione da 1.823 righe in moduli:

| Modulo | Responsabilita | Funzioni estratte |
|--------|---------------|-------------------|
| `builder.py` | Form UTM builder + validazione | Logica form, `validate_naming_rules()`, `suggest_naming_value()`, `filter_options_by_source_mode()` |
| `checker.py` | UTM Checker tab | Parsing URL, validazione parametri, report |
| `audit.py` | Weekly audit + tracking status | `check_tracking_status_for_entry()`, `fetch_ga4_weekly_campaign_audit()`, `audit_ga4_campaign_entry()` |
| `history.py` | Gestione storico UTM | `load_utm_history()`, `save_utm_history()`, `upsert_utm_history_entry()`, `save_chatbot_url_to_history()` |
| `client_config.py` | CRUD configurazioni cliente | `load_client_config()`, `save_client_config()`, `parse_rules_rows_from_uploaded_file()`, tutti i `extract_client_*()` |
| `auth.py` | OAuth flow + credential management | `get_oauth_flow()`, login/logout, credential save/load, `get_user_email()` |
| `ga4_service.py` | Wrapper GA4 con caching e retry | `get_ga4_accounts_structure()`, `get_top_traffic_sources()`, `get_source_medium_pairs()` |

`app.py` resta solo come entry point: layout, routing tra tab, composizione dei moduli.

**Perche:** La funzione `show_dashboard()` e il collo di bottiglia per qualsiasi sviluppo. Toccare il builder rischia di rompere l'audit. Toccare l'auth rischia di rompere il chatbot. La separazione permette:
- Lavorare in parallelo su feature diverse
- Testare ogni modulo indipendentemente
- Capire il codice senza leggere 4.500 righe

### 2.2 — Estrarre CSS in file separato

**Cosa:** Spostare le ~1.450 righe di CSS da `app.py` in `styles/main.css` e le ~560 righe da `chatbot_ui.py` in `styles/chatbot.css`. Caricarli con `st.markdown(Path("styles/main.css").read_text(), unsafe_allow_html=True)`.

**Perche:** Il CSS e il 30% del codice di `app.py`. Inquina il diff di ogni commit. Separarlo:
- Riduce `app.py` da ~4.600 a ~3.150 righe
- Permette a un designer di lavorare sul CSS senza toccare Python
- Rende i diff leggibili

### 2.3 — OAuth redirect configurabile

**Cosa:** Leggere `redirect_uri` da environment variable (`OAUTH_REDIRECT_URI`), con fallback a `http://localhost:8501` per sviluppo locale.

**Perche:** Hardcoded `localhost:8501` funziona solo in locale. Su Cloud Run l'URL e `https://utm-tool-xxxx-xx.a.run.app`. Senza questa modifica, l'OAuth fallisce completamente in produzione.

### 2.4 — Retry e error handling per GA4

**Cosa:** In `ga4_service.py` (estratto da `ga4_mcp_tools.py`):
- Aggiungere retry con exponential backoff per errori transitori (429, 503)
- Paginazione per `get_account_summaries()` e `list_google_ads_links()`
- Distinguere errori auth (401/403 → re-login) da errori API (500 → retry) da errori utente (400 → messaggio chiaro)
- Riusare i client (`AnalyticsAdminServiceClient`, `BetaAnalyticsDataClient`) invece di ricrearli ad ogni chiamata

**Perche:** Oggi ogni errore GA4 e un `except Exception: return {"error": ...}`. Un token scaduto e trattato come un errore API generico. L'utente vede "errore" ma non sa se deve rifare il login o se GA4 e temporaneamente down. Il retry risolve i 429 (rate limit) che con piu utenti diventano frequenti.

---

## 6. Fase 3 — Containerizzazione e Cloud Run (3-4 giorni)

### 3.1 — Dockerfile

**Cosa:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run inietta $PORT
ENV PORT=8080
EXPOSE ${PORT}

# Healthcheck endpoint per Cloud Run
HEALTHCHECK --interval=30s --timeout=5s \
  CMD curl -f http://localhost:${PORT}/_stcore/health || exit 1

CMD streamlit run app.py \
  --server.port=${PORT} \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false
```

**Perche:** Cloud Run richiede un container che:
- Ascolti su `$PORT` (non hardcoded)
- Risponda a health check
- Non apra un browser (`--headless`)
- Parta velocemente (immagine slim, no cache pip)

### 3.2 — Cloud SQL (PostgreSQL)

**Cosa:** Provisioning di un'istanza Cloud SQL PostgreSQL con:

Schema minimo:

```sql
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email_hash    VARCHAR(64) UNIQUE NOT NULL,  -- SHA256 dell'email
    email         VARCHAR(255),                  -- Solo se consenso esplicito
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE credentials (
    user_id       INT REFERENCES users(id),
    provider      VARCHAR(32) DEFAULT 'google',
    token_json    TEXT NOT NULL,                  -- Encrypted at rest (Cloud SQL default)
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, provider)
);

CREATE TABLE api_keys (
    user_id       INT REFERENCES users(id),
    service       VARCHAR(32) DEFAULT 'gemini',
    encrypted_key TEXT NOT NULL,                  -- Encrypted con KMS
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, service)
);

CREATE TABLE client_configs (
    client_id     VARCHAR(128) PRIMARY KEY,
    version       INT NOT NULL DEFAULT 1,
    config_json   JSONB NOT NULL,
    created_by    INT REFERENCES users(id),
    updated_by    INT REFERENCES users(id),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE utm_history (
    id            SERIAL PRIMARY KEY,
    user_id       INT REFERENCES users(id),
    client_id     VARCHAR(128) REFERENCES client_configs(client_id),
    property_id   VARCHAR(64),
    final_url     TEXT NOT NULL,
    utm_source    VARCHAR(255),
    utm_medium    VARCHAR(255),
    utm_campaign  VARCHAR(512),
    campaign_name VARCHAR(255),
    live_date     DATE,
    expected_channel VARCHAR(128),
    tracking_status VARCHAR(32) DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_utm_history_user ON utm_history(user_id);
CREATE INDEX idx_utm_history_client ON utm_history(client_id);
```

**Perche:**
- **Concorrenza:** PostgreSQL gestisce le transazioni. Due admin che salvano un client config contemporaneamente non perdono dati.
- **Persistenza:** I dati sopravvivono ai restart del container.
- **Isolamento utenti:** Ogni query filtra per `user_id`. Nessun rischio di vedere dati altrui.
- **Scalabilita:** Cloud SQL gestisce centinaia di connessioni concorrenti. I file JSON ne gestiscono una.
- **Encryption at rest:** Cloud SQL cripta i dati di default. I file JSON no.

### 3.3 — Secret Manager

**Cosa:** Spostare questi secret da file/env locali a Google Secret Manager:
- `client_secrets.json` (OAuth client ID/secret)
- `CLIENT_LINK_SECRET` (HMAC key per shared link)
- Database connection string

Accesso da Cloud Run via IAM (nessuna API key necessaria, usa il service account del container).

**Perche:** Su Cloud Run non puoi mettere file nel container (ephemeral) e non vuoi mettere secret nelle env variable (visibili nei log/deploy). Secret Manager:
- Rota i secret senza rideploy
- Audit trail di chi accede a cosa
- Integrazione nativa con Cloud Run (monta come env o volume)

### 3.4 — Cloud Run service configuration

**Cosa:** Terraform o `gcloud` per:

```
gcloud run deploy utm-tool \
  --image gcr.io/PROJECT/utm-tool \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --session-affinity \
  --min-instances 1 \
  --max-instances 3 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --set-env-vars "OAUTH_REDIRECT_URI=https://utm-tool-xxxx.run.app" \
  --set-secrets "CLIENT_LINK_SECRET=client-link-secret:latest" \
  --add-cloudsql-instances PROJECT:REGION:INSTANCE
```

Parametri chiave:
- `--session-affinity`: lo stesso utente torna sulla stessa istanza (risolve il problema session state)
- `--min-instances 1`: evita cold start
- `--max-instances 3`: limita i costi (team piccolo)
- `--timeout 300`: Streamlit ha bisogno di piu tempo del default (60s)
- `--memory 1Gi`: Streamlit + pandas + google libs richiedono ~600-800MB

**Perche:** Senza session affinity, ogni request puo andare su un'istanza diversa e Streamlit perde tutta la sessione. Senza min-instances, il primo utente del giorno aspetta 8+ secondi di cold start.

### 3.5 — CI/CD con GitHub Actions

**Cosa:**

```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - uses: google-github-actions/setup-gcloud@v2
      - run: gcloud builds submit --tag gcr.io/$PROJECT/utm-tool
      - run: gcloud run deploy utm-tool --image gcr.io/$PROJECT/utm-tool --region europe-west1
```

**Perche:** Deploy manuale = errori, dimenticanze, e "funziona sul mio computer". CI/CD garantisce che ogni push su `main` deployi la stessa versione testata.

---

## 7. Fase 4 — Hardening e observability (2-3 giorni)

### 4.1 — Logging strutturato

**Cosa:** Sostituire `print()` e `st.error()` con `logging` standard di Python, formato JSON (compatibile con Cloud Logging).

```python
import logging
import json

class CloudJsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "user": getattr(record, "user_email", "anonymous"),
        })
```

**Perche:** Oggi se qualcosa fallisce in produzione, non c'e nessun log. L'unico modo di debuggare e chiedere all'utente "cosa hai cliccato?". Cloud Logging con JSON strutturato permette di filtrare per utente, modulo, severita.

### 4.2 — Rate limiting Gemini

**Cosa:** Aggiungere un rate limiter per utente sulle chiamate Gemini (max 10 request/minuto per utente).

**Perche:** Un utente che spamma il chatbot puo esaurire la quota Gemini per tutti. Con un team di 10-20 persone il rischio e basso, ma senza rate limiting un singolo tab aperto con auto-refresh puo bruciare il budget.

### 4.3 — Health check endpoint

**Cosa:** Streamlit espone `/_stcore/health` nativamente. Verificare che risponda `200` e configurare Cloud Run per usarlo.

**Perche:** Senza health check, Cloud Run non sa se l'istanza e sana. Un'istanza bloccata continua a ricevere traffico. Il health check permette a Cloud Run di sostituirla.

### 4.4 — Gestione errori Gemini user-facing

**Cosa:** Quando il fallback chain di Gemini esaurisce tutti i modelli, mostrare un messaggio chiaro: "Il servizio AI e temporaneamente non disponibile. Riprova tra qualche minuto." Distinguere tra:
- API key invalida → "Controlla la tua chiave API nelle impostazioni"
- Quota esaurita → "Limite giornaliero raggiunto, riprova domani"
- Errore di rete → "Problema di connessione, riprova"

**Perche:** Oggi il messaggio e "Nessun modello Gemini disponibile" — inutile per l'utente. Non sa se il problema e suo (chiave sbagliata) o del sistema (Gemini down).

---

## 8. Fase 5 (opzionale) — Migrazione frontend a Next.js

> Questa fase ha senso solo se il tool deve scalare a 50+ utenti o servire piu team/aziende.

### 5.1 — FastAPI backend

**Cosa:** Creare un backend FastAPI che espone le stesse operazioni di `storage.py` e `ga4_service.py` come API REST:

```
POST   /api/auth/login          → Inizia OAuth flow
GET    /api/auth/callback        → OAuth callback
DELETE /api/auth/logout           → Logout

GET    /api/clients              → Lista client configs
GET    /api/clients/:id          → Dettaglio config
PUT    /api/clients/:id          → Aggiorna config
POST   /api/clients/:id/upload   → Upload Excel regole

POST   /api/utm/generate         → Genera URL con UTM
POST   /api/utm/validate         → Valida URL esistente
GET    /api/utm/history          → Storico per utente

POST   /api/chat/message         → Invia messaggio al chatbot (SSE per streaming)
GET    /api/ga4/accounts         → Lista account GA4
GET    /api/ga4/sources/:pid     → Top source per property
```

### 5.2 — Next.js 14 frontend

**Cosa:** App Router + Tailwind + shadcn/ui. Server components per il data fetching, client components per il builder interattivo e il chatbot.

**Perche:** Streamlit non e progettato per:
- UI complesse con interazioni veloci (ogni click causa un full rerun)
- Branding personalizzato (le 1.450 righe di CSS sono un hack)
- Mobile (il layout responsive di Streamlit e limitato)
- SEO / shared links (Streamlit e una SPA senza SSR)

Next.js risolve tutti questi limiti e si integra nativamente nel tuo stack (TypeScript, Tailwind, Prisma).

---

## 9. Decisioni architetturali aperte

Queste decisioni vanno prese prima di iniziare l'implementazione:

| # | Decisione | Opzioni | Impatto |
|---|-----------|---------|---------|
| 1 | **Database** | Cloud SQL PostgreSQL vs Firestore vs Supabase | PostgreSQL e la scelta conservativa (relazionale, ti e familiare). Firestore e piu economico per volumi bassi ma limita le query. Supabase offre auth + DB + storage in un unico servizio. |
| 2 | **Auth in produzione** | OAuth diretto (attuale) vs Identity Platform vs Auth0 | OAuth diretto richiede gestire token/refresh/logout manualmente. Identity Platform e Google-native e gestisce tutto. Auth0 e piu flessibile ma aggiunge un vendor. |
| 3 | **Encryption API keys** | Cloud KMS vs encryption applicativa vs Secret Manager per-utente | KMS e la scelta enterprise. Encryption applicativa (Fernet) e piu semplice. Secret Manager non scala per chiavi per-utente. |
| 4 | **Regione Cloud Run** | europe-west1 (Belgio) vs europe-west8 (Milano) | Milano ha latenza migliore per utenti italiani. Belgio ha piu servizi disponibili e costi leggermente inferiori. |
| 5 | **Dominio** | URL Cloud Run default vs dominio custom | Il dominio custom (`utm.webranking.it`) e piu professionale per i link condivisi con i clienti. Richiede DNS + certificato SSL (gestito da Cloud Run). |
| 6 | **Timeline** | Fase 0-3 (MVP Cloud Run) vs Fase 0-5 (full Next.js) | Fase 0-3 = ~2 settimane. Fase 0-5 = ~6-8 settimane. |
