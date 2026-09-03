# projects/ai-apps

Le app che girano sul Raspberry, una cartella per app.

| App | Cosa fa | Porta | Avvio |
|---|---|---|---|
| [`carhunt`](carhunt/) | cerca auto usate sui portali, dà un punteggio di convenienza e manda gli annunci nuovi su Telegram | `8080` | [`carhunt/deploy.sh`](carhunt/deploy.sh) |

## Convenzioni

Ogni app è autonoma: ha il suo `docker-compose.yml`, il suo `.env`
(mai committato: sta in `.gitignore`), il suo volume Docker per i dati e un
`README.md` che spiega come si avvia. Si accende e si spegne da sola con
`docker compose up -d` / `down` dalla sua cartella, senza dipendere dalle altre.

Le porte vanno tenute distinte fra un'app e l'altra: si cambiano dalla variabile
`*_PORT` nel `.env`, senza toccare il compose.
