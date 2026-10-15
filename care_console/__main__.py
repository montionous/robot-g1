import argparse
from pathlib import Path

import uvicorn

from .server import create_app

parser = argparse.ArgumentParser(description="老人陪伴护理工作台")
parser.add_argument("--port", type=int, default=8766)
parser.add_argument("--db", type=Path)
parser.add_argument('--interaction-db', type=Path)
parser.add_argument("--allowed-host", action="append", default=[])
parser.add_argument("--deployment", choices=["local", "cloud"], default="local")
parser.add_argument('--auth-file', type=Path)
args = parser.parse_args()
if not 1 <= args.port <= 65535:
    parser.error("port must be between 1 and 65535")
uvicorn.run(create_app(args.db, interaction_db=args.interaction_db, allowed_hosts=args.allowed_host, deployment=args.deployment, auth_file=args.auth_file), host="127.0.0.1", port=args.port)
