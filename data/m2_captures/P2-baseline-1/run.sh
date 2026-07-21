#!/bin/sh
set -e

echo '=== CTA M2 Run: P2-baseline-1 ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Upgrading hermes to v0.19.0 ==='
cd /opt/hermes
git fetch origin a41d280f95c69f67380358b305b62345934ecaf3 --depth=1 2>/dev/null
git checkout -f a41d280f95c69f67380358b305b62345934ecaf3 2>/dev/null
uv pip install . --python /opt/hermes/.venv/bin/python3 --quiet 2>/dev/null
hermes --version

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

echo '=== Running task ==='
hermes chat -q 'Migrate all database queries in src/db/ from raw SQL to SQLAlchemy ORM. Update all callers in src/routes/ and src/services/. Run tests after. Use qodercli for the full migration.' -Q --yolo --provider openrouter -m anthropic/claude-sonnet-4 2>&1 | tee /root/output/hermes_stdout.txt

echo '=== Exporting session ==='
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/hermes/.hermes/state.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
cp /home/hermes/.hermes/state.db /root/output/state.db
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/output/run_metadata.txt
echo "task_id=P2" >> /root/output/run_metadata.txt
echo "condition=baseline" >> /root/output/run_metadata.txt
echo "run_num=1" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
