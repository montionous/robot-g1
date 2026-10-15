"""Bind this run's module journals before starting their producers."""
import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def link_run(base_url, elderly_id, logs, mode='live'):
    url = urlparse(base_url)
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost'} or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment:
        raise ValueError('工作台接入只允许本机 HTTP 地址或本机 SSH 转发端口')
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(base_url.rstrip('/') + path, data=data,
                      headers={'X-Care-Console': '1', 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=10) as response:
                content = response.read(1024 * 1024 + 1)
        except HTTPError as exc:
            raise ValueError(f'工作台拒绝接入：{exc.read(2000).decode(errors="replace")}') from exc
        if len(content) > 1024 * 1024:
            raise ValueError('工作台响应超限')
        return json.loads(content)

    overview = request('/api/overview')
    if overview['interaction']['status'] != 'ready':
        raise ValueError(overview['interaction']['error'])
    key = overview['interaction']['source_key']
    profile = request('/api/elders/from-interaction', {'elderly_id': elderly_id, 'source_key': key})
    sources = request('/api/sources')
    linked = []
    for module, path in logs:
        existing = next((s for s in sources if s['path'] == path and s['enabled']), None)
        if existing:
            if existing['elder_id'] != profile['id'] or existing['module'] != module or existing['mode'] != mode:
                raise ValueError('本轮日志已绑定其他身份、模块或采集类型')
            linked.append(existing)
        else:
            linked.append(request('/api/sources', {'elder_id': profile['id'], 'module': module,
                                                  'path': path, 'mode': mode}))
    return {'elder_id': profile['id'], 'elderly_id': str(elderly_id), 'sources': linked}


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--console-url', default='http://127.0.0.1:8766')
    parser.add_argument('--elderly-id', required=True, type=int)
    parser.add_argument('--mode', choices=['live', 'replay'], default='live')
    for module in ('emotion', 'anomaly', 'interaction'):
        parser.add_argument(f'--{module}-log', action='append', type=Path, default=[])
    args = parser.parse_args()
    logs = [(module, str(path.resolve())) for module in ('emotion', 'anomaly', 'interaction')
            for path in getattr(args, module + '_log')]
    if not logs:
        parser.error('请指定本轮模块日志')
    try:
        result = link_run(args.console_url, args.elderly_id, logs, args.mode)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'care_console_link_failed: {exc}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
