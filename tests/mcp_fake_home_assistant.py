"""Home Assistant de mentira para os testes da casa (as ferramentas do servidor MCP do HA, por stdio)."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("home-assistant-teste")
STATES = {"luz do escritório": "on", "ar da sala": "off", "porta da frente": "locked", "portão da garagem": "closed"}


def _target(name: str | None, area: str | None, domain: list[str] | None) -> str:
    return " ".join(part for part in (name, area, ",".join(domain or [])) if part)


@server.tool()
def GetLiveContext() -> str:
    """Provides real-time information about the CURRENT state of the smart home devices."""
    lines = [f"- names: {name}\n  state: '{state}'" for name, state in STATES.items()]
    return "Live Context: An overview of the areas and the devices in this smart home:\n" + "\n".join(lines)


@server.tool()
def HassTurnOn(name: str | None = None, area: str | None = None, domain: list[str] | None = None) -> str:
    """Turns on/opens/locks a device or entity."""
    if name in STATES:
        STATES[name] = "on"
    return f"Turned on {_target(name, area, domain)}"


@server.tool()
def HassTurnOff(name: str | None = None, area: str | None = None, domain: list[str] | None = None) -> str:
    """Turns off/closes/unlocks a device or entity."""
    if name in STATES:
        STATES[name] = "off"
    return f"Turned off {_target(name, area, domain)}"


@server.tool()
def HassLightSet(name: str | None = None, area: str | None = None, brightness: int | None = None) -> str:
    """Sets the brightness or color of a light."""
    return f"Brightness of {_target(name, area, None)} set to {brightness}"


if __name__ == "__main__":
    server.run()
