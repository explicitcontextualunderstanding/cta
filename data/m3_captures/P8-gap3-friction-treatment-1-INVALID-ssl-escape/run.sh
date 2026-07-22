#!/bin/sh
set -e

echo '=== CTA Gap3 Run: P8-gap3-friction-treatment-1 ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Hermes pre-installed in friction image (editable, pinned commit) ==='
hermes --version

echo '=== Applying tools overlay (NDJSON patch — editable install, no pip needed) ==='
cp /root/tools_overlay/*.py /opt/hermes/tools/

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

echo '=== Installing qodercli skill (treatment variant) ==='
mkdir -p /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli
cp /root/skill/SKILL.md /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli/SKILL.md

echo '=== Setting up workspace ==='
cd /root/workspace
git status >/dev/null 2>&1 || { git init -q && git add -A && git commit -q -m "fixture baseline" --allow-empty 2>/dev/null || true; }

echo '=== Running Gap3 friction task ==='
hermes chat -q 'Use qodercli to implement a REST API authentication endpoint with JWT token validation in /root/workspace/src/routes/auth.py and middleware in /root/workspace/src/middleware/token.py. Use qodercli in BACKGROUND mode (background=true, pty=true) and monitor it with process(poll). Run pytest to verify the implementation.' -Q --yolo -m kimi-k2.7-code 2>&1 | tee /root/output/hermes_stdout.txt || true
HERMES_EXIT=$?

echo '=== Exporting workspace diff ==='
cd /root/workspace && git diff --stat > /root/output/git_diff.txt 2>/dev/null || true
cd /root/workspace && git diff > /root/output/git_diff_full.patch 2>/dev/null || true

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
echo "experiment=gap3" >> /root/output/run_metadata.txt
echo "adaptation=treatment" >> /root/output/run_metadata.txt
echo "run_num=1" >> /root/output/run_metadata.txt
echo "model=kimi-k2.7-code" >> /root/output/run_metadata.txt
echo "provider=opencode-go" >> /root/output/run_metadata.txt
echo "container_image=registry.rossollc.com/hermes:friction" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
