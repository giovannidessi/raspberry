# 🚗 Carhunt

Cerca auto usate sui portali di annunci, dà un **punteggio di convenienza** a ogni annuncio
in base ai criteri che imposti tu, e ti manda su **Telegram** solo le novità che valgono la pena.
Pensato per girare 24/7 su un Raspberry Pi con Docker.

```
webapp (browser)  ──►  FastAPI  ──►  provider (Subito, AutoScout24, demo)
                          │
                          ├── SQLite  (annunci già visti, storico prezzi)
                          ├── scoring (stima di mercato + pesi personalizzati)
                          └── APScheduler ── ogni ora ──► notifiche Telegram
```

## Cosa fa

- **Ricerche salvate**: marca, modello, budget, anni, km, alimentazione, cambio, potenza,
  venditore, parole obbligatorie/da escludere, distanza da casa.
- **Controllo automatico ogni ora** (intervallo configurabile) su tutte le ricerche attive.
- **Notifiche Telegram** per gli annunci *nuovi* sopra la soglia di punteggio e per i
  *ribassi di prezzo* su annunci già visti. Al primo giro manda un solo riepilogo, non 40 messaggi.
- **Punteggio + commento in italiano** su ogni annuncio: quanto è sotto o sopra il prezzo
  di mercato, se ha troppi km, se è più recente della media, cosa manca fra le dotazioni cercate.
- **Pesi regolabili dalla webapp**: sposti i cursori e la classifica si riordina subito,
  senza salvare e senza rifare le ricerche.

## Avvio rapido sul Raspberry

Docker e docker compose si installano con lo script già presente nel repo
(`../config_scripts.sh`).

```bash
cd carhunt
cp .env.example .env
nano .env               # metti TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
docker compose up -d --build
```

La webapp è su `http://<ip-del-raspberry>:8080`.

### Come si ottengono token e chat id di Telegram

1. Su Telegram scrivi a **@BotFather** → `/newbot` → scegli nome e username → copia il token.
2. Apri una chat con il bot appena creato e mandagli un messaggio qualsiasi (serve a
   sbloccare l'invio: Telegram non lascia scrivere a chi non ti ha mai scritto).
3. Apri `https://api.telegram.org/bot<TOKEN>/getUpdates` nel browser e copia il valore di
   `"chat":{"id": ...}`.
4. Incolla i due valori in `.env`, poi `docker compose up -d` e premi **Prova Telegram**
   nella webapp.

Per un gruppo di famiglia: aggiungi il bot al gruppo, scrivi un messaggio nel gruppo e usa
l'id (negativo) che compare in `getUpdates`.

## Come funziona il punteggio

Ogni annuncio riceve un voto da 0 a 100. Il voto è la media pesata di sette voci, e i pesi
(0–10) li decidi dalla webapp:

| Voce | Cosa misura |
|---|---|
| **Affare rispetto al mercato** | quanto il prezzo sta sotto la stima per quel modello con quei km e quell'età |
| **Prezzo assoluto** | quanto costa rispetto al budget e agli altri annunci trovati |
| **Chilometraggio** | posizione rispetto agli altri annunci della stessa ricerca |
| **Anno** | quanto è recente rispetto agli altri |
| **Potenza** | CV, con penalità se sotto il minimo richiesto |
| **Vicinanza** | distanza in linea d'aria da casa (serve lat/lon nella ricerca) |
| **Dotazioni** | quante delle parole in "meglio se ha" compaiono nell'annuncio |

La **stima di mercato** non viene da un listino: si ricava dagli annunci raccolti dalla
stessa ricerca. Con almeno 8 annunci completi si adatta una regressione
`prezzo ≈ base + a·km + b·anni` (scartando i prezzi fuori scala); con meno dati si usa la
mediana e il commento lo dice esplicitamente. Più giri fa il job, più la stima è affidabile.

Il commento sotto ogni annuncio spiega il voto in parole:

```
💰 Prezzo 18% sotto la stima di mercato (13.400 €) per km ed eta' simili.
⚠️ Chilometraggio alto: 168.000 km, 31% sopra la media.
✨ Include: navigatore, sensori.
📍 Bologna a circa 64 km da casa.
```

## Portali supportati

| Chiave | Portale | Note |
|---|---|---|
| `subito` | Subito.it | usa l'API JSON pubblica del sito |
| `autoscout24` | AutoScout24.it | legge il blob `__NEXT_DATA__` della pagina risultati |
| `demo` | annunci finti | nessuna rete: serve per provare l'app e le notifiche |

I portali cambiano struttura ogni tanto: quando succede, la ricerca continua a funzionare
con gli altri (il giro finisce in stato `parziale` e la webapp mostra l'errore). Per capire
cosa si è rotto, dal Raspberry:

```bash
docker compose exec carhunt python -m app.cli probe subito --make Volkswagen --model Golf --price-max 15000
docker compose exec carhunt python -m app.cli probe autoscout24 --make Volkswagen --model Golf --json
```

Se stampa 0 annunci, o campi sempre vuoti, va aggiornato il parser in
`app/providers/<portale>.py` — la funzione `parse()` è separata dalla parte di rete apposta
per poterla correggere e testare su un file salvato.

Una nota onesta: interrogare questi siti da un programma è una zona grigia rispetto ai loro
termini di servizio. Il codice fa una richiesta alla volta con una pausa fra l'una e l'altra
(`CARHUNT_REQUEST_DELAY`) e un giro all'ora, cioè meno traffico di una persona che aggiorna
la pagina; resta comunque uso personale, non ridistribuibile.

## Aggiungere un altro portale

1. Crea `app/providers/miosito.py` con una classe che estende `Provider`, una funzione
   `parse(payload) -> list[Listing]` e il metodo `search(criteria, limit)`.
2. Registrala in `app/providers/__init__.py`.
3. Aggiungi una fixture in `tests/fixtures/` e un test su `parse()`.

Il resto (dedup, punteggio, notifiche, webapp) funziona senza modifiche.

## Sviluppo

```bash
uv venv .venv && . .venv/bin/activate
uv pip install -r requirements.txt pytest
python -m pytest -q
CARHUNT_DB=/tmp/carhunt.sqlite3 uvicorn app.main:app --reload
```

## Configurazione (.env)

| Variabile | Default | A cosa serve |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | token del bot di @BotFather |
| `TELEGRAM_CHAT_ID` | — | destinatario di default (una ricerca può averne uno suo) |
| `CARHUNT_INTERVAL_MINUTES` | `60` | ogni quanto gira il controllo automatico |
| `CARHUNT_RUN_ON_START` | `false` | fa un giro subito all'avvio del container |
| `CARHUNT_PORT` | `8080` | porta della webapp sul Raspberry |
| `CARHUNT_REQUEST_DELAY` | `1.5` | secondi di pausa fra due richieste allo stesso portale |
| `CARHUNT_HTTP_TIMEOUT` | `25` | timeout delle richieste |
| `CARHUNT_MAX_RESULTS` | `60` | quanti annunci al massimo per portale per giro |

I dati stanno nel volume Docker `carhunt-data` (`/data/carhunt.sqlite3`): backup con
`docker compose cp carhunt:/data/carhunt.sqlite3 ./backup.sqlite3`.
