from __future__ import annotations

from .agent import AccessAgent, build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "run"
    agent = AccessAgent()

    if command == "run":
        agent.start()
    elif command == "code":
        agent.print_pairing_code()
    elif command == "install-startup":
        agent.install_startup_shortcut()
    elif command == "uninstall":
        agent.uninstall()
    else:
        parser.print_help()
