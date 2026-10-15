import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from care_console.link import link_run
from care_console.server import create_app


def test_run_is_bound_before_file_exists_and_keeps_its_identity(tmp_path):
    external = tmp_path / 'interaction.db'
    with sqlite3.connect(external) as db:
        db.executescript("CREATE TABLE elderly_person(id INTEGER PRIMARY KEY,name TEXT,age INTEGER,room TEXT,enabled INTEGER); CREATE TABLE elder_need(elderly_id INTEGER,status TEXT); INSERT INTO elderly_person VALUES(7,'测试老人',76,'201',1); INSERT INTO elderly_person VALUES(8,'另一老人',75,'202',1);")
    app = create_app(tmp_path / 'console.db', roots=[tmp_path], interaction_db=external, background=False)
    with TestClient(app) as client:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.forward()

            def do_POST(self):
                self.forward()

            def forward(self):
                if self.path == '/escaped':
                    server.escaped_hits += 1
                    self.send_response(403)
                    self.end_headers()
                    return
                if server.redirect:
                    self.send_response(302)
                    self.send_header('Location', '/escaped')
                    self.end_headers()
                    return
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                response = client.request(self.command, self.path, content=body,
                                          headers={'X-Care-Console': '1', 'Content-Type': 'application/json'})
                self.send_response(response.status_code)
                self.end_headers()
                self.wfile.write(response.content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.redirect = False
        server.escaped_hits = 0
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            path = tmp_path / 'events.jsonl'
            logs = [('anomaly', str(path))]
            result = link_run(url, 7, logs, 'replay')
            assert not path.exists() and len(result['sources']) == 1
            assert link_run(url, 7, logs, 'replay')['sources'][0]['id'] == result['sources'][0]['id']
            with pytest.raises(ValueError, match='其他身份'):
                link_run(url, 8, logs, 'replay')
            path.write_text(json.dumps({'event_id': 'linked-before-start', 'type': 'fall', 'level': 'L3', 'time': 1})+'\n')
            client.post('/api/sync', headers={'X-Care-Console': '1'})
            assert client.get('/api/events').json()['total'] == 1
            server.redirect = True
            with pytest.raises(ValueError, match='拒绝接入'):
                link_run(url, 7, logs, 'replay')
            assert server.escaped_hits == 0
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


def test_link_rejects_external_workstation():
    with pytest.raises(ValueError, match='本机'):
        link_run('http://example.com', 7, [('anomaly', '/tmp/events.jsonl')])


@pytest.mark.parametrize('scene', ['companion_entertainment', 'care_consultation_support',
                                  'contact_family', 'social_activity_support'])
def test_launcher_keeps_registered_identity_and_journal(tmp_path, scene):
    root = Path(__file__).resolve().parents[1]
    speech = tmp_path / 'github-product/g1-dex3-care-vla/speech'
    directory = speech / 'scenarios' / scene
    directory.mkdir(parents=True)
    shutil.copy(root / 'speech/companion_recording_env.sh', speech)
    shutil.copy(root / 'speech/scenarios' / scene / 'run_g1_demo.sh', directory)
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    fake_python = binaries / 'python3'
    fake_python.write_text(f'#!{sys.executable}\n'+'''import argparse,json,os,sys
from pathlib import Path
if sys.argv[1]=='-':
    sys.exit(0)
p=argparse.ArgumentParser()
p.add_argument('--elder-id','--elderly-id',dest='elderly_id')
p.add_argument('--interaction-log','--record-log',dest='log')
p.add_argument('--record-mode',default='live')
args,_=p.parse_known_args(sys.argv[1:])
name='registered.json' if sys.argv[1]=='-m' else 'produced.json'
Path(os.environ['CAPTURE_ROOT'],name).write_text(json.dumps(vars(args)))
print('{}')
''')
    fake_python.chmod(0o755)
    curl = binaries / 'curl'
    curl.write_text('#!/bin/sh\nexit 0\n')
    curl.chmod(0o755)
    env = {**os.environ, 'PATH': str(binaries)+os.pathsep+os.environ['PATH'],
           'HOME': str(tmp_path), 'G1_ELDERLY_ID': '7', 'CAPTURE_ROOT': str(tmp_path)}
    subprocess.run(['bash', str(directory / 'run_g1_demo.sh'), '--elder-id', '8',
                    '--elderly-id', '9', '--record-log', str(tmp_path / 'wrong.jsonl'),
                    '--record-mode', 'replay'], env=env, check=True, capture_output=True, timeout=10)
    registered = json.loads((tmp_path / 'registered.json').read_text())
    produced = json.loads((tmp_path / 'produced.json').read_text())
    assert registered['elderly_id'] == produced['elderly_id'] == '7'
    assert registered['log'] == produced['log']
    assert produced['record_mode'] == 'live'
