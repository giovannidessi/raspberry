#!/usr/bin/env bash
#
# Installa (o aggiorna) Carhunt sul Raspberry con un comando solo.
#
#   curl -fsSL https://raw.githubusercontent.com/giovannidessi/raspberry/BRANCH/projects/ai-apps/carhunt/deploy.sh | bash
#
# oppure, se il repo e' gia' clonato:  cd ~/raspberry/projects/ai-apps/carhunt && ./deploy.sh
#
# Variabili opzionali (per l'uso non interattivo):
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CARHUNT_PORT, CARHUNT_BRANCH, CARHUNT_DIR

set -euo pipefail

REPO_URL="${CARHUNT_REPO:-https://github.com/giovannidessi/raspberry.git}"
BRANCH="${CARHUNT_BRANCH:-claude/car-search-telegram-notifications-n4mtho}"
TARGET_DIR="${CARHUNT_DIR:-$HOME/raspberry}"
PORT="${CARHUNT_PORT:-8080}"

# quando lo script arriva da una pipe, le domande vanno lette dal terminale
if [ -e /dev/tty ] && [ -r /dev/tty ]; then TTY=/dev/tty; else TTY=/dev/stdin; fi

info()  { printf '\033[1;34m▶\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

ask() { # ask <messaggio> <variabile>
    local prompt="$1" __var="$2" answer=""
    while [ -z "$answer" ]; do
        printf '%s ' "$prompt" > /dev/tty 2>/dev/null || printf '%s ' "$prompt"
        read -r answer < "$TTY" || die "serve un terminale interattivo (oppure passa $__var come variabile d'ambiente)"
    done
    printf -v "$__var" '%s' "$answer"
}

# ---------------------------------------------------------------- prerequisiti
command -v git >/dev/null 2>&1 || die "git non installato: sudo apt-get install -y git"

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    die "Docker Compose non trovato. Installa Docker con lo script del repo:
    bash ~/raspberry/config_scripts.sh   (poi disconnettiti e riconnettiti)"
fi

docker info >/dev/null 2>&1 || die "il demone Docker non risponde. Prova:
    sudo systemctl start docker
    sudo usermod -aG docker \$USER   (poi esci e rientra dalla sessione)"

# -------------------------------------------------------------- codice sorgente
if [ -d "$TARGET_DIR/.git" ]; then
    info "aggiorno il repo in $TARGET_DIR"
    git -C "$TARGET_DIR" fetch --quiet origin "$BRANCH"
    git -C "$TARGET_DIR" checkout --quiet "$BRANCH"
    git -C "$TARGET_DIR" merge --quiet --ff-only "origin/$BRANCH" || \
        warn "ci sono modifiche locali: il repo non e' stato aggiornato"
else
    info "clono il repo in $TARGET_DIR"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
fi

APP_DIR="$TARGET_DIR/projects/ai-apps/carhunt"
[ -d "$APP_DIR" ] || die "cartella $APP_DIR non trovata"
cd "$APP_DIR"

# ------------------------------------------------------------------ credenziali
if [ -f .env ]; then
    ok "file .env gia' presente, lo riuso (cancellalo se vuoi rifare la configurazione)"
else
    info "configurazione Telegram"
    TOKEN="${TELEGRAM_BOT_TOKEN:-}"
    CHAT="${TELEGRAM_CHAT_ID:-}"

    if [ -z "$TOKEN" ]; then
        echo "  Su Telegram: @BotFather -> /newbot -> copia il token."
        ask "  Token del bot:" TOKEN
    fi

    if [ -z "$CHAT" ]; then
        echo "  Ora apri la chat con il tuo bot e mandagli un messaggio qualsiasi."
        ask "  Quando l'hai fatto scrivi ok e premi invio:" CONFIRM
        CHAT="$(curl -fsS --max-time 20 "https://api.telegram.org/bot${TOKEN}/getUpdates" 2>/dev/null \
                | grep -o '"chat":{"id":-\?[0-9]*' | head -1 | grep -o '\-\?[0-9]*$' || true)"
        if [ -n "$CHAT" ]; then
            ok "chat id trovato automaticamente: $CHAT"
        else
            warn "non sono riuscito a leggerlo da solo (hai scritto al bot?)"
            echo "  Aprilo a mano: https://api.telegram.org/bot<TOKEN>/getUpdates"
            ask "  Chat id:" CHAT
        fi
    fi

    umask 077
    sed -e "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TOKEN}|" \
        -e "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${CHAT}|" \
        -e "s|^CARHUNT_PORT=.*|CARHUNT_PORT=${PORT}|" \
        .env.example > .env
    chmod 600 .env
    ok "scritto .env (permessi 600, non finisce mai su git)"
fi

# ------------------------------------------------------------------------ build
info "costruisco l'immagine e avvio il servizio (la prima volta ci mette qualche minuto)"
$COMPOSE up -d --build

# ------------------------------------------------------------------- verifiche
info "attendo che il servizio risponda"
for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        HEALTHY=1; break
    fi
    sleep 2
done

if [ "${HEALTHY:-0}" != "1" ]; then
    $COMPOSE logs --tail 40 carhunt || true
    die "il servizio non risponde su http://127.0.0.1:${PORT} — log qui sopra"
fi
ok "servizio attivo"

info "mando un messaggio di prova su Telegram"
if $COMPOSE exec -T carhunt python -m app.cli telegram-test; then
    ok "controlla Telegram: dovresti aver ricevuto il messaggio di prova"
else
    warn "Telegram non ha accettato l'invio: controlla token e chat id in $APP_DIR/.env"
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "Carhunt e' su   http://${IP:-<ip-del-raspberry>}:${PORT}"
echo "   log:      cd $APP_DIR && $COMPOSE logs -f"
echo "   stop:     cd $APP_DIR && $COMPOSE down"
echo "   aggiorna: $APP_DIR/deploy.sh"
