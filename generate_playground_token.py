from __future__ import annotations

import argparse
import datetime as dt
import secrets

from livekit import api
from dotenv import load_dotenv

load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gera um JWT do LiveKit para testar o Jarvis no playground.",
    )
    parser.add_argument(
        "--room",
        default="jarvis-playground",
        help="Nome da sala do LiveKit. Padrão: jarvis-playground",
    )
    parser.add_argument(
        "--identity",
        default=f"web-user-{secrets.token_hex(4)}",
        help="Identity do participante que vai abrir o playground.",
    )
    parser.add_argument(
        "--name",
        default="Gabriel",
        help="Nome do participante no LiveKit.",
    )
    parser.add_argument(
        "--agent-name",
        default="jarvis",
        help="Nome do agente registrado no worker. Padrão: jarvis",
    )
    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=60,
        help="Tempo de vida do token em minutos. Padrão: 60",
    )
    return parser


def create_token(
    *,
    room: str,
    identity: str,
    name: str,
    agent_name: str,
    ttl_minutes: int,
) -> str:
    room_config = api.RoomConfiguration()
    room_config.agents.append(api.RoomAgentDispatch(agent_name=agent_name))

    token = (
        api.AccessToken()
        .with_identity(identity)
        .with_name(name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(room_config)
        .with_ttl(dt.timedelta(minutes=ttl_minutes))
        .to_jwt()
    )
    return token


def main() -> int:
    args = build_parser().parse_args()

    token = create_token(
        room=args.room,
        identity=args.identity,
        name=args.name,
        agent_name=args.agent_name,
        ttl_minutes=args.ttl_minutes,
    )

    print(f"Room: {args.room}")
    print(f"Identity: {args.identity}")
    print(f"Agent: {args.agent_name}")
    print("Token:")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
