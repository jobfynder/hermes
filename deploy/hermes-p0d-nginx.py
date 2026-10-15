"""Install Hermes-only persistent NPM Advanced include; validate before reload.

Run on the NPM/Hermes host with: python3 SCRIPT POLICY_FILE BACKUP_DIRECTORY
No other proxy host, global configuration, IAM or API enablement is changed.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

def main():
    policy, backup = map(Path, sys.argv[1:])
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path('/opt/nginx-proxy-manager/data')
    host = root / 'nginx/proxy_host/1.conf'
    custom = root / 'nginx/custom/hermes-resource-limits.conf'
    database = root / 'database.sqlite'
    connection = sqlite3.connect(database)
    row = connection.execute('SELECT domain_names,advanced_config FROM proxy_host WHERE id=1').fetchone()
    assert row and json.loads(row[0]) == ['hermes.jobfynder.com'], 'Unexpected proxy host scope'
    marker = 'include /data/nginx/custom/hermes-resource-limits.conf;'
    assert marker not in (row[1] or ''), 'Limits already installed; inspect before rerunning'
    original = host.read_bytes()
    previous_custom = custom.read_bytes() if custom.exists() else None
    others = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'nginx/proxy_host').glob('*.conf') if p != host}
    (backup/'nginx-before.conf').write_bytes(original)
    (backup/'npm-advanced-before.json').write_text(json.dumps({'id':1,'advanced_config':row[1]}))
    if previous_custom is not None:
        (backup/'custom-before.conf').write_bytes(previous_custom)
    text = original.decode()
    assert text.count('  # Custom\n') == 1, 'Unknown NPM template; do not guess insertion'
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_bytes(policy.read_bytes())
    host.write_text(text.replace('  # Custom\n','  '+marker+'\n\n  # Custom\n',1))
    committed = False
    try:
        subprocess.run(['docker','exec','nginx-proxy-manager','nginx','-t'],check=True,capture_output=True)
        assert others == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'nginx/proxy_host').glob('*.conf') if p != host}
        # Persist in NPM's Advanced field so normal NPM regeneration retains it.
        connection.execute('BEGIN IMMEDIATE')
        current = connection.execute('SELECT advanced_config FROM proxy_host WHERE id=1').fetchone()[0]
        assert current == row[1], 'Concurrent NPM edit; abort'
        connection.execute('UPDATE proxy_host SET advanced_config=? WHERE id=1',((row[1] or '')+'\n'+marker+'\n',))
        connection.commit();committed = True
        subprocess.run(['docker','exec','nginx-proxy-manager','nginx','-s','reload'],check=True,capture_output=True)
    except Exception:
        connection.rollback()
        if committed:
            connection.execute('UPDATE proxy_host SET advanced_config=? WHERE id=1',(row[1],));connection.commit()
        host.write_bytes(original)
        if previous_custom is None:
            custom.unlink(missing_ok=True)
        else:
            custom.write_bytes(previous_custom)
        raise
    finally:
        connection.close()
    print('Hermes-only limits persisted; syntax validated; Nginx gracefully reloaded')

if __name__ == '__main__':
    main()
