#!/bin/sh
# Seed bot_state.json into the volume on first deploy
if [ ! -f /app/data/bot_state.json ] && [ -f /app/bot_state.seed.json ]; then
    cp /app/bot_state.seed.json /app/data/bot_state.json
    echo "[start.sh] Seeded bot_state.json from image into volume."
fi

exec python main.py
