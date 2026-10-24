#!/bin/zsh
# Запуск приложения на этом Mac: http://localhost:8501 (откроется само). Остановить — Ctrl+C.
cd "$(dirname "$0")"

# Python 3.11+ (pandas 3 не ставится на Python 3.9 из macOS)
if [ ! -x .venv/bin/python ]; then
  py=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v $c >/dev/null && $c -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then py=$c; break; fi
  done
  if [ -z "$py" ]; then
    echo "Нужен Python 3.11 или новее. Установите: brew install python (Homebrew — https://brew.sh) или с https://www.python.org/downloads/"
    exit 1
  fi
  echo "Создаю окружение .venv ($($py --version))…"
  $py -m venv .venv || exit 1
fi

# Зависимости — при первом запуске и после каждого изменения requirements.txt
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Устанавливаю зависимости…"
  .venv/bin/pip install -q -r requirements.txt && touch .venv/.installed || exit 1
fi

# Прежний запуск держит в памяти старый код (Streamlit не перечитывает browser_agent.py) — останавливаем его.
# Только сам сервер (LISTEN): простой lsof -ti tcp:8501 задел бы и сетевой процесс Chrome. Агент — отдельный процесс, он не прервётся.
old=$(lsof -ti tcp:8501 -sTCP:LISTEN)
if [ -n "$old" ]; then
  echo "Перезапускаю приложение, запущенное раньше…"
  kill $old
  for i in {1..20}; do lsof -ti tcp:8501 -sTCP:LISTEN >/dev/null || break; sleep 0.5; done
fi

# Браузер — когда сервер уже отвечает
(for i in {1..120}; do curl -sf http://localhost:8501/_stcore/health >/dev/null && { open http://localhost:8501; exit; }; sleep 0.5; done) &
exec .venv/bin/streamlit run app.py
