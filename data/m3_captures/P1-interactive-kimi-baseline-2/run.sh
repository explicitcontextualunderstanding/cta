#!/bin/sh
set -e

echo '=== CTA M3 Run: P1-interactive-kimi-baseline-2 ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Upgrading hermes to v0.19.0 ==='
cd /opt/hermes
git fetch origin a41d280f95c69f67380358b305b62345934ecaf3 --depth=1 2>/dev/null
git checkout -f a41d280f95c69f67380358b305b62345934ecaf3 2>/dev/null
uv pip install . --python /opt/hermes/.venv/bin/python3 --quiet 2>/dev/null
hermes --version

echo '=== Configuring model: opencode-go/kimi-k2.7-code ==='
mkdir -p /home/hermes/.hermes
cat > /home/hermes/.hermes/config.yaml << 'HERMESCFG'
model:
  default: kimi-k2.7-code
  provider: opencode-go
  base_url: https://opencode.ai/zen/go/v1
  api_mode: chat_completions
HERMESCFG
chown -R hermes:hermes /home/hermes/.hermes 2>/dev/null || true

echo '=== Installing qodercli 1.1.1 ==='
npm install -g @qoder-ai/qodercli@1.1.1 2>/dev/null
qodercli --version


echo '=== Baseline: no skill installed ==='
rm -rf /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli 2>/dev/null || true


echo '=== Setting up workspace ==='
cp -r /root/fixture /root/workspace
cd /root/workspace
git init -q
git add -A
git commit -q -m "fixture baseline" --allow-empty 2>/dev/null || true

echo '=== Running interactive-mode task ==='
hermes chat -q 'Use qodercli in interactive mode to implement a REST API authentication endpoint in src/routes/auth.py with JWT token validation middleware in src/middleware/token.py. Launch qodercli with the -i flag using background=true and pty=true, then guide it through the implementation step by step using process commands (poll, write, log). After qodercli finishes, verify the implementation by running the test suite.' -Q --yolo --provider opencode-go -m kimi-k2.7-code 2>&1 | tee /root/output/hermes_stdout.txt || true
HERMES_EXIT=$?

echo '=== Exporting session ==='
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/hermes/.hermes/state.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
cp /home/hermes/.hermes/state.db /root/output/state.db
echo "hermes_exit=$HERMES_EXIT" >> /root/output/run_metadata.txt
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/output/run_metadata.txt
echo "task_id=P1-interactive" >> /root/output/run_metadata.txt
echo "condition=baseline" >> /root/output/run_metadata.txt
echo "run_num=2" >> /root/output/run_metadata.txt
echo "model=kimi-k2.7-code" >> /root/output/run_metadata.txt
echo "provider=opencode-go" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
